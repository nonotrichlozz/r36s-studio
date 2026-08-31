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


def test_load_config_defaults_to_arkos_firmware_when_no_file_exists(tmp_path):
    with patch("r36s_studio.config.config_path", return_value=tmp_path / "config.json"):
        loaded = config.load_config()

    assert loaded.firmware == "arkos"


def test_save_then_load_roundtrips_firmware(tmp_path):
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(firmware="rocknix"))
        loaded = config.load_config()

    assert loaded.firmware == "rocknix"


def test_save_then_load_roundtrips_emuelec_firmware(tmp_path):
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(firmware="emuelec"))
        loaded = config.load_config()

    assert loaded.firmware == "emuelec"


def test_load_config_falls_back_to_default_on_unknown_firmware_value(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"firmware": "n\'importe quoi"}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.firmware == "arkos"


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


# --- archive_records : mémorisation des sauvegardes BOOT/EASYROMS par ------
# --- empreinte de carte (§5 mode assisté, évite de tout recopier à ---------
# --- chaque nouveau passage sur la même carte, EASYROMS en particulier) ----


def test_get_archive_record_returns_none_when_nothing_stored():
    cfg = config.AppConfig()

    assert config.get_archive_record(cfg, "abc123", "BOOT") is None


def test_get_archive_record_returns_none_when_fingerprint_is_none():
    cfg = config.AppConfig()
    config.set_archive_record(cfg, "abc123", "BOOT", "/tmp/BOOT_x")

    assert config.get_archive_record(cfg, None, "BOOT") is None


def test_set_then_get_archive_record_roundtrips_path_and_date():
    from datetime import datetime

    cfg = config.AppConfig()
    when = datetime(2026, 7, 6, 0, 21)

    config.set_archive_record(cfg, "abc123", "BOOT", "/tmp/BOOT_2026-07-06_00-21", created_at=when)
    record = config.get_archive_record(cfg, "abc123", "BOOT")

    assert record == {"path": "/tmp/BOOT_2026-07-06_00-21", "created_at": when.isoformat()}


def test_set_archive_record_defaults_created_at_to_now():
    cfg = config.AppConfig()

    config.set_archive_record(cfg, "abc123", "BOOT", "/tmp/BOOT_x")

    record = config.get_archive_record(cfg, "abc123", "BOOT")
    assert record is not None
    assert record["created_at"]  # une date ISO a bien été générée


def test_set_archive_record_keeps_boot_and_easyroms_independent():
    cfg = config.AppConfig()

    config.set_archive_record(cfg, "abc123", "BOOT", "/tmp/BOOT_x")
    config.set_archive_record(cfg, "abc123", "EASYROMS", "/tmp/EASYROMS_x")

    assert config.get_archive_record(cfg, "abc123", "BOOT")["path"] == "/tmp/BOOT_x"
    assert config.get_archive_record(cfg, "abc123", "EASYROMS")["path"] == "/tmp/EASYROMS_x"


def test_set_archive_record_overwrites_previous_entry_for_same_combination():
    cfg = config.AppConfig()
    config.set_archive_record(cfg, "abc123", "BOOT", "/tmp/BOOT_old")

    config.set_archive_record(cfg, "abc123", "BOOT", "/tmp/BOOT_new")

    assert config.get_archive_record(cfg, "abc123", "BOOT")["path"] == "/tmp/BOOT_new"


def test_set_archive_record_keeps_different_fingerprints_independent():
    cfg = config.AppConfig()

    config.set_archive_record(cfg, "card-a", "BOOT", "/tmp/BOOT_a")
    config.set_archive_record(cfg, "card-b", "BOOT", "/tmp/BOOT_b")

    assert config.get_archive_record(cfg, "card-a", "BOOT")["path"] == "/tmp/BOOT_a"
    assert config.get_archive_record(cfg, "card-b", "BOOT")["path"] == "/tmp/BOOT_b"


def test_save_then_load_roundtrips_archive_records(tmp_path):
    path = tmp_path / "config.json"
    cfg = config.AppConfig()
    config.set_archive_record(cfg, "abc123", "BOOT", "/tmp/BOOT_x")

    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(cfg)
        loaded = config.load_config()

    assert config.get_archive_record(loaded, "abc123", "BOOT")["path"] == "/tmp/BOOT_x"


def test_load_config_ignores_archive_records_of_the_wrong_shape(tmp_path):
    """Un fichier corrompu ou modifié à la main ne doit jamais faire
    planter le chargement -- toute entrée malformée est ignorée plutôt que
    de faire échouer la configuration entière."""
    path = tmp_path / "config.json"
    path.write_text(
        '{"archive_records": {'
        '"valid": {"BOOT": {"path": "/tmp/x", "created_at": "2026-01-01T00:00:00"}},'
        '"not_a_dict": "oops",'
        '"missing_fields": {"BOOT": {"path": "/tmp/y"}},'
        '"wrong_type": {"BOOT": "not-a-dict"}'
        '}}',
        encoding="utf-8",
    )

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert config.get_archive_record(loaded, "valid", "BOOT") == {
        "path": "/tmp/x",
        "created_at": "2026-01-01T00:00:00",
    }
    assert "not_a_dict" not in loaded.archive_records
    assert "missing_fields" not in loaded.archive_records
    assert "wrong_type" not in loaded.archive_records


def test_load_config_falls_back_to_empty_archive_records_when_not_a_dict(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"archive_records": "oops"}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.archive_records == {}
