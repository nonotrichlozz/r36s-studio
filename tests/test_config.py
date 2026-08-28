"""Tests de config.py — configuration utilisateur persistée (§6),
notamment le mode d'interface (assisté/expert, §5 mode assisté)."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio import config


@patch("r36s_studio.config.platform.system", return_value="Darwin")
def test_config_dir_under_home_config_on_macos(mock_system, tmp_path):
    with patch("r36s_studio.config.Path.home", return_value=tmp_path):
        result = config.config_dir()

    assert result == tmp_path / ".config" / "r36s-studio"
    assert result.is_dir()  # créé s'il n'existait pas


@patch("r36s_studio.config.platform.system", return_value="Windows")
def test_config_dir_under_appdata_on_windows(mock_system, tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))

    result = config.config_dir()

    assert result == tmp_path / "r36s-studio"
    assert result.is_dir()


def test_load_config_defaults_to_assisted_ui_mode_when_no_file_exists(tmp_path):
    with patch("r36s_studio.config.config_path", return_value=tmp_path / "config.json"):
        loaded = config.load_config()

    assert loaded.ui_mode == "assisted"


def test_save_then_load_roundtrips_ui_mode(tmp_path):
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(ui_mode="expert"))
        loaded = config.load_config()

    assert loaded.ui_mode == "expert"


def test_load_config_falls_back_to_default_on_corrupt_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{ceci n'est pas du JSON", encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.ui_mode == "assisted"


def test_load_config_falls_back_to_default_on_unknown_ui_mode_value(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"ui_mode": "n\'importe quoi"}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.ui_mode == "assisted"


def test_save_config_never_stores_a_secret_looking_key(tmp_path):
    """Garde-fou léger, cohérent avec la règle §9 (« aucun secret dans le
    dépôt ») : ce module ne doit jamais introduire de champ de ce genre."""
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(ui_mode="expert"))

    raw = path.read_text(encoding="utf-8")
    assert "token" not in raw.lower()
    assert "password" not in raw.lower()
    assert "secret" not in raw.lower()
