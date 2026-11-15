"""Tests de `android/apk.py` (étape 2, docs/android-adb.md) : plan
d'installation tiré d'une fiche, téléchargement contrôlé d'un APK,
`adb install`. Aucun adb ni réseau réel : `runner` et `opener` injectés."""

from __future__ import annotations

import hashlib
import io
import subprocess
from types import SimpleNamespace

import pytest

from r36s_studio.android import apk
from r36s_studio.consoles_diverses.procedures.fiche import procedure_depuis_json

_URL = "https://github.com/exemple/projet/releases/latest/download/appli.apk"
_APK = b"PK\x03\x04" + b"contenu" * 100


def _procedure(**changes):
    data = {
        "id": "appli-installation",
        "titre": "Installer Appli",
        "firmware": "Appli",
        "version": "dernière",
        "mode": "adb",
        "efface_donnees": False,
        "plateformes": ["windows", "macos", "linux"],
        "telechargements": [{"nom": "appli.apk", "url": _URL, "paquet": "io.exemple.appli"}],
        "etapes": [
            {"ordre": 1, "action": "activer_debogage_usb", "automatisable": "non", "detail": "…"},
            {"ordre": 2, "action": "telecharger", "automatisable": "oui", "detail": "…"},
            {"ordre": 3, "action": "installer_apk", "automatisable": "oui", "detail": "…"},
        ],
        "source_url": "https://github.com/exemple/projet",
    }
    data.update(changes)
    return procedure_depuis_json(data)


class _Reponse(io.BytesIO):
    def __init__(self, data: bytes, length=None):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data) if length is None else length)}


def _opener(data: bytes, length=None):
    return lambda requete, timeout=None: _Reponse(data, length)


def _result(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _fichier(sha256=None):
    return apk.ApkFile(nom="appli.apk", url=_URL, paquet="io.exemple.appli", sha256=sha256)


# --- Plan ------------------------------------------------------------------


def test_plan_from_procedure_reads_the_apk_and_its_package():
    plan = apk.plan_from_procedure(_procedure())

    assert plan is not None
    assert plan.titre == "Installer Appli"
    assert [(f.nom, f.url, f.paquet, f.sha256) for f in plan.fichiers] == [
        ("appli.apk", _URL, "io.exemple.appli", None)
    ]
    assert plan.sans_empreinte() == plan.fichiers


def test_plan_keeps_a_published_sha256():
    sha = "a" * 64
    plan = apk.plan_from_procedure(
        _procedure(telechargements=[{"nom": "appli.apk", "url": _URL, "paquet": "io.exemple.appli", "sha256": sha}])
    )

    assert plan.fichiers[0].sha256 == sha
    assert plan.sans_empreinte() == []


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": "usb_download"},
        {"efface_donnees": True},
        # Étape inconnue : jamais exécutée à moitié.
        {"etapes": [{"ordre": 1, "action": "flasher", "automatisable": "oui", "detail": "…"},
                    {"ordre": 2, "action": "installer_apk", "automatisable": "oui", "detail": "…"}]},
        # Aucune étape d'installation.
        {"etapes": [{"ordre": 1, "action": "telecharger", "automatisable": "oui", "detail": "…"}]},
        {"telechargements": []},
        # Pas de paquet : impossible de vérifier l'installation.
        {"telechargements": [{"nom": "appli.apk", "url": _URL}]},
        {"telechargements": [{"nom": "appli.apk", "url": _URL, "paquet": "appli; rm -rf /"}]},
        # Ailleurs que sur GitHub.
        {"telechargements": [{"nom": "appli.apk", "url": "https://exemple.org/appli.apk", "paquet": "io.exemple.appli"}]},
        {"telechargements": [{"nom": "appli.zip", "url": _URL, "paquet": "io.exemple.appli"}]},
    ],
)
def test_plan_from_procedure_refuses_what_it_cannot_run_entirely(changes):
    assert apk.plan_from_procedure(_procedure(**changes)) is None


def test_plan_from_fiche_takes_the_first_installable_procedure():
    fiche = SimpleNamespace(procedures=[_procedure(mode="usb_download"), _procedure()])

    assert apk.plan_from_fiche(fiche).procedure_id == "appli-installation"
    assert apk.plan_from_fiche(SimpleNamespace(procedures=[])) is None


# --- Téléchargement ----------------------------------------------------------


def test_download_apk_writes_the_file_and_returns_its_sha256(tmp_path):
    seen = []
    destination = tmp_path / "a.apk"

    sha = apk.download_apk(_fichier(), destination, lambda done, total: seen.append((done, total)), opener=_opener(_APK))

    assert destination.read_bytes() == _APK
    assert sha == hashlib.sha256(_APK).hexdigest()
    assert seen[-1] == (len(_APK), len(_APK))


def test_download_apk_accepts_the_published_sha256(tmp_path):
    sha = hashlib.sha256(_APK).hexdigest()

    assert apk.download_apk(_fichier(sha), tmp_path / "a.apk", opener=_opener(_APK)) == sha


@pytest.mark.parametrize(
    "fichier, data, length, code",
    [
        (_fichier("b" * 64), _APK, None, "empreinte"),
        (_fichier(), b"<html>404</html>", None, "pas_un_apk"),
        (_fichier(), b"", None, "pas_un_apk"),
        (_fichier(), _APK, len(_APK) + 10, "reseau"),
        (_fichier(), _APK, apk.MAX_APK_BYTES + 1, "trop_gros"),
    ],
)
def test_download_apk_refuses_and_leaves_no_file(tmp_path, fichier, data, length, code):
    destination = tmp_path / "a.apk"

    with pytest.raises(apk.ApkError) as caught:
        apk.download_apk(fichier, destination, opener=_opener(data, length))

    assert caught.value.code == code
    assert not destination.exists()


def test_download_apk_refuses_another_host_without_any_request(tmp_path):
    def opener(requete, timeout=None):
        raise AssertionError("aucune requête attendue")

    fichier = apk.ApkFile(nom="a.apk", url="https://exemple.org/a.apk", paquet="io.exemple.appli")
    with pytest.raises(apk.ApkError) as caught:
        apk.download_apk(fichier, tmp_path / "a.apk", opener=opener)

    assert caught.value.code == "url"


def test_download_apk_network_error_and_cancel(tmp_path):
    def broken(requete, timeout=None):
        raise OSError("pas de réseau")

    with pytest.raises(apk.ApkError) as caught:
        apk.download_apk(_fichier(), tmp_path / "a.apk", opener=broken)
    assert caught.value.code == "reseau"

    with pytest.raises(apk.ApkError) as caught:
        apk.download_apk(_fichier(), tmp_path / "b.apk", annule=lambda: True, opener=_opener(_APK))
    assert caught.value.code == "annule"
    assert not (tmp_path / "b.apk").exists()


# --- adb ---------------------------------------------------------------------


def test_install_apk_runs_adb_install_r_on_the_given_console(tmp_path):
    calls = []

    def runner(args, timeout):
        calls.append(args)
        return _result("Performing Streamed Install\nSuccess\n")

    apk.install_apk("adb", "SER1", tmp_path / "a.apk", runner=runner)

    assert calls == [["adb", "-s", "SER1", "install", "-r", str(tmp_path / "a.apk")]]


def test_install_apk_reports_the_refusal_of_the_console(tmp_path):
    def runner(args, timeout):
        return _result("Performing Streamed Install\n", 1, "adb: failed to install a.apk: Failure [INSTALL_FAILED_OLDER_SDK]\n")

    with pytest.raises(apk.ApkError) as caught:
        apk.install_apk("adb", "SER1", tmp_path / "a.apk", runner=runner)

    assert caught.value.code == "refuse"
    assert "INSTALL_FAILED_OLDER_SDK" in caught.value.detail


def test_install_apk_timeout_is_an_adb_error(tmp_path):
    def runner(args, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    with pytest.raises(apk.ApkError) as caught:
        apk.install_apk("adb", "SER1", tmp_path / "a.apk", runner=runner)

    assert caught.value.code == "adb"


def test_is_package_installed_reads_pm_path():
    def present(args, timeout):
        assert args == ["adb", "-s", "SER1", "shell", "pm", "path", "io.exemple.appli"]
        return _result("package:/data/app/io.exemple.appli/base.apk\n")

    assert apk.is_package_installed("adb", "SER1", "io.exemple.appli", runner=present)
    assert not apk.is_package_installed("adb", "SER1", "io.exemple.appli", runner=lambda a, t: _result("", 1))


def test_is_package_installed_never_sends_an_invalid_name_to_the_console():
    def runner(args, timeout):
        raise AssertionError("aucune commande attendue")

    assert not apk.is_package_installed("adb", "SER1", "appli; reboot", runner=runner)


# --- Plan complet ------------------------------------------------------------


def _console(install_stdout="Success\n", pm_stdout="package:/data/app/base.apk\n"):
    calls = []

    def runner(args, timeout):
        calls.append(args[3:])
        return _result(install_stdout if args[3] == "install" else pm_stdout)

    return runner, calls


def test_run_plan_downloads_installs_checks_and_cleans_up(tmp_path):
    runner, calls = _console()
    steps = []

    result = apk.run_plan(
        "adb", "SER1", apk.plan_from_procedure(_procedure()), tmp_path,
        sur_etape=lambda etape, nom: steps.append((etape, nom)), opener=_opener(_APK), runner=runner,
    )

    assert result.ok
    assert [(i.nom, i.paquet, i.sha256) for i in result.installes] == [
        ("appli.apk", "io.exemple.appli", hashlib.sha256(_APK).hexdigest())
    ]
    assert steps == [("telechargement", "appli.apk"), ("installation", "appli.apk"), ("verification", "appli.apk")]
    assert [c[0] for c in calls] == ["install", "shell"]
    assert list(tmp_path.iterdir()) == []


def test_run_plan_never_calls_adb_when_the_download_fails(tmp_path):
    runner, calls = _console()

    result = apk.run_plan(
        "adb", "SER1", apk.plan_from_procedure(_procedure()), tmp_path, opener=_opener(b"<html>"), runner=runner
    )

    assert (result.ok, result.echec_code, result.echec_nom) == (False, "pas_un_apk", "appli.apk")
    assert calls == []
    assert result.installes == []


def test_run_plan_reports_an_app_missing_after_install(tmp_path):
    runner, _ = _console(pm_stdout="")

    result = apk.run_plan(
        "adb", "SER1", apk.plan_from_procedure(_procedure()), tmp_path, opener=_opener(_APK), runner=runner
    )

    assert result.echec_code == "absent"
    assert list(tmp_path.iterdir()) == []
