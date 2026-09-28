"""Tests de `consoles_diverses/settings_store.py` (adresse du serveur) et
`consoles_diverses/settings_dialog.py`. La clé de licence elle-même vit
dans `AppConfig` (`tests/test_config.py`)."""

from __future__ import annotations

import pytest

from r36s_studio.consoles_diverses import settings_store
from r36s_studio.consoles_diverses.settings_dialog import ConsolesDiversesSettingsDialog


# --- Validation de l'adresse du serveur (durcissement demandé, point 3) ---


@pytest.mark.parametrize(
    "url",
    [
        "https://exemple.invalid",
        "https://exemple.invalid:8787",
        "http://localhost",
        "http://localhost:8787",
        "http://127.0.0.1",
        "http://127.0.0.1:8787",
    ],
)
def test_valider_adresse_serveur_accepts_https_and_local_http(url):
    assert settings_store.valider_adresse_serveur(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "http://exemple.invalid",
        "http://192.168.1.10:8787",
        "http://mon-serveur-distant.example",
    ],
)
def test_valider_adresse_serveur_rejects_remote_http(url):
    message = settings_store.valider_adresse_serveur(url)

    assert message is not None
    assert "localhost" in message or "127.0.0.1" in message


def test_valider_adresse_serveur_rejects_empty():
    message = settings_store.valider_adresse_serveur("")

    assert message is not None


def test_valider_adresse_serveur_rejects_other_schemes():
    message = settings_store.valider_adresse_serveur("ftp://exemple.invalid")

    assert message is not None


# --- Adresse du serveur : en dur, surchargeable par variable d'environnement


def test_adresse_serveur_is_production_by_default(monkeypatch):
    monkeypatch.delenv("R36S_STUDIO_CLOUD_URL", raising=False)

    assert settings_store.adresse_serveur() == "https://r36s-studio-cloud.r36studio.workers.dev"


def test_adresse_serveur_uses_the_environment_override_for_a_local_worker(monkeypatch):
    monkeypatch.setenv("R36S_STUDIO_CLOUD_URL", "  http://localhost:8787  ")

    assert settings_store.adresse_serveur() == "http://localhost:8787"


def test_adresse_serveur_ignores_a_blank_override(monkeypatch):
    monkeypatch.setenv("R36S_STUDIO_CLOUD_URL", "   ")

    assert settings_store.adresse_serveur() == settings_store.PRODUCTION_SERVER_URL


@pytest.mark.parametrize("url", ["http://serveur-distant.example", "ftp://exemple.invalid", "pas une adresse"])
def test_adresse_serveur_refuses_an_unsafe_override_loudly(monkeypatch, capsys, url):
    """Jamais la clé de licence en clair vers un serveur distant, et jamais
    un refus silencieux : signalé sur la sortie d'erreur."""
    monkeypatch.setenv("R36S_STUDIO_CLOUD_URL", url)

    assert settings_store.adresse_serveur() == settings_store.PRODUCTION_SERVER_URL
    assert "R36S_STUDIO_CLOUD_URL" in capsys.readouterr().err


# --- ConsolesDiversesSettingsDialog -----------------------------------------


def test_settings_dialog_has_no_server_address_field(qapp):
    """Retiré : un client ne saurait pas quoi y mettre, et une adresse mal
    tapée rendait la section inutilisable sans message clair. Seule la clé
    de licence reste à saisir."""
    from PySide6.QtWidgets import QLineEdit

    dialog = ConsolesDiversesSettingsDialog()

    assert not hasattr(dialog, "_server_url_edit")
    assert dialog.findChildren(QLineEdit) == [dialog._licence_edit]


def test_settings_dialog_prefills_the_current_licence(qapp):
    dialog = ConsolesDiversesSettingsDialog()
    dialog.set_values("cle-actuelle")

    assert dialog._licence_edit.text() == "cle-actuelle"


def test_settings_dialog_save_emits_only_the_licence_key(qapp):
    dialog = ConsolesDiversesSettingsDialog()
    dialog.set_values("")
    dialog._licence_edit.setText("ma-cle")
    received = []
    dialog.settings_saved.connect(received.append)

    dialog._save_button.click()

    assert received == ["ma-cle"]
