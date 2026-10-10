"""Tests du garde-fou global contre les sous-processus réels
(`tests/conftest.py::_forbid_real_subprocess`).

Diagnostic CI Windows (run réel, 202 échecs). `platform.system()` invoque en
interne `subprocess.run('ver')` sous Windows -- ni macOS ni Linux ne le font.
Un premier correctif tentait de reconnaître cet appel interne par sa pile
d'appels (module appelant immédiat == `platform`), mais l'échec a persisté
sur le run CI suivant : l'implémentation réelle passe par une couche
intermédiaire (`platform.uname()`/`_syscmd_ver()` selon la version de
Python), parfois via une fonction non patchée ici (`subprocess.
check_output`), rendant la pile d'appels peu fiable à inspecter -- retiré.

Corrigé plus simplement (et plus sûrement) : `platform.system()`/`uname()`
mettent déjà leur résultat en cache en interne (`platform._uname_cache`).
`conftest.py` l'appelle une fois au chargement du module, avant que la garde
ne patche `subprocess` -- plus aucun appel interne à `subprocess` ensuite,
sur aucun OS, quel que soit le nombre de niveaux internes traversés."""

from __future__ import annotations

import os
import platform
import subprocess

import pytest

# Importées au chargement du module, avant les patchs de `conftest.py` :
# exactement la copie de l'incident du 2026-10-10.
from r36s_studio.config import config_path as _stale_config_path
from r36s_studio.gui.logs import log_dir as _stale_log_dir


def test_platform_system_result_is_cached_before_tests_run():
    """Vérifie le mécanisme du correctif lui-même : `platform._uname_cache`
    (l'attribut de cache interne de la bibliothèque standard) doit déjà être
    rempli avant qu'aucun test ne s'exécute -- c'est ce qui garantit qu'un
    test qui ne mocke pas `platform.system` n'entraînera plus jamais son
    implémentation interne à retenter un appel système. Couplé à un détail
    d'implémentation CPython plutôt qu'au comportement observable (celui-ci
    ne diffère que sous Windows, impossible à vérifier directement sur une
    machine de développement macOS), mais c'est le seul moyen direct de
    prouver que l'amorçage a bien eu lieu."""
    assert platform._uname_cache is not None


def test_platform_system_does_not_trigger_the_subprocess_guard():
    """Conséquence observable du correctif, vérifiable sur n'importe quel
    OS : appeler `platform.system()` pendant un test (donc avec
    `subprocess.run`/`Popen` déjà patchés par la garde autouse) ne doit
    jamais lever `UnmockedSubprocessError` -- que son implémentation
    interne touche ou non `subprocess` sur cet OS précis."""
    platform.system()


def test_forbid_real_subprocess_still_blocks_application_code():
    """Non-régression : un appel direct depuis le code de test (donc
    « applicatif » du point de vue de la garde) reste bloqué."""
    with pytest.raises(Exception) as exc_info:
        subprocess.run(["r36s-studio-test-probe-inexistant"], capture_output=True)

    assert type(exc_info.value).__name__ == "UnmockedSubprocessError"


# --- Vrai dossier de config (`conftest.py::_real_config_dir_guard`) ---------
#
# Incident du 2026-10-10 : un test importait `config_path` directement
# (`from r36s_studio.config import config_path`), ce qui contournait la
# redirection de `config.config_path`, et a écrasé le vrai config.json.


@pytest.mark.skipif(platform.system() != "Windows", reason="APPDATA n'est lu que sous Windows")
def test_stale_import_of_config_path_now_lands_in_tmp_path(tmp_path):
    assert _stale_config_path() == tmp_path / "appdata" / "r36s-studio" / "config.json"
    assert _stale_log_dir() == tmp_path / "appdata" / "r36s-studio" / "logs"


def test_writing_into_the_real_config_dir_fails(_real_config_dir_guard):
    from tests.conftest import _REAL_CONFIG_DIR, RealConfigDirTouched

    target = os.path.join(_REAL_CONFIG_DIR, "config.json")
    with pytest.raises(RealConfigDirTouched):
        open(target, "w")  # bloqué avant même l'ouverture
    with pytest.raises(RealConfigDirTouched):
        os.replace(os.path.join(_REAL_CONFIG_DIR, "absent"), target)
    # Relevé même si le code testé avait avalé l'exception : le test
    # échouerait au démontage. Vidé ici, l'échec est le comportement attendu.
    assert len(_real_config_dir_guard.violations) == 2
    _real_config_dir_guard.violations.clear()


def test_reading_the_real_config_dir_fails_too(_real_config_dir_guard):
    from tests.conftest import _REAL_CONFIG_DIR, RealConfigDirTouched

    with pytest.raises(RealConfigDirTouched):
        open(os.path.join(_REAL_CONFIG_DIR, "config.json"), "rb")
    _real_config_dir_guard.violations.clear()
