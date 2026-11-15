# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Installation d'applications sur une console Android branchée en USB
(étape 2, docs/android-adb.md) : une procédure de fiche en mode `adb`
devient un plan (`plan_from_procedure`), chaque APK est téléchargé, contrôlé
puis installé par `adb install -r` (`run_plan`).

- Jamais `adb root`, jamais de désinstallation, aucune donnée effacée :
  `adb install -r` garde les données d'une application déjà présente.
- Une procédure dont une étape est inconnue n'est pas proposée (jamais
  exécutée à moitié, même règle que `consoles_diverses/procedures/fiche.py`).
- Un APK sans SHA-256 publiée (lien « dernière version ») est accepté
  seulement depuis une release GitHub ; son empreinte est calculée et
  rendue à l'appelant, qui la journalise.

Aucun import de `consoles_diverses/` : la procédure est lue par ses
attributs. `runner` et `opener` injectables : aucun test ne lance adb ni
ne touche le réseau."""

from __future__ import annotations

import hashlib
import re
import subprocess
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

from r36s_studio import __version__

from .adb import Runner, _default_runner

INSTALL_TIMEOUT_SECONDS = 300.0
CHECK_TIMEOUT_SECONDS = 15.0
MAX_APK_BYTES = 500 * 1024 * 1024
USER_AGENT = f"R36S-Studio/{__version__}"
_BLOC = 1024 * 1024

# Actions qu'une procédure `adb` peut contenir. `installer_apk` est la seule
# que le logiciel exécute ; les autres sont des gestes de l'utilisateur,
# affichés par la fiche.
ACTIONS_CONNUES = frozenset(
    {
        "activer_debogage_usb",
        "brancher_console",
        "telecharger",
        "installer_apk",
        "ouvrir_application",
        "configuration_initiale",
    }
)

_PAQUET = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z0-9_]+)+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_AUTORISEE = "https://github.com/"


class ApkError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        # "url", "reseau", "trop_gros", "pas_un_apk", "empreinte", "annule",
        # "adb", "refuse", "absent"
        self.code = code
        self.detail = detail


@dataclass
class ApkFile:
    nom: str
    url: str
    paquet: str
    sha256: Optional[str] = None


@dataclass
class ApkInstallPlan:
    procedure_id: str
    titre: str
    source_url: str
    fichiers: List[ApkFile] = field(default_factory=list)

    def sans_empreinte(self) -> List[ApkFile]:
        return [f for f in self.fichiers if f.sha256 is None]


@dataclass
class InstalledApk:
    nom: str
    paquet: str
    sha256: str  # empreinte du fichier réellement installé


@dataclass
class InstallResult:
    installes: List[InstalledApk] = field(default_factory=list)
    echec_nom: str = ""
    echec_code: str = ""  # code d'`ApkError`, "" si tout est installé
    echec_detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.echec_code


def paquet_valide(paquet: Any) -> bool:
    return isinstance(paquet, str) and bool(_PAQUET.match(paquet))


def plan_from_procedure(procedure: Any) -> Optional[ApkInstallPlan]:
    """Plan d'installation d'une procédure de fiche, ou `None` si le
    logiciel ne peut pas la mener en entier sans risque."""
    if getattr(procedure, "mode", None) != "adb" or getattr(procedure, "efface_donnees", True):
        return None
    etapes = list(getattr(procedure, "etapes", []) or [])
    actions = [getattr(e, "action", "") for e in etapes]
    if "installer_apk" not in actions or any(a not in ACTIONS_CONNUES for a in actions):
        return None
    fichiers: List[ApkFile] = []
    for fichier in getattr(procedure, "telechargements", []) or []:
        nom, url = getattr(fichier, "nom", ""), getattr(fichier, "url", "")
        paquet, sha = getattr(fichier, "paquet", None), getattr(fichier, "sha256", None)
        if not nom.lower().endswith(".apk") or not url.startswith(_SOURCE_AUTORISEE) or not paquet_valide(paquet):
            return None  # un fichier que le logiciel ne sait pas installer : rien n'est proposé
        fichiers.append(ApkFile(nom=nom, url=url, paquet=paquet, sha256=sha if sha and _SHA256.match(sha) else None))
    if not fichiers:
        return None
    return ApkInstallPlan(
        procedure_id=getattr(procedure, "id", ""),
        titre=getattr(procedure, "titre", ""),
        source_url=getattr(procedure, "source_url", ""),
        fichiers=fichiers,
    )


def plan_from_fiche(fiche: Any) -> Optional[ApkInstallPlan]:
    """Première procédure installable de la fiche."""
    for procedure in getattr(fiche, "procedures", []) or []:
        plan = plan_from_procedure(procedure)
        if plan is not None:
            return plan
    return None


def download_apk(
    fichier: ApkFile,
    destination: Path,
    progression: Callable[[int, int], None] = lambda fait, total: None,
    annule: Callable[[], bool] = lambda: False,
    opener: Optional[Callable] = None,
) -> str:
    """Télécharge l'APK vers `destination` et renvoie sa SHA-256. Refuse un
    fichier qui n'est pas une archive APK, trop gros, ou dont l'empreinte
    diffère de celle de la fiche (fichier alors supprimé)."""
    if not fichier.url.startswith(_SOURCE_AUTORISEE):
        raise ApkError("url", fichier.url)
    requete = urllib.request.Request(fichier.url, headers={"User-Agent": USER_AGENT})
    ouvrir = opener or urllib.request.urlopen
    try:
        reponse = ouvrir(requete, timeout=60)
    except OSError as exc:
        raise ApkError("reseau", str(exc)) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    empreinte = hashlib.sha256()
    fait = 0
    try:
        with reponse:
            total = int(reponse.headers.get("Content-Length") or 0)
            if total > MAX_APK_BYTES:
                raise ApkError("trop_gros", str(total))
            with open(destination, "wb") as sortie:
                while True:
                    if annule():
                        raise ApkError("annule")
                    try:
                        bloc = reponse.read(_BLOC)
                    except OSError as exc:
                        raise ApkError("reseau", str(exc)) from exc
                    if not bloc:
                        break
                    if fait == 0 and not bloc.startswith(b"PK"):
                        raise ApkError("pas_un_apk", fichier.nom)
                    fait += len(bloc)
                    if fait > MAX_APK_BYTES:
                        raise ApkError("trop_gros", str(fait))
                    sortie.write(bloc)
                    empreinte.update(bloc)
                    progression(fait, total)
        if fait == 0:
            raise ApkError("pas_un_apk", fichier.nom)
        if total and fait != total:
            raise ApkError("reseau", f"fichier incomplet ({fait}/{total} octets)")
        obtenue = empreinte.hexdigest()
        if fichier.sha256 is not None and obtenue != fichier.sha256:
            raise ApkError("empreinte", fichier.nom)
    except ApkError:
        destination.unlink(missing_ok=True)
        raise
    return obtenue


def install_apk(
    adb_path: str,
    serial: str,
    apk_path: Path,
    *,
    runner: Runner = _default_runner,
    timeout: float = INSTALL_TIMEOUT_SECONDS,
) -> None:
    """`adb install -r` : installe, ou met à jour en gardant les données."""
    try:
        resultat = runner([adb_path, "-s", serial, "install", "-r", str(apk_path)], timeout)
    except subprocess.TimeoutExpired as exc:
        raise ApkError("adb", f"adb install : délai dépassé ({timeout}s).") from exc
    except OSError as exc:
        raise ApkError("adb", f"adb install : {exc}") from exc
    sortie = f"{resultat.stdout or ''}\n{resultat.stderr or ''}"
    if resultat.returncode != 0 or "Success" not in sortie:
        lignes = [ligne.strip() for ligne in sortie.splitlines() if ligne.strip()]
        raise ApkError("refuse", lignes[-1] if lignes else f"code {resultat.returncode}")


def is_package_installed(
    adb_path: str,
    serial: str,
    paquet: str,
    *,
    runner: Runner = _default_runner,
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> bool:
    if not paquet_valide(paquet):
        return False
    try:
        resultat = runner([adb_path, "-s", serial, "shell", "pm", "path", paquet], timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise ApkError("adb", f"adb shell pm path : {exc}") from exc
    return (resultat.stdout or "").strip().startswith("package:")


def run_plan(
    adb_path: str,
    serial: str,
    plan: ApkInstallPlan,
    dossier: Path,
    *,
    sur_etape: Callable[[str, str], None] = lambda etape, nom: None,
    progression: Callable[[int, int], None] = lambda fait, total: None,
    annule: Callable[[], bool] = lambda: False,
    opener: Optional[Callable] = None,
    runner: Runner = _default_runner,
) -> InstallResult:
    """Télécharge puis installe chaque APK du plan, dans l'ordre. S'arrête
    au premier échec ; ce qui est déjà installé le reste. `sur_etape(etape,
    nom)` : `telechargement`, `installation`, `verification`."""
    resultat = InstallResult()
    for index, fichier in enumerate(plan.fichiers):
        chemin = dossier / f"{index}.apk"
        try:
            sur_etape("telechargement", fichier.nom)
            empreinte = download_apk(fichier, chemin, progression, annule, opener)
            if annule():
                raise ApkError("annule")
            sur_etape("installation", fichier.nom)
            install_apk(adb_path, serial, chemin, runner=runner)
            sur_etape("verification", fichier.nom)
            if not is_package_installed(adb_path, serial, fichier.paquet, runner=runner):
                raise ApkError("absent", fichier.paquet)
        except ApkError as exc:
            resultat.echec_nom, resultat.echec_code, resultat.echec_detail = fichier.nom, exc.code, exc.detail
            return resultat
        finally:
            chemin.unlink(missing_ok=True)
        resultat.installes.append(InstalledApk(nom=fichier.nom, paquet=fichier.paquet, sha256=empreinte))
    return resultat


__all__ = [
    "ACTIONS_CONNUES",
    "ApkError",
    "ApkFile",
    "ApkInstallPlan",
    "InstalledApk",
    "InstallResult",
    "paquet_valide",
    "plan_from_procedure",
    "plan_from_fiche",
    "download_apk",
    "install_apk",
    "is_package_installed",
    "run_plan",
]
