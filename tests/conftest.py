"""Fixtures partagées.

`qapp` fournit une QApplication unique pour toute la session (Qt n'en
autorise qu'une par processus), en mode "offscreen" pour ne pas dépendre
d'un vrai écran (CI, machines sans affichage).

**Garde-fou global contre les sous-processus réels** — incident corrigé :
un test utilisant `/dev/disk4`/`/dev/disk3` comme chemin factice coïncidait
avec un vrai disque externe branché sur la machine de dev ; une version
temporairement non mockée a exécuté un vrai `diskutil mount` dessus (voir
CLAUDE.md, §8). Deux mesures structurelles : les chemins de test utilisent
désormais des identifiants impossibles à confondre avec du matériel réel
(`/dev/fake-disk-test-*`), et — la garde ci-dessous — `subprocess.run`/
`subprocess.Popen` sont patchés par défaut sur *tous* les tests, pour que
l'absence de mock lève une erreur explicite au lieu d'exécuter une commande
réelle. Les rares tests qui doivent vraiment lancer un sous-processus (voir
`tests/test_gui_elevate.py`) le déclarent avec `@pytest.mark.real_subprocess`."""

from __future__ import annotations

import os
import platform
import subprocess

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# Diagnostic CI Windows (run réel, 202 échecs) : `platform.system()` invoque
# en interne `subprocess.run('ver')` sous Windows -- ni macOS ni Linux ne le
# font. Un premier correctif a tenté de reconnaître cet appel interne par sa
# pile d'appels (module appelant immédiat == `platform`), mais l'implémentation
# réelle passe par une couche intermédiaire (`platform.uname()`/`_syscmd_ver()`
# selon la version de Python) avant d'atteindre `subprocess` -- parfois via
# une fonction non patchée ici (`subprocess.check_output`), rendant la pile
# d'appels peu fiable à inspecter. `platform.system()`/`uname()` mettent déjà
# leur résultat en cache en interne (`platform._uname_cache`) : l'appeler une
# fois ici, avant que la garde ci-dessous ne patche `subprocess`, force ce
# cache à se remplir pour toute la session -- plus aucun appel interne à
# `subprocess` ensuite, sur aucun OS, y compris pour du code qui ne mocke pas
# `platform.system` lui-même.
platform.system()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


class UnmockedSubprocessError(RuntimeError):
    """Levée quand un test appelle `subprocess.run`/`subprocess.Popen` sans
    le mocker et sans la marque `@pytest.mark.real_subprocess`. Le message
    inclut la commande pour identifier immédiatement le test fautif et ce
    qu'il tentait d'exécuter."""


def _make_guard(function_name: str):
    def _raise_instead_of_running(*args, **kwargs):
        attempted = args[0] if args else kwargs.get("args")
        raise UnmockedSubprocessError(
            f"subprocess.{function_name}({attempted!r}) appelé sans mock dans un "
            "test -- aucune commande système réelle ne doit s'exécuter pendant "
            "les tests (voir tests/conftest.py). Mocke "
            f"`subprocess.{function_name}` (ou la fonction qui l'appelle), ou si "
            "ce test doit vraiment lancer un sous-processus, marque-le avec "
            "`@pytest.mark.real_subprocess`."
        )

    return _raise_instead_of_running


@pytest.fixture(autouse=True)
def _forbid_real_subprocess(request, monkeypatch):
    """Patche `subprocess.run`/`subprocess.Popen` au niveau du module
    partagé : comme tout le code source fait `import subprocess` puis
    `subprocess.run(...)`/`subprocess.Popen(...)` (jamais `from subprocess
    import run`), ces deux attributs sont la même référence partout, et un
    seul patch ici les neutralise pour l'ensemble du code appelé par un
    test — quel que soit le module qui les invoque.

    Un test décoré `@patch(...)` sur `subprocess.run`/`Popen` (ou leur
    équivalent qualifié, ex. `r36s_studio.devices.macos.subprocess.run` —
    le même objet module, donc le même attribut) reste inchangé : son
    propre patch s'applique par-dessus celui-ci pour la durée du test, puis
    restaure cette garde en se refermant."""
    if request.node.get_closest_marker("real_subprocess"):
        yield
        return

    monkeypatch.setattr(subprocess, "run", _make_guard("run"))
    monkeypatch.setattr(subprocess, "Popen", _make_guard("Popen"))
    yield


@pytest.fixture(autouse=True)
def _default_full_disk_access_granted(request, monkeypatch):
    """`gui.elevate.has_full_disk_access` lit un vrai dossier protégé par
    TCC (§3) -- sur une machine de dev réellement macOS, son résultat
    dépendrait de l'autorisation réelle accordée (ou non) au terminal qui
    lance la suite, rendant les tests non déterministes selon la machine.
    Par défaut, tous les tests supposent l'autorisation déjà accordée --
    comportement historique, avant l'écran de bienvenue macOS
    (`gui/screens.py::FullDiskAccessScreen`) -- les tests dédiés à cet
    écran (`tests/test_gui_main_window.py`) repatchent explicitement une
    valeur différente. Les tests de `has_full_disk_access` elle-même
    (`tests/test_gui_elevate.py`) se marquent `@pytest.mark.real_fda_probe`
    pour laisser passer leur propre implémentation -- même principe que
    `real_subprocess` ci-dessus."""
    if request.node.get_closest_marker("real_fda_probe"):
        yield
        return

    from r36s_studio.gui import elevate

    monkeypatch.setattr(elevate, "has_full_disk_access", lambda: True)
    yield


@pytest.fixture(autouse=True)
def _consoles_diverses_log_isolated(request, tmp_path, monkeypatch):
    """Bug corrigé, confirmé sur du vrai matériel : chaque lancement local
    de la suite écrivait pour de vrai dans le journal applicatif réel
    (`%APPDATA%\\r36s-studio\\logs\\consoles_diverses.log` sous Windows,
    `gui/logs.py::consoles_diverses_log_path`) -- plusieurs tests
    construisent volontairement une fiche malformée pour vérifier que
    `consoles_diverses/models.py::fiche_depuis_json` la rejette
    (`test_fiche_depuis_json_raises_when_top_level_field_missing` et
    consorts, `tests/test_consoles_diverses_client.py::test_rechercher_
    console_console_field_missing_required_field_is_reponse_invalide`),
    sans jamais mocker ce chemin -- seuls les deux tests spécifiquement
    dédiés à la journalisation elle-même le faisaient. Un signalement
    utilisateur (« bug confirmé par les logs ») s'est avéré être
    exactement ces cinq lignes de test, toujours dans le même ordre,
    jamais un vrai échec serveur/réseau -- la vraie recherche fonctionnait
    normalement (confirmé indépendamment via `Invoke-RestMethod`).

    Redirige `consoles_diverses/models.py::gui_logs.consoles_diverses_
    log_path` vers un fichier temporaire pour tous les tests, plutôt que
    de patcher chaque site d'appel un par un -- un futur test qui
    oublierait de le faire ne pourra plus jamais polluer le vrai journal
    de la machine de développement. Les deux tests qui vérifient le
    *contenu* du journal (`tests/test_consoles_diverses_models.py`) le
    repatchent explicitement dans leur propre `with` -- ce repatch
    l'emporte normalement pour la durée de leur bloc, puis restaure cette
    valeur par défaut en se refermant, comme pour `_forbid_real_
    subprocess` ci-dessus. `tests/test_gui_logs.py` teste `consoles_
    diverses_log_path` elle-même (sa résolution de chemin réelle) --
    marquée `@pytest.mark.real_consoles_diverses_log_path` pour laisser
    passer son implémentation non redirigée, même principe que
    `real_fda_probe`/`real_subprocess` ci-dessus."""
    if request.node.get_closest_marker("real_consoles_diverses_log_path"):
        yield
        return

    from r36s_studio.consoles_diverses import models as consoles_diverses_models

    monkeypatch.setattr(
        consoles_diverses_models.gui_logs,
        "consoles_diverses_log_path",
        lambda: tmp_path / "consoles_diverses.log",
    )
    yield


@pytest.fixture(autouse=True)
def _reset_privileged_mount_hook():
    """`partitions/locate.py::_privileged_mount_hook` est un point
    d'extension au niveau module que `MainWindow.__init__` installe sur
    macOS (§4.4, cartes GPT/EFI) -- sur une machine de dev réellement
    macOS, chaque `MainWindow()` construit dans un test y installe une
    méthode liée à cette instance, qui fuit sinon vers les tests suivants
    (y compris dans d'autres fichiers) bien après que l'instance elle-même
    ait cessé d'être utile."""
    from r36s_studio.partitions import locate

    locate.set_privileged_mount_hook(None)
    yield
    locate.set_privileged_mount_hook(None)
