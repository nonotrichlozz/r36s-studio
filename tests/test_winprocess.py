"""Tests de `r36s_studio/winprocess.py` : le drapeau qui empêche les
sous-processus console (PowerShell) de faire apparaître leur propre fenêtre
visible une fois l'app empaquetée (§1, bug corrigé confirmé sur le binaire
réel -- voir le docstring de module).

`subprocess.CREATE_NO_WINDOW` n'existe réellement que sur un vrai Python
Windows (défini une fois pour toutes à l'import du module `subprocess`,
selon l'OS réel -- un `sys.platform` simulé en test ne le fait pas
apparaître comme par magie sur macOS/Linux). `create=True` sur ce second
patch permet de le poser temporairement même sur un OS où l'attribut
n'existe pas, pour que ce test reste déterministe sur les trois OS de la
CI (§8) plutôt que de dépendre de la machine qui l'exécute."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.winprocess import no_console_kwargs


@patch("r36s_studio.winprocess.subprocess.CREATE_NO_WINDOW", 0x08000000, create=True)
@patch("r36s_studio.winprocess.sys.platform", "win32")
def test_no_console_kwargs_on_windows():
    assert no_console_kwargs() == {"creationflags": 0x08000000}


@patch("r36s_studio.winprocess.sys.platform", "darwin")
def test_no_console_kwargs_empty_on_macos():
    assert no_console_kwargs() == {}


@patch("r36s_studio.winprocess.sys.platform", "linux")
def test_no_console_kwargs_empty_on_linux():
    assert no_console_kwargs() == {}
