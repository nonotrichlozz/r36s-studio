"""Tests de config.py — configuration utilisateur persistée (§6),
notamment le mode d'interface (assisté/expert, §5 mode assisté)."""

from __future__ import annotations

import json
import sys
from dataclasses import fields
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


def test_load_config_defaults_to_rocknix_firmware_when_no_file_exists(tmp_path):
    with patch("r36s_studio.config.config_path", return_value=tmp_path / "config.json"):
        loaded = config.load_config()

    assert loaded.firmware == "rocknix"


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


def test_save_then_load_roundtrips_amberelec_firmware(tmp_path):
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(firmware="amberelec"))
        loaded = config.load_config()

    assert loaded.firmware == "amberelec"


def test_load_config_falls_back_to_default_on_unknown_firmware_value(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"firmware": "n\'importe quoi"}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.firmware == "rocknix"


def test_load_config_defaults_to_exfat_reset_card_filesystem_when_no_file_exists(tmp_path):
    with patch("r36s_studio.config.config_path", return_value=tmp_path / "config.json"):
        loaded = config.load_config()

    assert loaded.reset_card_filesystem == "exfat"


def test_save_then_load_roundtrips_fat32_reset_card_filesystem(tmp_path):
    """Cas réel : une console (SF3000HD) qui ne lit que le FAT32, rendue
    inutilisable par le formatage exFAT par défaut de « Remettre la carte
    à zéro » (§4.3 bis)."""
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(reset_card_filesystem="fat32"))
        loaded = config.load_config()

    assert loaded.reset_card_filesystem == "fat32"


def test_load_config_falls_back_to_default_on_unknown_reset_card_filesystem_value(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"reset_card_filesystem": "ntfs"}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.reset_card_filesystem == "exfat"


def test_server_url_is_no_longer_a_config_field():
    """L'adresse du serveur « Consoles diverses » est en dur
    (`settings_store.adresse_serveur`), jamais saisie ni mémorisée."""
    assert "consoles_diverses_server_url" not in {f.name for f in fields(config.AppConfig)}


def test_legacy_localhost_server_url_is_ignored_and_dropped_on_next_save(tmp_path):
    """Un `config.json` d'une version précédente porte presque toujours
    l'ancien défaut `http://localhost:8787` -- il ne doit plus jamais
    rediriger la recherche, et disparaît au prochain enregistrement."""
    path = tmp_path / "config.json"
    path.write_text('{"ui_mode": "expert", "consoles_diverses_server_url": "http://localhost:8787"}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()
        config.save_config(loaded)

    assert loaded.ui_mode == "expert"
    assert "consoles_diverses_server_url" not in path.read_text(encoding="utf-8")


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


# --- Tuile personnelle « Web » (jamais distribuée à un client) -------------
# Lue uniquement depuis R36S_STUDIO_WEB_URL, jamais un champ d'AppConfig
# (donc jamais dans config.json, jamais dans le repli save/load ci-dessus).


def test_personal_web_url_absent_by_default(monkeypatch):
    monkeypatch.delenv("R36S_STUDIO_WEB_URL", raising=False)

    assert config.personal_web_url() is None


def test_personal_web_url_returns_https_value(monkeypatch):
    monkeypatch.setenv("R36S_STUDIO_WEB_URL", "https://nonotrichlozz.github.io/mon-dashboard/")

    assert config.personal_web_url() == "https://nonotrichlozz.github.io/mon-dashboard/"


def test_personal_web_url_strips_whitespace(monkeypatch):
    monkeypatch.setenv("R36S_STUDIO_WEB_URL", "  https://exemple.invalid/  ")

    assert config.personal_web_url() == "https://exemple.invalid/"


def test_personal_web_url_rejects_non_https_scheme(monkeypatch):
    monkeypatch.setenv("R36S_STUDIO_WEB_URL", "http://exemple.invalid/")

    assert config.personal_web_url() is None


def test_personal_web_url_rejects_blank_value(monkeypatch):
    monkeypatch.setenv("R36S_STUDIO_WEB_URL", "   ")

    assert config.personal_web_url() is None


def test_personal_web_url_absent_by_default_even_when_frozen(monkeypatch):
    """Signalement utilisateur : doit rester absente dans un binaire
    PyInstaller comme en développement -- `os.environ.get` ne se comporte
    pas différemment une fois figé (`sys.frozen`), rien de spécifique à
    ce cas ne doit jamais faire apparaître une valeur par défaut."""
    monkeypatch.delenv("R36S_STUDIO_WEB_URL", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert config.personal_web_url() is None


def test_personal_web_url_never_persisted_in_app_config_fields():
    """Garde-fou de conception : cette URL ne doit jamais devenir un champ
    d'`AppConfig` (donc jamais écrite dans config.json, §9 -- une variable
    d'environnement ne quitte jamais la machine qui la définit)."""
    field_names = {f.name for f in fields(config.AppConfig)}
    assert not any("web" in name for name in field_names)


# --- Destination de l'outil « Doublons de jeux » (signalé : « permettre
# de choisir l'emplacement du dossier de destination ») -------------------


def test_load_config_defaults_doublons_destination_fields_when_no_file_exists(tmp_path):
    with patch("r36s_studio.config.config_path", return_value=tmp_path / "config.json"):
        loaded = config.load_config()

    assert loaded.doublons_last_destination is None
    assert loaded.doublons_recent_destinations == []


def test_save_then_load_roundtrips_doublons_last_destination(tmp_path):
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(doublons_last_destination="D:/Backup"))
        loaded = config.load_config()

    assert loaded.doublons_last_destination == "D:/Backup"


def test_load_config_falls_back_to_none_when_last_destination_is_blank(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"doublons_last_destination": "   "}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.doublons_last_destination is None


def test_load_config_falls_back_to_empty_list_when_recent_destinations_malformed(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"doublons_recent_destinations": "not a list"}', encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert loaded.doublons_recent_destinations == []


def test_load_config_truncates_an_overly_long_recent_destinations_list(tmp_path):
    path = tmp_path / "config.json"
    long_list = [f"D:/Backup{i}" for i in range(50)]
    path.write_text(json.dumps({"doublons_recent_destinations": long_list}), encoding="utf-8")

    with patch("r36s_studio.config.config_path", return_value=path):
        loaded = config.load_config()

    assert len(loaded.doublons_recent_destinations) <= 10


def test_record_doublons_destination_sets_last_destination():
    app_config = config.AppConfig()

    config.record_doublons_destination(app_config, "D:/Backup")

    assert app_config.doublons_last_destination == "D:/Backup"
    assert app_config.doublons_recent_destinations == ["D:/Backup"]


def test_record_doublons_destination_moves_existing_entry_to_front():
    app_config = config.AppConfig(doublons_recent_destinations=["A", "B", "C"])

    config.record_doublons_destination(app_config, "B")

    assert app_config.doublons_recent_destinations == ["B", "A", "C"]


def test_record_doublons_destination_never_duplicates_an_entry():
    app_config = config.AppConfig()

    config.record_doublons_destination(app_config, "D:/Backup")
    config.record_doublons_destination(app_config, "D:/Backup")

    assert app_config.doublons_recent_destinations == ["D:/Backup"]


def test_record_doublons_destination_caps_the_recent_list():
    app_config = config.AppConfig(doublons_recent_destinations=[f"D{i}" for i in range(10)])

    config.record_doublons_destination(app_config, "new")

    assert len(app_config.doublons_recent_destinations) == 10
    assert app_config.doublons_recent_destinations[0] == "new"
    assert "D9" not in app_config.doublons_recent_destinations  # le plus ancien tombe


def test_consoles_diverses_licence_key_round_trips_through_config_json(tmp_path):
    """Clé de licence mémorisée dans `config.json` (plus de trousseau
    système), relue sans espace parasite ; une valeur non-texte retombe
    sur « aucune clé »."""
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        assert config.load_config().consoles_diverses_licence_key == ""
        config.save_config(config.AppConfig(consoles_diverses_licence_key="r36s-abc"))
        assert config.load_config().consoles_diverses_licence_key == "r36s-abc"

        path.write_text('{"consoles_diverses_licence_key": " r36s-abc\\n"}', encoding="utf-8")
        assert config.load_config().consoles_diverses_licence_key == "r36s-abc"

        path.write_text('{"consoles_diverses_licence_key": 42}', encoding="utf-8")
        assert config.load_config().consoles_diverses_licence_key == ""
