"""Tests de `consoles_diverses/settings_store.py` et
`consoles_diverses/settings_dialog.py`. `keyring` est monkeypatché --
jamais de vrai trousseau système lu ou écrit pendant les tests, quelle
que soit la machine qui lance la suite."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from r36s_studio.consoles_diverses import settings_store
from r36s_studio.consoles_diverses.settings_dialog import ConsolesDiversesSettingsDialog


@pytest.fixture(autouse=True)
def _reset_settings_store_state():
    """`trousseau_disponible()`/la mémoire-session sont des états de module
    -- chaque test doit repartir propre, sinon un test influence le
    suivant selon l'ordre d'exécution."""
    settings_store.reset_trousseau_disponible_cache()
    settings_store._licence_memoire_session = None
    yield
    settings_store.reset_trousseau_disponible_cache()
    settings_store._licence_memoire_session = None


# --- trousseau disponible ----------------------------------------------------


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_enregistrer_puis_lire_licence_via_trousseau_quand_disponible(mock_keyring):
    stockage = {}

    def _set_password(service, account, value):
        stockage[(service, account)] = value

    def _get_password(service, account):
        return stockage.get((service, account))

    mock_keyring.set_password.side_effect = _set_password
    mock_keyring.get_password.side_effect = _get_password

    settings_store.enregistrer_licence("ma-cle")

    assert settings_store.lire_licence() == "ma-cle"
    assert settings_store.trousseau_disponible() is True


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_enregistrer_licence_strips_stray_whitespace_via_trousseau(mock_keyring):
    """Bug corrigé : une clé valide (confirmée contre le serveur de
    production) était refusée par la GUI -- un espace/retour à la ligne
    parasite laissé par un copier-coller n'était jamais retiré avant
    l'enregistrement."""
    stockage = {}

    def _set_password(service, account, value):
        stockage[(service, account)] = value

    def _get_password(service, account):
        return stockage.get((service, account))

    mock_keyring.set_password.side_effect = _set_password
    mock_keyring.get_password.side_effect = _get_password

    settings_store.enregistrer_licence(" ma-cle \n")

    mock_keyring.set_password.assert_called_once_with(settings_store.SERVICE_NAME, "licence", "ma-cle")
    assert settings_store.lire_licence() == "ma-cle"


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_enregistrer_licence_strips_stray_whitespace_via_memory_fallback(mock_keyring):
    mock_keyring.get_password.side_effect = RuntimeError("aucun backend keyring")

    settings_store.enregistrer_licence(" ma-cle \n")

    assert settings_store.lire_licence() == "ma-cle"


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_lire_licence_never_returns_a_stale_trousseau_value_after_a_failed_rewrite(mock_keyring):
    """Bug corrigé, signalé : une clé valide restait refusée après
    plusieurs ressaisies (longueur identique à chaque tentative dans le
    journal). Cause : certains backends `keyring` (`WinVaultKeyring`,
    entre autres -- voir le commentaire d'`enregistrer_licence`) peuvent
    lever *après* avoir déjà commencé à modifier le trousseau, avant
    d'avoir écrit la nouvelle valeur -- l'ancienne valeur reste alors en
    place. L'ancien code retombait sur la mémoire-session en cas
    d'échec, mais `lire_licence()` préférait quand même une relecture
    trousseau non vide -- rendant systématiquement l'ancienne valeur,
    jamais celle qu'on venait de demander."""
    stockage = {(settings_store.SERVICE_NAME, "licence"): "ancienne-cle"}

    def _get_password(service, account):
        return stockage.get((service, account))

    mock_keyring.get_password.side_effect = _get_password
    mock_keyring.set_password.side_effect = RuntimeError("échec partiel côté backend")

    settings_store.enregistrer_licence("nouvelle-cle")

    assert settings_store.lire_licence() == "nouvelle-cle"


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_enregistrer_licence_logs_a_diagnostic_without_the_key_itself(mock_keyring, tmp_path):
    """Diagnostic demandé : hash de la clé demandée, hash de ce que le
    trousseau rend en relecture directe, et la source utilisée -- jamais
    la clé en clair."""
    stockage = {}

    def _set_password(service, account, value):
        stockage[(service, account)] = value

    def _get_password(service, account):
        return stockage.get((service, account))

    mock_keyring.set_password.side_effect = _set_password
    mock_keyring.get_password.side_effect = _get_password

    log_path = tmp_path / "consoles_diverses.log"
    with patch.object(settings_store.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        settings_store.enregistrer_licence("ma-cle-secrete")

    contenu = log_path.read_text(encoding="utf-8")
    assert "ma-cle-secrete" not in contenu
    assert "source=trousseau" in contenu
    hash_attendu = settings_store._hash_prefix("ma-cle-secrete")
    assert f"sha256_demandee={hash_attendu}" in contenu
    assert f"sha256_trousseau_relue={hash_attendu}" in contenu


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_enregistrer_licence_diagnostic_reports_memoire_source_and_stale_trousseau_hash(mock_keyring, tmp_path):
    """Même scénario que le bug corrigé ci-dessus, vu depuis le journal :
    la source retombe sur `memoire`, et le hash relu au trousseau reste
    celui de l'ancienne valeur -- exactement ce qui permet de confirmer le
    diagnostic depuis les logs, sans jamais y faire figurer une clé."""
    stockage = {(settings_store.SERVICE_NAME, "licence"): "ancienne-cle"}

    def _get_password(service, account):
        return stockage.get((service, account))

    mock_keyring.get_password.side_effect = _get_password
    mock_keyring.set_password.side_effect = RuntimeError("échec partiel côté backend")

    log_path = tmp_path / "consoles_diverses.log"
    with patch.object(settings_store.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        settings_store.enregistrer_licence("nouvelle-cle")

    contenu = log_path.read_text(encoding="utf-8")
    assert "nouvelle-cle" not in contenu
    assert "ancienne-cle" not in contenu
    assert "source=memoire" in contenu
    assert f"sha256_demandee={settings_store._hash_prefix('nouvelle-cle')}" in contenu
    assert f"sha256_trousseau_relue={settings_store._hash_prefix('ancienne-cle')}" in contenu


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_effacer_licence_supprime_du_trousseau(mock_keyring):
    mock_keyring.get_password.return_value = None

    settings_store.effacer_licence()

    mock_keyring.delete_password.assert_called_once_with(settings_store.SERVICE_NAME, "licence")


# --- Repli sans trousseau système (durcissement demandé, point 5) ----------


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_trousseau_disponible_false_when_keyring_raises(mock_keyring):
    mock_keyring.get_password.side_effect = RuntimeError("aucun backend keyring")

    assert settings_store.trousseau_disponible() is False


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_enregistrer_licence_falls_back_to_memory_when_no_keyring_backend(mock_keyring):
    mock_keyring.get_password.side_effect = RuntimeError("aucun backend keyring")

    settings_store.enregistrer_licence("ma-cle")

    # jamais écrit via keyring -- resté uniquement en mémoire-session
    mock_keyring.set_password.assert_not_called()
    assert settings_store.lire_licence() == "ma-cle"


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_memory_fallback_licence_is_never_persisted_to_disk(mock_keyring, tmp_path):
    """Le repli mémoire-session ne doit laisser aucune trace sur disque --
    c'est tout l'intérêt du durcissement demandé (point 5)."""
    mock_keyring.get_password.side_effect = RuntimeError("aucun backend keyring")

    settings_store.enregistrer_licence("cle-tres-secrete")

    # Aucune écriture disque n'est même tentée par ce module -- vérifié en
    # s'assurant qu'aucun appel keyring persistant n'a eu lieu.
    mock_keyring.set_password.assert_not_called()


@patch("r36s_studio.consoles_diverses.settings_store.keyring")
def test_trousseau_disponible_result_is_cached_for_the_session(mock_keyring):
    mock_keyring.get_password.return_value = None

    assert settings_store.trousseau_disponible() is True
    assert settings_store.trousseau_disponible() is True

    assert mock_keyring.get_password.call_count == 1


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


# --- ConsolesDiversesSettingsDialog -----------------------------------------


def test_settings_dialog_shows_keyring_warning_when_unavailable(qapp):
    with patch("r36s_studio.consoles_diverses.settings_dialog.settings_store.trousseau_disponible", return_value=False):
        dialog = ConsolesDiversesSettingsDialog()
        dialog.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
        dialog.set_values("http://localhost:8787", "")

    assert dialog._keyring_warning_label.isVisible() is True


def test_settings_dialog_hides_keyring_warning_when_available(qapp):
    with patch("r36s_studio.consoles_diverses.settings_dialog.settings_store.trousseau_disponible", return_value=True):
        dialog = ConsolesDiversesSettingsDialog()
        dialog.set_values("http://localhost:8787", "")

    assert dialog._keyring_warning_label.isVisible() is False


def test_settings_dialog_save_emits_signal_with_valid_url(qapp):
    dialog = ConsolesDiversesSettingsDialog()
    dialog.set_values("http://localhost:8787", "")
    dialog._server_url_edit.setText("https://exemple.invalid")
    dialog._licence_edit.setText("ma-cle")
    received = []
    dialog.settings_saved.connect(lambda url, cle: received.append((url, cle)))

    dialog._save_button.click()

    assert received == [("https://exemple.invalid", "ma-cle")]


def test_settings_dialog_save_with_invalid_url_shows_error_and_does_not_emit(qapp):
    dialog = ConsolesDiversesSettingsDialog()
    dialog.set_values("http://localhost:8787", "")
    dialog._server_url_edit.setText("http://serveur-distant.example")
    received = []
    dialog.settings_saved.connect(lambda url, cle: received.append((url, cle)))

    dialog._save_button.click()

    assert received == []
    assert dialog._error_label.text() != ""
