"""Tests de navigation/orchestration de `MainWindow` pour l'outil « Console
Android » (android/, étape 1, docs/android-adb.md). `AndroidDetectRunner`/
`AndroidPlatformToolsSizeRunner`/`AndroidPlatformToolsDownloadRunner`/
`ConsoleSearchRunner` sont mockés -- même principe que les autres threads
de `MainWindow` (`RocknixListRunner`/`RocknixDownloadRunner`, `tests/
test_gui_main_window.py`) : jamais un vrai thread ni un accès réseau/adb
réel, les résultats sont simulés en appelant directement le gestionnaire
concerné plutôt qu'en attendant une livraison de signal asynchrone."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from r36s_studio.android.models import AndroidDeviceInfo, DetectionResult
from r36s_studio.config import AppConfig
from r36s_studio.consoles_diverses.client import ResultatRecherche
from r36s_studio.consoles_diverses.models import fiche_depuis_json
from r36s_studio.gui.main_window import MainWindow

_EXPERT_MODE_CONFIG = AppConfig(ui_mode="expert")


def _mock_runner_class():
    instances = []

    def _factory(*args, **kwargs):
        instance = MagicMock()
        instance.init_args = args
        instance.init_kwargs = kwargs
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


def _device_info():
    return AndroidDeviceInfo(
        serial="SER1",
        manufacturer="Retroid",
        model="RP Flip 2",
        product_name="flip2",
        android_version="13",
        abi="arm64-v8a",
    )


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_android_button_from_home_switches_screen_and_back_returns(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()

    with patch("r36s_studio.gui.main_window.android_adb.resolve_adb_path", return_value=None):
        window._home.android_requested.emit()

    assert window._root_stack.currentWidget() is window._android_screen

    window._android_screen.back_requested.emit()
    assert window._root_stack.currentWidget() is window._main_view


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_android_tile_from_assisted_landing_switches_screen(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()

    with patch("r36s_studio.gui.main_window.android_adb.resolve_adb_path", return_value=None):
        window._assisted_landing.android_requested.emit()

    assert window._root_stack.currentWidget() is window._android_screen


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_opening_android_screen_shows_consent_when_adb_missing(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    size_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.android_adb.resolve_adb_path", return_value=None):
        with patch("r36s_studio.gui.main_window.AndroidPlatformToolsSizeRunner", size_runner_class):
            window._open_android_screen()

    assert window._android_screen._consent_frame.isVisible()
    size_runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_opening_android_screen_starts_detection_when_adb_available(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    detect_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.android_adb.resolve_adb_path", return_value="/usr/bin/adb"):
        with patch("r36s_studio.gui.main_window.AndroidDetectRunner", detect_runner_class):
            window._open_android_screen()

    assert window._android_screen._status_frame.isVisible()
    detect_runner_class.assert_called_once_with("/usr/bin/adb", window)
    detect_runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_detection_finished_populates_screen_with_ready_device(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._root_stack.setCurrentWidget(window._android_screen)

    window._on_android_detect_finished(DetectionResult(state="ready", device=_device_info()))

    assert window._android_screen._device_frame.isVisible()
    assert window._android_screen._device_value_labels["manufacturer"].text() == "Retroid"


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_platform_tools_size_ready_updates_consent_screen(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()

    window._on_android_platform_tools_size_ready(1024 * 1024)

    assert "environ" in window._android_screen._consent_size_label.text()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_consent_download_requested_starts_download_runner(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._root_stack.setCurrentWidget(window._android_screen)
    download_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.AndroidPlatformToolsDownloadRunner", download_runner_class):
        window._android_screen.consent_download_requested.emit()

    assert not window._android_screen._consent_download_button.isVisible()
    download_runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_cancel_download_requested_calls_cancel_on_active_runner(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    download_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.AndroidPlatformToolsDownloadRunner", download_runner_class):
        window._android_screen.consent_download_requested.emit()
    window._android_screen.cancel_download_requested.emit()

    download_runner_class.instances[0].cancel.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_download_finished_ok_relaunches_detection(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    detect_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.android_adb.resolve_adb_path", return_value="/usr/bin/adb"):
        with patch("r36s_studio.gui.main_window.AndroidDetectRunner", detect_runner_class):
            window._on_android_download_finished(True, "/usr/bin/adb")

    detect_runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_download_finished_failure_does_not_relaunch_detection(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    detect_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.AndroidDetectRunner", detect_runner_class):
        window._on_android_download_finished(False, "")

    detect_runner_class.assert_not_called()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_download_error_cancelled_returns_to_consent_screen_silently(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._root_stack.setCurrentWidget(window._android_screen)

    window._on_android_download_error("CANCELLED", "annulé")

    assert window._android_screen._consent_frame.isVisible()
    assert not window._android_screen._download_error_label.isVisible()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_download_error_shows_friendly_message(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._root_stack.setCurrentWidget(window._android_screen)
    # En usage réel, un téléchargement est toujours lancé depuis la zone
    # "consent" (`show_downloading` ne change pas de zone) -- reproduit ici
    # pour que `_download_error_label` (à l'intérieur de `_consent_frame`)
    # puisse redevenir visible comme en conditions réelles.
    window._android_screen.show_downloading()

    window._on_android_download_error("PLATFORM_TOOLS_ERROR", "détail technique brut")

    assert window._android_screen._download_error_label.isVisible()
    # Message convivial, jamais le détail technique brut affiché tel quel.
    assert "détail technique brut" not in window._android_screen._download_error_label.text()


@patch("r36s_studio.gui.main_window.consoles_diverses_settings_store.lire_licence", return_value="cle")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch(
    "r36s_studio.gui.main_window.app_config.load_config",
    return_value=AppConfig(ui_mode="expert", consoles_diverses_server_url="https://exemple.invalid"),
)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_search_catalog_requested_starts_search_runner_with_configured_server(
    mock_list, mock_filter, mock_load, mock_save, mock_lire_licence, qapp
):
    window = MainWindow()
    search_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.ConsoleSearchRunner", search_runner_class):
        window._android_screen.search_catalog_requested.emit("RP Flip 2")

    search_runner_class.assert_called_once_with("RP Flip 2", "https://exemple.invalid", "cle")
    search_runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_search_catalog_requested_with_blank_reference_does_nothing(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    search_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.ConsoleSearchRunner", search_runner_class):
        window._android_screen.search_catalog_requested.emit("   ")

    search_runner_class.assert_not_called()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_search_finished_found_shows_fiche(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._on_android_detect_finished(DetectionResult(state="ready", device=_device_info()))
    fiche = fiche_depuis_json(
        {"id": "x", "identite": {"nom": "Retroid Pocket Flip 2"}, "statut": "verifie"}
    )

    window._on_android_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    assert window._android_screen._catalog_result_layout.count() > 0


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_search_finished_not_found_shows_message(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._root_stack.setCurrentWidget(window._android_screen)
    window._on_android_detect_finished(DetectionResult(state="ready", device=_device_info()))

    window._on_android_search_finished(ResultatRecherche(statut="aucune_information_trouvee", console=None))

    assert window._android_screen._catalog_status_label.isVisible()


@patch("r36s_studio.gui.main_window.consoles_diverses_settings_store.lire_licence", return_value="cle-partagee")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch(
    "r36s_studio.gui.main_window.app_config.load_config",
    return_value=AppConfig(ui_mode="expert", consoles_diverses_server_url="https://exemple.invalid"),
)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_android_search_uses_exactly_the_same_config_as_consoles_diverses(
    mock_list, mock_filter, mock_load, mock_save, mock_lire_licence, qapp
):
    """Signalé : « Impossible de joindre le serveur » depuis l'écran
    Console Android alors que la recherche marche depuis Consoles
    diverses -- vérifie que les deux chemins d'appel utilisent strictement
    la même URL de serveur et la même clé de licence (pas de configuration
    séparée pour cet écran, jamais une valeur par défaut différente)."""
    window = MainWindow()

    # Chemin « Consoles diverses » -- valeurs passées à `set_network_config`.
    window._open_consoles_diverses()
    consoles_diverses_url = window._consoles_diverses_screen._server_url
    consoles_diverses_licence = window._consoles_diverses_screen._licence_key

    # Chemin « Console Android » -- valeurs passées au constructeur du runner.
    search_runner_class = _mock_runner_class()
    with patch("r36s_studio.gui.main_window.ConsoleSearchRunner", search_runner_class):
        window._android_screen.search_catalog_requested.emit("RP Flip 2")
    android_call = search_runner_class.instances[0].init_args
    android_url, android_licence = android_call[1], android_call[2]

    assert android_url == consoles_diverses_url == "https://exemple.invalid"
    assert android_licence == consoles_diverses_licence == "cle-partagee"


@patch("r36s_studio.gui.main_window.consoles_diverses_settings_store.lire_licence", return_value="cle")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch(
    "r36s_studio.gui.main_window.app_config.load_config",
    return_value=AppConfig(ui_mode="expert", consoles_diverses_server_url="https://exemple.invalid/"),
)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_android_search_logs_the_called_url(
    mock_list, mock_filter, mock_load, mock_save, mock_lire_licence, qapp, tmp_path
):
    """Demandé explicitement : « Journalise l'URL appelée ». Le fixture
    autouse `_android_log_isolated` (tests/conftest.py) redirige `gui_logs.
    android_log_path` vers `tmp_path / "android.log"` -- même `tmp_path`
    que celui reçu ici (fixture function-scopée, une seule instance par
    test)."""
    window = MainWindow()
    search_runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.ConsoleSearchRunner", search_runner_class):
        window._android_screen.search_catalog_requested.emit("RP Flip 2")

    log_content = (tmp_path / "android.log").read_text(encoding="utf-8")
    assert "https://exemple.invalid/recherche" in log_content
    assert "RP Flip 2" in log_content


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_android_search_error_logs_url_and_error_code(mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path):
    """Demandé explicitement : « ... et le code d'erreur »."""
    window = MainWindow()
    search_runner_class = _mock_runner_class()
    with patch("r36s_studio.gui.main_window.ConsoleSearchRunner", search_runner_class):
        window._android_screen.search_catalog_requested.emit("RP Flip 2")

    window._on_android_search_error("serveur_injoignable", "")

    log_content = (tmp_path / "android.log").read_text(encoding="utf-8")
    assert "serveur_injoignable" in log_content
    assert "/recherche" in log_content


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_search_error_shows_friendly_message(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._root_stack.setCurrentWidget(window._android_screen)
    window._on_android_detect_finished(DetectionResult(state="ready", device=_device_info()))

    window._on_android_search_error("serveur_injoignable", "")

    assert window._android_screen._catalog_status_label.isVisible()
    assert window._android_screen._catalog_status_label.text()
