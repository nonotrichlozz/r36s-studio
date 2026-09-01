"""Tests du garde-fou global contre les sous-processus réels
(`tests/conftest.py::_forbid_real_subprocess`).

Diagnostic CI Windows (202 échecs) : `platform.system()` invoque en
interne `subprocess.run('ver')` sous Windows (`platform._syscmd_ver`), ce
que ne font ni macOS ni Linux — jamais observé avant que la suite tourne
pour de vrai sur un runner Windows. La garde interceptait cet appel
interne de la bibliothèque standard comme s'il venait du code applicatif.
Corrigé en laissant passer tout appel dont le module appelant immédiat est
`platform` lui-même, vers le vrai `subprocess.run`/`Popen` -- jamais vers
le code applicatif, qui reste bloqué comme avant."""

from __future__ import annotations

import subprocess

import pytest


def test_forbid_real_subprocess_allows_calls_whose_immediate_caller_is_platform():
    """Simule `platform.system()` sous Windows (`_syscmd_ver`) sans dépendre
    de l'implémentation interne réelle ni du système d'exploitation local :
    injecte, dans l'espace de noms du vrai module `platform`, une fonction
    qui invoque `subprocess.run` -- son `__globals__["__name__"]` vaut donc
    réellement `"platform"`, exactement le signal que la garde doit
    reconnaître."""
    import platform as platform_module

    exec(
        "def _r36s_studio_test_probe():\n"
        "    import subprocess\n"
        "    return subprocess.run(['r36s-studio-test-probe-inexistant'], capture_output=True)\n",
        vars(platform_module),
    )
    try:
        with pytest.raises(FileNotFoundError):
            platform_module._r36s_studio_test_probe()
    finally:
        del platform_module._r36s_studio_test_probe


def test_forbid_real_subprocess_still_blocks_application_code():
    """Non-régression : un appel direct depuis le code de test (donc
    « applicatif » du point de vue de la garde) reste bloqué."""
    with pytest.raises(Exception) as exc_info:
        subprocess.run(["r36s-studio-test-probe-inexistant"], capture_output=True)

    assert type(exc_info.value).__name__ == "UnmockedSubprocessError"
