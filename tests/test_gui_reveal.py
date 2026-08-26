"""Tests d'affichage dans le gestionnaire de fichiers (gui/reveal.py,
écran Résultat §5). `subprocess.run`/`platform.system` sont mockés —
aucune vraie fenêtre n'est ouverte."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio.gui.reveal import reveal, reveal_label


@patch("r36s_studio.gui.reveal.subprocess.run")
@patch("r36s_studio.gui.reveal.platform.system", return_value="Darwin")
def test_macos_uses_open_dash_r(mock_platform, mock_run):
    reveal("/tmp/R36S Studio/BOOT_x")

    mock_run.assert_called_once_with(["open", "-R", "/tmp/R36S Studio/BOOT_x"], check=True)


@patch("r36s_studio.gui.reveal.subprocess.run")
@patch("r36s_studio.gui.reveal.platform.system", return_value="Linux")
def test_linux_uses_xdg_open(mock_platform, mock_run):
    reveal("/tmp/R36S Studio/BOOT_x")

    mock_run.assert_called_once_with(["xdg-open", "/tmp/R36S Studio/BOOT_x"], check=True)


@patch("r36s_studio.gui.reveal.subprocess.run")
@patch("r36s_studio.gui.reveal.platform.system", return_value="Windows")
def test_windows_uses_explorer_select_without_check(mock_platform, mock_run):
    """`explorer` renvoie souvent un code non nul même en cas de succès --
    pas de `check=True` sous peine de lever une fausse erreur."""
    reveal(r"C:\Users\x\Documents\R36S Studio\BOOT_x")

    mock_run.assert_called_once_with(
        ["explorer", r"/select,C:\Users\x\Documents\R36S Studio\BOOT_x"]
    )
    assert "check" not in mock_run.call_args.kwargs


@patch("r36s_studio.gui.reveal.platform.system", return_value="Plan9")
def test_unsupported_os_raises_not_implemented(mock_platform):
    with pytest.raises(NotImplementedError):
        reveal("/tmp/x")


@patch("r36s_studio.gui.reveal.platform.system", return_value="Darwin")
def test_reveal_label_macos(mock_platform):
    assert reveal_label() == "Afficher dans le Finder"


@patch("r36s_studio.gui.reveal.platform.system", return_value="Windows")
def test_reveal_label_windows(mock_platform):
    assert reveal_label() == "Afficher dans l'Explorateur"


@patch("r36s_studio.gui.reveal.platform.system", return_value="Linux")
def test_reveal_label_linux(mock_platform):
    assert reveal_label() == "Afficher dans le gestionnaire de fichiers"
