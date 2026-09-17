"""Tests de gui/logs.py — emplacement du journal d'élévation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from r36s_studio.gui import logs


@patch("r36s_studio.gui.logs.platform.system", return_value="Darwin")
def test_log_dir_under_home_config_on_macos(mock_system, tmp_path):
    with patch("r36s_studio.gui.logs.Path.home", return_value=tmp_path):
        result = logs.log_dir()

    assert result == tmp_path / ".config" / "r36s-studio" / "logs"
    assert result.is_dir()  # créé s'il n'existait pas


@patch("r36s_studio.gui.logs.platform.system", return_value="Windows")
def test_log_dir_under_appdata_on_windows(mock_system, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    result = logs.log_dir()

    assert result == tmp_path / "r36s-studio" / "logs"
    assert result.is_dir()


@patch("r36s_studio.gui.logs.platform.system", return_value="Darwin")
def test_elevation_log_path_is_inside_log_dir(mock_system, tmp_path):
    with patch("r36s_studio.gui.logs.Path.home", return_value=tmp_path):
        path = logs.elevation_log_path()

    assert path == tmp_path / ".config" / "r36s-studio" / "logs" / "elevation.log"
    assert isinstance(path, Path)


@patch("r36s_studio.gui.logs.platform.system", return_value="Darwin")
def test_consoles_diverses_log_path_is_inside_log_dir(mock_system, tmp_path):
    with patch("r36s_studio.gui.logs.Path.home", return_value=tmp_path):
        path = logs.consoles_diverses_log_path()

    assert path == tmp_path / ".config" / "r36s-studio" / "logs" / "consoles_diverses.log"
    assert isinstance(path, Path)
