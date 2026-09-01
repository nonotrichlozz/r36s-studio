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

import platform
import subprocess

import pytest


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
