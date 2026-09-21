"""Tests de navigation de MainWindow (gui/main_window.py, §5 refonte
navigation) : une seule vue permanente (deux colonnes) devant laquelle les
choix ponctuels s'ouvrent en fenêtres modales, plutôt qu'une succession
d'écrans. Traverse le parcours de bout en bout pour les six étapes du
workflow à deux cartes (§4.4/§4.5) et la sauvegarde complète. `list_devices`,
`detect_workflow_status`, `WorkerRunner`/`PartitionJobRunner`, `archives` et
`eject_device` sont mockés — aucun périphérique réel, aucune élévation,
aucune écriture disque."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from r36s_studio import config as app_config
from r36s_studio.config import AppConfig
from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.doublons.move import default_destination as default_doublons_destination
from r36s_studio.gui import elevate
from r36s_studio.gui.main_window import MainWindow
from r36s_studio.gui.worker_runner import WorkerRunner
from r36s_studio.imaging.copy import ProgressEvent
from r36s_studio.partitions.locate import PartitionInfo

# La plupart des tests de ce fichier portent sur le parcours à six étapes
# (mode expert) -- `_EXPERT_MODE_CONFIG` démarre `MainWindow` directement
# sur `HomeScreen` plutôt que sur l'accueil du mode assisté (§5 mode
# assisté, par défaut sinon), pour ne pas changer le sens de tests déjà
# en place. Les tests du mode assisté lui-même (plus bas) repatchent
# `app_config.load_config` explicitement selon leurs besoins.
_EXPERT_MODE_CONFIG = AppConfig(ui_mode="expert")


def _make_device(path="/dev/fake-disk-test-3", size_bytes=32_000_000_000, display="Carte SD factice") -> Device:
    return Device(
        path=path,
        display=display,
        size_bytes=size_bytes,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


def _all_status(value: StepStatus) -> dict:
    return {
        "extract_boot": value,
        "extract_easyroms": value,
        "flash": value,
        "inject_boot": value,
        "copy_games": value,
        "eject": value,
    }


def _mock_runner_class():
    """Fabrique une classe de substitution pour WorkerRunner : chaque
    instance créée est un MagicMock enregistré dans `.instances` pour
    inspection, avec de vrais attributs Signal-like (mockés) sur lesquels
    `.connect()` fonctionne sans effet."""
    instances = []

    def _factory(argv, parent=None, macos_auth_session=None):
        instance = MagicMock()
        instance.argv = argv
        instance.macos_auth_session = macos_auth_session
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


def _mock_partition_runner_class():
    """Même principe que `_mock_runner_class`, pour `PartitionJobRunner`
    (mode, device, source_path positionnels)."""
    instances = []

    def _factory(mode, device, source_path, parent=None):
        instance = MagicMock()
        instance.mode = mode
        instance.device = device
        instance.source_path = source_path
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_flow_reaches_worker_with_correct_argv(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.backup_selected.emit()

        assert window._device_dialog.isVisible() is True
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        assert window._device_dialog.isVisible() is False  # fermée par MainWindow après le choix
        assert window._file_dialog.isVisible() is True

        with patch("r36s_studio.gui.screens.QFileDialog.getSaveFileName", return_value=("/tmp/out.img", "")):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

        # Backup n'écrit jamais sur un périphérique : pas de fenêtre de
        # confirmation, l'opération démarre directement.
        assert window._file_dialog.isVisible() is False
        assert window._confirm_dialog.isVisible() is False

    runner_class.assert_called_once()
    argv = runner_class.instances[0].argv
    assert argv == ["backup", "--device", "/dev/fake-disk-test-3", "--output", "/tmp/out.img"]
    runner_class.instances[0].start.assert_called_once()
    assert window._home._backup_row.isEnabled() is False  # occupé pendant l'opération


# --- sauvegarde système sans les jeux (§4.3) --------------------------------
#
# Contrairement à la sauvegarde complète ci-dessus, le choix de la carte
# déclenche d'abord une estimation de taille (SystemBackupEstimateRunner,
# sur un thread séparé -- lire la table de partitions et, en best-effort,
# monter le BOOT pour suggérer un nom de fichier peut bloquer) avant
# d'ouvrir la fenêtre Choix du fichier.


def _mock_estimate_runner_class():
    instances = []

    def _factory(*args, **kwargs):
        instance = MagicMock()
        instance.init_args = args
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_system_device_chosen_starts_estimate_runner_not_file_dialog(
    mock_list, mock_filter, mock_detect, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    estimate_runner_class = _mock_estimate_runner_class()

    with patch("r36s_studio.gui.main_window.SystemBackupEstimateRunner", estimate_runner_class):
        window = MainWindow()
        window._home.backup_system_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

    estimate_runner_class.assert_called_once_with(device.path, parent=window)
    estimate_runner_class.instances[0].start.assert_called_once()
    assert window._file_dialog.isVisible() is False


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_system_estimate_marks_home_busy_while_running(mock_list, mock_filter, mock_detect, qapp):
    """Sans ceci, un clic sur une autre ligne (y compris Éjecter) pendant
    le calcul de l'estimation lancerait une deuxième opération en même
    temps -- scénario probable derrière le bug rapporté (carte éjectée
    pendant que la sauvegarde système était censée être en cours)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    estimate_runner_class = _mock_estimate_runner_class()

    with patch("r36s_studio.gui.main_window.SystemBackupEstimateRunner", estimate_runner_class):
        window = MainWindow()
        window._home.backup_system_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

    assert window._home._backup_row.isEnabled() is False
    assert window._home._backup_system_row.isEnabled() is False
    for tile in window._home._tiles.values():
        assert tile.isEnabled() is False


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_releases_busy_state_on_success(mock_list, mock_filter, mock_detect, qapp):
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()
    window._home.set_busy(True)

    window._on_system_backup_estimate_ready(SystemBackupEstimate(size_bytes=9_000_000_000))

    for tile in window._home._tiles.values():
        assert tile.isEnabled() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_releases_busy_state_on_error(mock_list, mock_filter, mock_detect, qapp):
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()
    window._home.set_busy(True)

    window._on_system_backup_estimate_ready(SystemBackupEstimate(error="IO_ERROR", detail="x"))

    for tile in window._home._tiles.values():
        assert tile.isEnabled() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_opens_file_dialog_with_model_in_suggested_filename(mock_list, mock_filter, mock_detect, qapp):
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()

    window._on_system_backup_estimate_ready(
        SystemBackupEstimate(size_bytes=9_000_000_000, board_compatible="rk3326-r35s")
    )

    assert window._file_dialog.isVisible() is True
    suggested = window._file_dialog._path_label.text()
    assert "rk3326-r35s" in suggested
    assert suggested.endswith(".img")


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_shows_the_size_directly_on_the_file_dialog(mock_list, mock_filter, mock_detect, qapp):
    """§4.3 : « affiche la taille estimée et demande confirmation avant de
    lancer » -- visible sur la fenêtre elle-même, pas seulement dans le
    journal de bord."""
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()

    window._on_system_backup_estimate_ready(SystemBackupEstimate(size_bytes=9_000_000_000, board_compatible=None))

    assert window._file_dialog._system_backup_size_label.isVisible() is True
    assert "8.4 Go" in window._file_dialog._system_backup_size_label.text()


# --- repli élevé (§4.3, confirmé sur du vrai matériel : lire la table de --
# --- partitions brute exige les droits administrateur sur macOS) ----------


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_needs_elevation_starts_elevated_worker_and_stays_busy(mock_list, mock_filter, mock_detect, qapp):
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    device = _make_device()
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._mode = "backup_system"
        window._device = device
        window._home.set_busy(True)
        window._assisted_landing.set_busy(True)

        window._on_system_backup_estimate_ready(
            SystemBackupEstimate(needs_elevation=True, board_compatible="rk3326-r35s")
        )

    runner_class.assert_called_once_with(
        ["backup", "--device", device.path, "--system-only", "--estimate-only"],
        parent=window,
        macos_auth_session=None,
    )
    runner_class.instances[0].start.assert_called_once()
    # Toujours occupé -- le premier temps de l'opération n'est pas terminé.
    for tile in window._home._tiles.values():
        assert tile.isEnabled() is False


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_elevated_estimate_success_opens_file_dialog_and_releases_busy(mock_list, mock_filter, mock_detect, qapp):
    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()
    window._home.set_busy(True)
    window._pending_estimate_board_compatible = "rk3326-r35s"

    window._on_elevated_system_backup_estimate(9_000_000_000)
    window._on_elevated_system_backup_estimate_finished(True)

    assert window._file_dialog.isVisible() is True
    suggested = window._file_dialog._path_label.text()
    assert "rk3326-r35s" in suggested
    assert "8.4 Go" in window._file_dialog._system_backup_size_label.text()
    for tile in window._home._tiles.values():
        assert tile.isEnabled() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_elevated_estimate_failure_logs_real_detail_and_releases_busy(mock_list, mock_filter, mock_detect, qapp):
    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()
    window._home.set_busy(True)
    window._pending_estimate_board_compatible = None

    window._on_worker_error("IO_ERROR", "[Errno 13] Permission denied: '/dev/disk2'")
    window._on_elevated_system_backup_estimate_finished(False)

    assert window._file_dialog.isVisible() is False
    log_text = window._log_panel._log_view.toPlainText()
    assert "Permission denied" in log_text
    for tile in window._home._tiles.values():
        assert tile.isEnabled() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_elevated_estimate_finished_true_without_estimate_event_is_treated_as_failure(
    mock_list, mock_filter, mock_detect, qapp
):
    """Défensif : `finished(True)` sans qu'aucun `estimate` n'ait jamais
    été reçu ne doit jamais être traité comme un succès silencieux."""
    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()
    window._pending_estimate_size_bytes = None

    window._on_elevated_system_backup_estimate_finished(True)

    assert window._file_dialog.isVisible() is False


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_suggested_filename_preserves_periods_in_model(mock_list, mock_filter, mock_detect, qapp):
    """Un identifiant de carte réel peut contenir un point (ex. un numéro
    de révision de carte, `G80CA-MB-V1.2`) -- ne doit pas être défiguré
    par la mise en sécurité du nom de fichier."""
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()

    window._on_system_backup_estimate_ready(
        SystemBackupEstimate(size_bytes=9_000_000_000, board_compatible="G80CA-MB-V1.2")
    )

    suggested = window._file_dialog._path_label.text()
    assert "G80CA-MB-V1.2" in suggested
    log_text = window._log_panel._log_view.toPlainText()
    assert "8.4 Go" in log_text  # taille estimée journalisée avant l'ouverture


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_suggests_a_filename_without_model_when_unknown(mock_list, mock_filter, mock_detect, qapp):
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()

    window._on_system_backup_estimate_ready(SystemBackupEstimate(size_bytes=9_000_000_000, board_compatible=None))

    assert window._file_dialog.isVisible() is True
    assert window._file_dialog._path_label.text().endswith(".img")


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_shows_friendly_error_and_does_not_open_file_dialog(mock_list, mock_filter, mock_detect, qapp):
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()

    window._on_system_backup_estimate_ready(SystemBackupEstimate(error="GAMES_PARTITION_NOT_FOUND"))

    assert window._file_dialog.isVisible() is False
    log_text = window._log_panel._log_view.toPlainText()
    assert "jeux" in log_text.lower()


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_logs_the_real_error_detail(mock_list, mock_filter, mock_detect, qapp):
    """Bug rapporté : le journal n'affichait que « Une erreur est
    survenue », sans la cause réelle -- doit apparaître comme ligne
    supplémentaire, comme pour toute autre opération (§5)."""
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()

    window._on_system_backup_estimate_ready(
        SystemBackupEstimate(error="IO_ERROR", detail="[Errno 6] Device not configured")
    )

    log_text = window._log_panel._log_view.toPlainText()
    assert "Device not configured" in log_text


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_estimate_ready_refreshes_home_state_on_error(mock_list, mock_filter, mock_detect, qapp):
    """La carte a pu disparaître entre le lancement et l'échec de
    l'estimation (bug rapporté) -- le bandeau/les lignes « Par sécurité »
    doivent refléter l'état réel, pas rester sur une détection périmée."""
    from r36s_studio.gui.partition_runner import SystemBackupEstimate

    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()
    mock_detect.reset_mock()

    window._on_system_backup_estimate_ready(SystemBackupEstimate(error="IO_ERROR", detail="carte débranchée"))

    mock_detect.assert_called_once()


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_system_flow_reaches_worker_with_system_only_flag(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    window = MainWindow()
    window._mode = "backup_system"
    window._device = device
    window._file_path = "/tmp/systeme_rk3326-r35s_2026-07-06_00-21.img"

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    argv = runner_class.instances[0].argv
    assert argv == [
        "backup",
        "--device",
        device.path,
        "--output",
        "/tmp/systeme_rk3326-r35s_2026-07-06_00-21.img",
        "--system-only",
    ]


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_success_message_mentions_system(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._mode = "backup_system"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    assert "système" in window._success_message().lower()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_reachable_from_assisted_landing(mock_list, mock_filter, mock_load, qapp):
    """§4.3 : proposée comme option du mode assisté, pas seulement depuis
    l'écran expert -- réutilise `MainView`/`_log_panel` le temps de
    l'opération (journal de bord, états occupé), mais reste dans
    l'habillage assisté (`WizardStepPanel`), jamais l'écran expert
    (`HomeScreen`) -- correctif d'un défaut de parcours signalé (bascule
    vers le mode expert pendant l'opération)."""
    window = MainWindow()
    assert window._root_stack.currentWidget() is window._assisted_landing

    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._wizard_panel
    assert window._device_dialog.isVisible() is True  # _start_flow("backup_system") a démarré


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_from_assisted_landing_does_not_persist_expert_mode(mock_list, mock_filter, mock_load, qapp):
    """Contrairement au bouton « Mode expert » -- ce n'est qu'un passage
    temporaire par l'écran expert, pas un vrai changement de mode : rien
    à retrouver en mode expert au prochain lancement."""
    with patch("r36s_studio.gui.main_window.app_config.save_config") as mock_save:
        window = MainWindow()
        window._assisted_landing.backup_requested.emit()
        window._assisted_backup_kind_dialog.system_only_requested.emit()

    mock_save.assert_not_called()
    assert window._app_config.ui_mode == "assisted"


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_success_offers_prepare_card_and_return_home(mock_list, mock_filter, mock_load, qapp):
    """Correctif d'un défaut de parcours signalé : une fois la sauvegarde
    terminée, l'utilisateur ne doit jamais se retrouver sans proposition
    de suite -- deux choix explicites sur le panneau assisté."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"

    window._on_worker_finished(True)

    assert window._root_stack.currentWidget() is window._main_view
    assert window._wizard_panel._prepare_card_button.isVisible() is True
    assert window._wizard_panel._return_home_button.isVisible() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "/tmp/systeme.img" in log_text  # chemin du fichier créé, affiché


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_failure_only_offers_return_home(mock_list, mock_filter, mock_load, qapp):
    """Un échec n'a rien produit à préparer -- seul le retour a du sens,
    jamais un choix qui n'en a pas."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._last_error_code = "IO_ERROR"
    window._last_error_msg = "disque plein"

    window._on_worker_finished(False)

    assert window._wizard_panel._prepare_card_button.isVisible() is False
    assert window._wizard_panel._return_home_button.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_return_home_switches_to_assisted_landing(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)

    window._wizard_panel.return_to_home_requested.emit()

    assert window._root_stack.currentWidget() is window._assisted_landing
    assert window._assisted_ad_hoc_active is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_prepare_card_starts_polling_with_continue_disabled(
    mock_list, mock_filter, mock_load, qapp
):
    """Bug corrigé, constaté en conditions réelles : cet écran n'affichait
    aucun bandeau de détection (contrairement aux étapes 1/4) et son
    bouton Continuer ne déclenchait rien -- ni sondage démarré, ni action
    câblée. Doit démarrer le même sondage automatique que les étapes 1/4,
    Continuer désactivé tant qu'aucune carte n'est trouvée."""
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device_dialog.close()  # fenêtre Choix de la carte de l'étape backup_system, non simulée ici
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)

    window._wizard_panel.prepare_card_requested.emit()

    assert window._mode == "flash"
    assert window._file_path == "/tmp/systeme.img"
    assert window._prepare_card_poll_timer.isActive() is True
    assert window._device_dialog.isVisible() is False  # jamais immédiatement
    assert window._root_stack.currentWidget() is window._main_view
    assert window._wizard_panel._continue_button.isEnabled() is False


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_system_prepare_card_single_candidate_enables_continue(
    mock_list, mock_filter, mock_load, mock_detect, qapp
):
    new_device = _make_device(path="/dev/fake-disk-test-9", display="Carte neuve")
    mock_list.return_value = [new_device]
    mock_filter.return_value = [new_device]
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)
    window._wizard_panel.prepare_card_requested.emit()

    window._on_prepare_card_poll()

    assert window._wizard_panel._continue_button.isEnabled() is True
    assert window._prepare_card_poll_timer.isActive() is False  # trouvée -> plus besoin de resonder
    assert "Carte neuve" in window._wizard_panel._status_label.text()


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_system_prepare_card_continue_proceeds_to_confirmation(
    mock_list, mock_filter, mock_load, mock_detect, qapp
):
    """« Préparer une carte avec cette sauvegarde » réutilise le fichier
    déjà créé comme source du flash -- jamais un aller vers l'écran expert
    (§5 mode assisté) : reste sur MainView/WizardStepPanel, la fenêtre
    Choix du fichier est inutile puisque le fichier est déjà connu. La
    fenêtre Confirmation, elle, reste obligatoire (§2 n°6)."""
    new_device = _make_device(path="/dev/fake-disk-test-9", display="Carte neuve")
    mock_list.return_value = [new_device]
    mock_filter.return_value = [new_device]
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)
    window._wizard_panel.prepare_card_requested.emit()
    window._on_prepare_card_poll()

    window._wizard_panel.continue_requested.emit()

    assert window._file_dialog.isVisible() is False
    assert window._confirm_dialog.isVisible() is True
    assert window._device is new_device
    assert window._prepare_card_candidate is None  # consommé


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_system_prepare_card_multiple_candidates_falls_back_to_device_dialog(
    mock_list, mock_filter, mock_load, qapp
):
    devices = [
        _make_device(path="/dev/fake-disk-test-9", display="Carte 1"),
        _make_device(path="/dev/fake-disk-test-10", display="Carte 2"),
    ]
    mock_list.return_value = devices
    mock_filter.return_value = devices
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)
    window._wizard_panel.prepare_card_requested.emit()

    window._on_prepare_card_poll()

    assert window._prepare_card_poll_timer.isActive() is False
    assert window._device_dialog.isVisible() is True

    window._device_dialog._list.setCurrentRow(1)
    window._device_dialog._emit_chosen()

    # Fichier déjà connu même via ce repli : la fenêtre Choix du fichier
    # reste sautée, direct à la fenêtre Confirmation.
    assert window._file_dialog.isVisible() is False
    assert window._confirm_dialog.isVisible() is True
    assert window._device is devices[1]


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_prepare_card_no_candidate_keeps_waiting(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device_dialog.close()  # fenêtre Choix de la carte de l'étape backup_system, non simulée ici
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)
    window._wizard_panel.prepare_card_requested.emit()

    window._on_prepare_card_poll()

    assert window._prepare_card_poll_timer.isActive() is True
    assert window._wizard_panel._continue_button.isEnabled() is False
    assert window._device_dialog.isVisible() is False


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_system_prepare_card_refresh_button_polls_the_right_target(
    mock_list, mock_filter, mock_load, mock_detect, qapp
):
    """Le bouton Actualiser de cet écran ne doit jamais relancer le
    sondage du vrai parcours guidé (`_on_wizard_poll`, qui opère sur
    `self._wizard_flow` -- sans rapport ici)."""
    new_device = _make_device(path="/dev/fake-disk-test-9", display="Carte neuve")
    mock_list.return_value = [new_device]
    mock_filter.return_value = [new_device]
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)
    window._wizard_panel.prepare_card_requested.emit()
    window._prepare_card_poll_timer.stop()  # simule un sondage arrêté (ex. dialogue multi-cartes fermé)

    window._wizard_panel.refresh_requested.emit()

    assert window._wizard_panel._continue_button.isEnabled() is True  # a retrouvé la carte unique


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_prepare_card_cancel_stops_polling(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)
    window._wizard_panel.prepare_card_requested.emit()
    assert window._prepare_card_poll_timer.isActive() is True

    window._wizard_panel.cancel_requested.emit()

    assert window._prepare_card_poll_timer.isActive() is False
    assert window._root_stack.currentWidget() is window._assisted_landing


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_backup_system_prepare_card_flash_finished_only_offers_return_home(
    mock_list, mock_filter, mock_load, qapp
):
    """Une fois la carte préparée (succès ou échec), plus rien à préparer
    -- seul le retour à l'accueil reste proposé."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._assisted_landing.backup_requested.emit()
    window._assisted_backup_kind_dialog.system_only_requested.emit()
    window._device = _make_device()
    window._file_path = "/tmp/systeme.img"
    window._on_worker_finished(True)
    window._wizard_panel.prepare_card_requested.emit()
    window._device = _make_device()

    window._on_worker_finished(True)

    assert window._mode == "flash"
    assert window._wizard_panel._prepare_card_button.isVisible() is False
    assert window._wizard_panel._return_home_button.isVisible() is True


# --- Mécanisme ad-hoc généralisé (§5, refonte menu de tuiles) : vérifié ---
# --- ci-dessus pour backup/backup_system, ici pour un second job_key -----
# --- (copy_games) et pour l'éjection (chemin d'exécution distinct, -------
# --- _perform_eject/_on_perform_eject_finished, jamais _start_worker). ---


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_copy_games_ad_hoc_from_assisted_landing_offers_next_step_choice(
    mock_list, mock_filter, mock_load, qapp
):
    """Généralisation du mécanisme ad-hoc à un job_key au-delà de backup/
    backup_system -- même mécanisme (`_start_assisted_ad_hoc_job`), une
    table de chaînes au lieu d'un `if`/`else` en dur pour exactement deux
    cas."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    window._assisted_landing.copy_games_requested.emit()

    assert window._mode == "copy_games"
    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._wizard_panel

    window._device = _make_device()
    window._file_path = "/tmp/games"
    window._on_worker_finished(True)

    assert window._wizard_panel._return_home_button.isVisible() is True
    # "Préparer une carte avec cette sauvegarde" n'a de sens qu'après une
    # sauvegarde (backup/backup_system) -- jamais pour copy_games.
    assert window._wizard_panel._prepare_card_button.isVisible() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_ad_hoc_from_assisted_landing_offers_next_step_choice_not_refresh_home(
    mock_list, mock_filter, mock_load, qapp
):
    """§5, refonte menu de tuiles -- correctif du même défaut de parcours
    déjà corrigé pour les autres tuiles-job : l'éjection ad-hoc doit
    proposer une suite explicite (`show_next_step_choice`), jamais un
    `_refresh_home_state()` qui ne fait rien d'utile pour un écran de
    tuiles jamais visible à ce moment (`_home` n'est pas affiché)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    def _fake_start_eject(dev, on_finished):
        on_finished(True, None, None)

    with patch.object(window, "_start_eject", side_effect=_fake_start_eject), patch.object(
        window, "_refresh_home_state"
    ) as mock_refresh:
        window._assisted_landing.eject_requested.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

    mock_refresh.assert_not_called()
    assert window._wizard_panel._return_home_button.isVisible() is True


# --- Tuile « Rechercher ma console » (identification DTB, §5) --------------


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_start_assisted_identify_single_device_runs_identify_and_shows_result(mock_list, mock_filter, qapp):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    with patch("r36s_studio.gui.main_window.IdentifyRunner") as mock_runner_class:
        instance = MagicMock()
        mock_runner_class.return_value = instance
        window._assisted_landing.identify_requested.emit()

        mock_runner_class.assert_called_once_with(device.path, parent=window)
        instance.start.assert_called_once()
        callback = instance.finished_identify.connect.call_args[0][0]
        callback(IdentifyResult(info=DtbInfo(board_compatible="rk3326-r35s", panel_compatible=None)))

    assert window._identify_result_dialog.isVisible() is True
    assert "rk3326-r35s" in window._identify_result_dialog._message.text()


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_assisted_identify_multiple_devices_opens_dedicated_device_dialog(mock_list, mock_filter, qapp):
    """Instance dédiée (`_identify_device_dialog`), jamais `_device_dialog`
    (câblé au grand dispatcher `_on_device_chosen`, sans rapport avec ce
    flux ponctuel)."""
    devices = [_make_device(path="/dev/fake-disk-test-a"), _make_device(path="/dev/fake-disk-test-b")]
    mock_list.return_value = devices
    mock_filter.return_value = devices
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    window._assisted_landing.identify_requested.emit()

    assert window._identify_device_dialog.isVisible() is True
    assert window._device_dialog.isVisible() is False


# --- Outil « Doublons de jeux » (docs/doublons.md, outil autonome) --------
# Remplace l'ancien flux carte-SD-uniquement (`partitions.dedupe`, jamais
# implémenté au-delà de ce test mort) : la tuile ouvre désormais un choix
# de dossier quelconque, plus aucun rapport avec une carte détectée.


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_find_duplicates_tile_opens_folder_screen_then_scan_shows_results(mock_list, mock_filter, qapp, tmp_path):
    from r36s_studio.doublons.scan import ExactDuplicateGroup, ScanResult, Unit

    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    window._assisted_landing.find_duplicates_requested.emit()
    assert window._root_stack.currentWidget() is window._doublons_folder_screen

    unit_a = Unit(tmp_path / "Aladdin.zip", [tmp_path / "Aladdin.zip"], 10, False)
    unit_b = Unit(tmp_path / "Aladdin.7z", [tmp_path / "Aladdin.7z"], 10, False)
    result = ScanResult(
        exact_duplicate_groups=[ExactDuplicateGroup([unit_a, unit_b], sha256="a" * 64)], files_scanned=2
    )

    with patch("r36s_studio.gui.main_window.DoublonsScanRunner") as mock_runner_class:
        instance = MagicMock()
        mock_runner_class.return_value = instance
        window._doublons_folder_screen.folder_chosen.emit(str(tmp_path))

        mock_runner_class.assert_called_once_with(
            str(tmp_path), window._app_config.doublons_ignored_folders, parent=window
        )
        callback = instance.finished_scan.connect.call_args[0][0]
        callback(result)

    assert window._root_stack.currentWidget() is window._doublons_results_screen
    assert window._doublons_results_screen._empty_label.isVisible() is False


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_move_confirmed_starts_move_runner_and_rescans(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    from r36s_studio.doublons.scan import Unit

    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._doublons_root = str(tmp_path)
    dry_run = window._app_config.doublons_simulation_mode
    units = [Unit(tmp_path / "Aladdin.7z", [tmp_path / "Aladdin.7z"], 10, False)]

    with patch("r36s_studio.gui.main_window.DoublonsMoveRunner") as mock_move_class, patch(
        "r36s_studio.gui.main_window.DoublonsScanRunner"
    ) as mock_scan_class:
        move_instance = MagicMock()
        mock_move_class.return_value = move_instance
        scan_instance = MagicMock()
        mock_scan_class.return_value = scan_instance

        window._doublons_results_screen.move_requested.emit(units)
        window._confirm_move_doublons_dialog.confirmed.emit()

        expected_destination = default_doublons_destination(str(tmp_path))
        mock_move_class.assert_called_once_with(
            str(tmp_path), units, dry_run, destination=expected_destination, parent=window
        )
        move_instance.start.assert_called_once()

        finished_callback = move_instance.finished_move.connect.call_args[0][0]
        finished_callback(True)

        # Relance toujours un scan frais après un déplacement -- reflète
        # l'état réel du dossier plutôt qu'une mise à jour partielle.
        mock_scan_class.assert_called_once_with(
            str(tmp_path), window._app_config.doublons_ignored_folders, parent=window
        )


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_move_confirmed_shows_real_progress(mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path):
    """Signalement utilisateur (1900 fichiers, 1272 groupes), règle §2
    n°5 -- une barre de progression réelle, jamais simulée, pendant le
    déplacement de la sélection."""
    from r36s_studio.doublons.scan import Unit

    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._doublons_root = str(tmp_path)
    units = [
        Unit(tmp_path / "a.7z", [tmp_path / "a.7z"], 10, False),
        Unit(tmp_path / "b.7z", [tmp_path / "b.7z"], 10, False),
    ]

    with patch("r36s_studio.gui.main_window.DoublonsMoveRunner") as mock_move_class:
        move_instance = MagicMock()
        mock_move_class.return_value = move_instance

        window._doublons_results_screen.move_requested.emit(units)
        window._confirm_move_doublons_dialog.confirmed.emit()

        assert window._root_stack.currentWidget() is window._doublons_move_progress_screen
        assert window._doublons_move_progress_screen._progress_bar.maximum() == 2

        progress_callback = move_instance.progress.connect.call_args[0][0]
        progress_callback(1, 2)

    assert window._doublons_move_progress_screen._progress_bar.value() == 1


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_move_progress_screen_cancel_button_cancels_runner(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    """Si l'utilisateur annule en cours, ce qui a déjà été déplacé reste
    dans le journal (move.py, écriture au fil de l'eau) -- ce test vérifie
    seulement que le clic Annuler atteint bien le runner en cours."""
    from r36s_studio.doublons.scan import Unit

    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._doublons_root = str(tmp_path)
    units = [Unit(tmp_path / "a.7z", [tmp_path / "a.7z"], 10, False)]

    with patch("r36s_studio.gui.main_window.DoublonsMoveRunner") as mock_move_class:
        move_instance = MagicMock()
        mock_move_class.return_value = move_instance

        window._doublons_results_screen.move_requested.emit(units)
        window._confirm_move_doublons_dialog.confirmed.emit()

        from PySide6.QtWidgets import QPushButton

        from r36s_studio.gui.strings import tr

        cancel_button = [
            b
            for b in window._doublons_move_progress_screen.findChildren(QPushButton)
            if b.text() == tr("doublons_scan_cancel_button")
        ][0]
        cancel_button.click()

        move_instance.cancel.assert_called_once()


# --- Destination du déplacement (signalé explicitement : « permettre de
# choisir l'emplacement du dossier de destination, au lieu de _doublons
# imposé à la racine du dossier analysé ») ----------------------------------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_scan_finished_prefills_destination_field_with_default(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    from r36s_studio.doublons.scan import ScanResult

    window = MainWindow()
    window._doublons_root = str(tmp_path)

    window._on_doublons_scan_finished(ScanResult())

    expected = default_doublons_destination(str(tmp_path))
    assert window._doublons_destination == expected
    assert window._doublons_results_screen.destination() == expected


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_scan_finished_prefills_destination_with_remembered_last_choice(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    from r36s_studio.doublons.scan import ScanResult

    window = MainWindow()
    remembered = tmp_path / "elsewhere"
    window._app_config.doublons_last_destination = str(remembered)
    window._doublons_root = str(tmp_path / "root")

    window._on_doublons_scan_finished(ScanResult())

    assert window._doublons_destination == str(remembered)
    assert window._doublons_results_screen.destination() == str(remembered)


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_scan_finished_ignores_a_remembered_destination_now_invalid_for_this_root(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    """La destination mémorisée provient d'une session précédente, sur un
    dossier analysé différent -- si elle se trouve être refusée pour le
    dossier actuel (ex. à l'intérieur de celui-ci), retombe sur la
    proposition par défaut plutôt que d'appliquer silencieusement une
    valeur invalide."""
    from r36s_studio.doublons.scan import ScanResult

    window = MainWindow()
    root = tmp_path / "root"
    window._app_config.doublons_last_destination = str(root / "some_other_folder")
    window._doublons_root = str(root)

    window._on_doublons_scan_finished(ScanResult())

    assert window._doublons_destination == default_doublons_destination(str(root))


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_destination_chosen_updates_state_and_remembers_it(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    window = MainWindow()
    window._doublons_root = str(tmp_path / "root")
    chosen = str(tmp_path / "backup")

    window._on_doublons_destination_chosen(chosen)

    assert window._doublons_destination == chosen
    assert window._doublons_results_screen.destination() == chosen
    assert window._app_config.doublons_last_destination == chosen
    mock_save.assert_called_once()


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_destination_chosen_refuses_a_folder_inside_root(
    mock_list, mock_filter, mock_load, mock_save, mock_warning, qapp, tmp_path
):
    window = MainWindow()
    root = tmp_path / "root"
    window._doublons_root = str(root)
    window._doublons_destination = "/previous"
    window._doublons_results_screen.set_destination("/previous")

    window._on_doublons_destination_chosen(str(root / "some_other_folder"))

    mock_warning.assert_called_once()
    # Refusé -- l'état précédent n'est jamais silencieusement remplacé.
    assert window._doublons_destination == "/previous"
    assert window._doublons_results_screen.destination() == "/previous"
    mock_save.assert_not_called()


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_destination_chosen_refuses_a_filesystem_root(
    mock_list, mock_filter, mock_load, mock_save, mock_warning, qapp, tmp_path
):
    window = MainWindow()
    window._doublons_root = str(tmp_path / "root")

    with patch("r36s_studio.gui.main_window.check_destination_allowed") as mock_check:
        from r36s_studio.doublons.move import DestinationIsFilesystemRoot

        mock_check.side_effect = DestinationIsFilesystemRoot("C:\\")
        window._on_doublons_destination_chosen("C:\\")

    mock_warning.assert_called_once()
    assert window._doublons_destination is None


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_destination_chosen_refuses_a_read_only_folder(
    mock_list, mock_filter, mock_load, mock_save, mock_warning, qapp, tmp_path
):
    window = MainWindow()
    window._doublons_root = str(tmp_path / "root")

    with patch("r36s_studio.gui.main_window.check_destination_allowed") as mock_check:
        from r36s_studio.doublons.move import DestinationNotWritable

        mock_check.side_effect = DestinationNotWritable("/read-only", "reason")
        window._on_doublons_destination_chosen("/read-only")

    mock_warning.assert_called_once()
    assert window._doublons_destination is None


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_cross_volume_warning_shown_when_destination_on_another_disk(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    window = MainWindow()
    window._doublons_root = str(tmp_path / "root")

    with patch("r36s_studio.gui.main_window.is_cross_volume_destination", return_value=True):
        window._on_doublons_destination_chosen(str(tmp_path / "backup"))

    # Vérifié via `isHidden()` plutôt que `isVisible()` -- pas de
    # `window.show()` ici, `isVisible()` resterait `False` quel que soit
    # l'appel à `setVisible(True)` (piège Qt déjà documenté ailleurs dans
    # ce fichier).
    assert window._doublons_results_screen._cross_volume_banner.isHidden() is False


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_cross_volume_warning_hidden_for_same_disk_destination(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    window = MainWindow()
    window._doublons_root = str(tmp_path / "root")

    with patch("r36s_studio.gui.main_window.is_cross_volume_destination", return_value=False):
        window._on_doublons_destination_chosen(str(tmp_path / "backup"))

    assert window._doublons_results_screen._cross_volume_banner.isHidden() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch(
    "r36s_studio.gui.main_window.app_config.load_config",
    return_value=AppConfig(ui_mode="expert", doublons_simulation_mode=False),
)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_move_confirmed_records_destination_for_a_real_move(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    """Un déplacement réel (pas une simulation) mémorise la destination
    dans l'historique (§4 demandé explicitement) -- pour que « Tout
    annuler » la retrouve même après un changement de destination."""
    from r36s_studio.doublons.scan import Unit

    window = MainWindow()
    window._doublons_root = str(tmp_path)
    window._doublons_destination = str(tmp_path / "backup")
    units = [Unit(tmp_path / "a.7z", [tmp_path / "a.7z"], 10, False)]

    with patch("r36s_studio.gui.main_window.DoublonsMoveRunner"):
        window._doublons_results_screen.move_requested.emit(units)
        window._confirm_move_doublons_dialog.confirmed.emit()

    assert window._app_config.doublons_last_destination == str(tmp_path / "backup")
    assert str(tmp_path / "backup") in window._app_config.doublons_recent_destinations


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch(
    "r36s_studio.gui.main_window.app_config.load_config",
    return_value=AppConfig(ui_mode="expert", doublons_simulation_mode=True),
)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_move_confirmed_never_records_destination_for_a_simulated_move(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    from r36s_studio.doublons.scan import Unit

    window = MainWindow()
    window._doublons_root = str(tmp_path)
    window._doublons_destination = str(tmp_path / "backup")
    units = [Unit(tmp_path / "a.7z", [tmp_path / "a.7z"], 10, False)]

    with patch("r36s_studio.gui.main_window.DoublonsMoveRunner"):
        window._doublons_results_screen.move_requested.emit(units)
        window._confirm_move_doublons_dialog.confirmed.emit()

    assert window._app_config.doublons_recent_destinations == []


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_undo_confirmed_sweeps_recent_and_current_destinations(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    """Signalé explicitement : « annulation depuis une autre destination »
    -- « Tout annuler » doit interroger l'historique mémorisé en plus de
    la destination de la session en cours, pas seulement cette dernière."""
    window = MainWindow()
    window._doublons_root = str(tmp_path / "root")
    window._doublons_destination = str(tmp_path / "current")
    window._app_config.doublons_recent_destinations = [str(tmp_path / "old_1"), str(tmp_path / "old_2")]

    with patch("r36s_studio.gui.main_window.DoublonsUndoRunner") as mock_undo_class:
        instance = MagicMock()
        mock_undo_class.return_value = instance

        window._doublons_results_screen.undo_requested.emit()
        window._confirm_undo_doublons_dialog.confirmed.emit()

        called_destinations = mock_undo_class.call_args[0][0]
        assert str(tmp_path / "current") in called_destinations
        assert str(tmp_path / "old_1") in called_destinations
        assert str(tmp_path / "old_2") in called_destinations
        instance.start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_doublons_undo_available_reflects_any_known_destination_with_a_journal(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    """Vérifié avec un vrai journal sur disque (pas de mock de `has_
    pending_journal_entries`) -- une destination mémorisée mais différente
    de celle de la session en cours doit quand même activer le bouton."""
    from r36s_studio.doublons.scan import ScanResult

    old_destination = tmp_path / "old_backup"
    old_destination.mkdir()
    (old_destination / "journal.json").write_text(
        '[{"source": "a", "destination": "b", "moved_at": "now"}]', encoding="utf-8"
    )

    window = MainWindow()
    window._doublons_root = str(tmp_path / "root")
    window._app_config.doublons_recent_destinations = [str(old_destination)]

    window._on_doublons_scan_finished(ScanResult())

    assert window._doublons_results_screen._undo_button.isEnabled() is True


# --- Écran de bienvenue macOS : Accès complet au disque (§3) ---------------
# `elevate.has_full_disk_access` est forcée à `True` par l'autofixture
# `_default_full_disk_access_granted` (tests/conftest.py) sauf ici, où
# chaque test la repatche explicitement pour exercer les deux issues.


@patch("r36s_studio.gui.main_window.elevate.has_full_disk_access", return_value=False)
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_startup_shows_fda_welcome_screen_when_not_granted_on_macos(
    mock_list, mock_filter, mock_load, mock_system, mock_fda, qapp
):
    """Autorisation absente sur macOS : l'écran de bienvenue remplace
    l'accueil habituel (assisté ou expert), quel que soit `ui_mode`."""
    window = MainWindow()

    assert window._root_stack.currentWidget() is window._fda_screen


@patch("r36s_studio.gui.main_window.elevate.has_full_disk_access", return_value=True)
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_startup_skips_fda_welcome_screen_when_already_granted(
    mock_list, mock_filter, mock_load, mock_system, mock_fda, qapp
):
    window = MainWindow()

    assert window._root_stack.currentWidget() is window._assisted_landing


@patch("r36s_studio.gui.main_window.elevate.has_full_disk_access", return_value=False)
@patch("r36s_studio.gui.main_window.platform.system", return_value="Windows")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_startup_ignores_fda_status_outside_macos(mock_list, mock_filter, mock_load, mock_system, mock_fda, qapp):
    """Le blocage TCC est spécifique à macOS (§3) -- une valeur `False`
    ailleurs (accident de mock, comportement futur imprévu...) ne doit
    jamais faire apparaître cet écran sur Windows/Linux."""
    window = MainWindow()

    assert window._root_stack.currentWidget() is window._assisted_landing


@patch("r36s_studio.gui.main_window.elevate.has_full_disk_access")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_fda_recheck_success_switches_to_normal_startup_screen(
    mock_list, mock_filter, mock_load, mock_system, mock_fda, qapp
):
    """Bouton « J'ai terminé » : une fois l'autorisation détectée, l'écran
    de bienvenue ne réapparaît plus (§ demande utilisateur)."""
    mock_fda.return_value = False
    window = MainWindow()
    assert window._root_stack.currentWidget() is window._fda_screen

    mock_fda.return_value = True
    window._fda_screen.recheck_requested.emit()

    assert window._root_stack.currentWidget() is window._assisted_landing


@patch("r36s_studio.gui.main_window.elevate.has_full_disk_access", return_value=False)
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_fda_recheck_failure_stays_on_welcome_screen_and_warns(
    mock_list, mock_filter, mock_load, mock_system, mock_fda, qapp
):
    """Toujours pas détectée : jamais un clic silencieusement ignoré (§5) --
    reste sur l'écran de bienvenue et affiche le message dédié."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    window._fda_screen.recheck_requested.emit()

    assert window._root_stack.currentWidget() is window._fda_screen
    assert window._fda_screen._still_not_detected_label.isVisible() is True


@patch("r36s_studio.gui.main_window.elevate.has_full_disk_access", return_value=False)
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.subprocess.run")
def test_fda_welcome_screen_open_settings_opens_the_same_settings_pane(
    mock_run, mock_list, mock_filter, mock_load, mock_system, mock_fda, qapp
):
    """Réutilise exactement le même lien profond que la fenêtre Aide
    (`HelpDialog`, §3) -- une seule source de vérité pour ce panneau."""
    from r36s_studio.gui.main_window import _MACOS_FULL_DISK_ACCESS_SETTINGS_URL

    window = MainWindow()

    window._fda_screen.open_settings_requested.emit()

    mock_run.assert_called_once_with(["open", _MACOS_FULL_DISK_ACCESS_SETTINGS_URL], check=True)


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_flow_requires_confirmation_before_worker_starts(mock_list, mock_filter, mock_detect, mock_load, qapp):
    """Firmware par défaut (`AppConfig()`) mocké explicitement -- sans quoi
    ce test dépend du vrai fichier de configuration de la machine qui lance
    la suite (§8, même principe que `real_fda_probe`). `--eject-after` est
    désormais attendu pour tout flash mode expert, quel que soit le
    firmware (§4.6, constaté en usage réel au-delà du seul cas Android) --
    ce que ce test vérifie n'est pas cette liste précise mais que le worker
    ne démarre qu'après la confirmation explicite (§2 règle 6)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.flash_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        with patch(
            "r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")
        ):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

        # Le flash écrit sur le périphérique : confirmation obligatoire.
        assert window._confirm_dialog.isVisible() is True
        runner_class.assert_not_called()

        window._confirm_dialog._checkbox.setChecked(True)
        window._confirm_dialog.confirmed.emit()

        assert window._confirm_dialog.isVisible() is False

    argv = runner_class.instances[0].argv
    assert argv == ["flash", "--image", "/tmp/sd.img", "--device", "/dev/fake-disk-test-3", "--eject-after"]


# --- une seule autorisation macOS pour tout le parcours (§5 mode assisté) --
#
# Correctif d'un comportement observé en usage réel : le parcours guidé
# redemandait l'invite mot de passe à chaque étape élevée. `MainWindow`
# possède désormais une seule `MacosAuthorizationSession`, créée au premier
# besoin, réutilisée par tous les `WorkerRunner` suivants.


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.sys")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Linux")
def test_macos_auth_session_is_none_outside_macos(mock_system, mock_sys, mock_list, mock_filter, qapp):
    mock_sys.frozen = True
    window = MainWindow()

    assert window._get_or_create_macos_auth_session() is None


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.sys")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
def test_macos_auth_session_is_none_in_dev_mode(mock_system, mock_sys, mock_list, mock_filter, qapp):
    """En développement (`sys.frozen` absent), le worker élevé passe par
    `osascript`, qui ne consomme aucune `AuthorizationRef` -- pas la peine
    d'en créer une (et ça éviterait une invite mot de passe superflue
    pendant le développement)."""
    del mock_sys.frozen  # simule l'attribut absent, comme en dev réel
    window = MainWindow()

    assert window._get_or_create_macos_auth_session() is None


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.elevate.MacosAuthorizationSession")
@patch("r36s_studio.gui.main_window.sys")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
def test_macos_auth_session_created_once_and_reused(mock_system, mock_sys, mock_session_class, mock_list, mock_filter, qapp):
    mock_sys.frozen = True
    window = MainWindow()

    first = window._get_or_create_macos_auth_session()
    second = window._get_or_create_macos_auth_session()

    mock_session_class.assert_called_once()
    assert first is second


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.elevate.MacosAuthorizationSession", side_effect=OSError("indisponible"))
@patch("r36s_studio.gui.main_window.sys")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
def test_macos_auth_session_falls_back_to_none_on_creation_failure(mock_system, mock_sys, mock_session_class, mock_list, mock_filter, qapp):
    mock_sys.frozen = True
    window = MainWindow()

    assert window._get_or_create_macos_auth_session() is None


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.elevate.MacosAuthorizationSession")
@patch("r36s_studio.gui.main_window.sys")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
def test_close_event_closes_the_macos_auth_session(mock_system, mock_sys, mock_session_class, mock_list, mock_filter, qapp):
    mock_sys.frozen = True
    window = MainWindow()
    session = window._get_or_create_macos_auth_session()

    window.close()

    session.close.assert_called_once()


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_close_event_without_a_macos_auth_session_does_not_raise(mock_list, mock_filter, qapp):
    window = MainWindow()

    window.close()  # ne doit pas lever, même sans session créée


# --- fermeture pendant qu'un worker élevé tourne encore (§2) ---------------
#
# Bug corrigé, constaté sur du vrai matériel : fermer la fenêtre pendant
# qu'une opération élevée tournait encore laissait le worker orphelin --
# PID survivant, verrous de fichiers maintenus (y compris, dans le pire des
# cas, sur la carte SD elle-même en cours d'écriture -- un risque réel, pas
# seulement une gêne pour reconstruire le binaire). `self._runner` ne
# redevient jamais `None` une fois une opération terminée (seulement
# réaffecté au worker suivant) -- ces tests vérifient donc que `closeEvent`
# se base bien sur `LogPanel.is_operation_active()`, pas sur `self._runner
# is not None` seul, pour ne jamais agir sur un worker déjà terminé depuis
# longtemps.


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_close_event_leaves_a_finished_runner_alone(mock_list, mock_filter, mock_load, qapp):
    """`self._runner` pointe encore vers le worker de la toute dernière
    opération, déjà terminée depuis longtemps (jamais remis à `None`) --
    `LogPanel.is_operation_active()` vaut alors `False` (`finish_success`/
    `finish_error` déjà passés), `closeEvent` ne doit rien lui faire."""
    window = MainWindow()
    runner = MagicMock()
    window._runner = runner

    window.close()

    runner.cancel.assert_not_called()
    runner.force_kill.assert_not_called()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_close_event_force_kills_worker_that_never_responds_to_cancel(mock_list, mock_filter, mock_load, qapp):
    """Le worker ne s'arrête jamais tout seul (`process.poll()` reste
    `None` -- toujours actif) -- après le court délai de grâce, `closeEvent`
    doit forcer l'arrêt plutôt que de laisser un worker (et, sous Windows,
    tout sous-processus PowerShell qu'il aurait lui-même lancé) orphelin."""
    window = MainWindow()
    window._log_panel.start_operation("Test")
    runner = MagicMock()
    process = MagicMock()
    process.poll.return_value = None
    runner._process = process
    window._runner = runner

    with patch("r36s_studio.gui.main_window.time.sleep"), patch(
        "r36s_studio.gui.main_window.time.monotonic", side_effect=[0.0, 0.1, 0.2, 3.0]
    ):
        window.close()

    runner.cancel.assert_called_once()
    runner.force_kill.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_close_event_skips_force_kill_once_cancel_succeeds_quickly(mock_list, mock_filter, mock_load, qapp):
    """L'annulation coopérative a le temps d'aboutir avant le délai de
    grâce (`process.poll()` renvoie un vrai code de sortie) -- jamais
    besoin de forcer l'arrêt dans ce cas, l'écriture en cours a pu se
    terminer/s'annuler proprement."""
    window = MainWindow()
    window._log_panel.start_operation("Test")
    runner = MagicMock()
    process = MagicMock()
    process.poll.return_value = 0
    runner._process = process
    window._runner = runner

    with patch("r36s_studio.gui.main_window.time.sleep"), patch(
        "r36s_studio.gui.main_window.time.monotonic", side_effect=[0.0, 0.1]
    ):
        window.close()

    runner.cancel.assert_called_once()
    runner.force_kill.assert_not_called()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_close_event_terminates_partition_job_runner_too(mock_list, mock_filter, mock_load, qapp):
    """`self._runner` peut aussi être un `PartitionJobRunner` (étapes A/B/D/
    E, sans élévation, §4.4) -- pas de `_process`/`force_kill` à sa
    disposition (ni orphelin de sous-processus possible, un QThread meurt
    avec le process principal), mais l'annulation coopérative reste
    appelée sans lever, `force_kill` manquant simplement ignoré."""
    window = MainWindow()
    window._log_panel.start_operation("Test")
    runner = MagicMock(spec=["cancel"])  # ni _process, ni force_kill
    window._runner = runner

    window.close()  # ne doit pas lever

    runner.cancel.assert_called_once()


# --- repli élevé pour le montage forcé d'une carte GPT/EFI (§4.4) ----------
#
# Confirmé sur du vrai matériel : le montage forcé lui-même (`mount -t
# msdos`, locate.py) nécessite les droits administrateur. `MainWindow`
# installe un point d'extension auprès de `locate.py` (`set_privileged_
# mount_hook`) qui réutilise le même mécanisme d'élévation que backup/flash.


@patch("r36s_studio.gui.main_window.set_privileged_mount_hook")
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
def test_installs_privileged_mount_hook_on_macos(mock_system, mock_list, mock_filter, mock_set_hook, qapp):
    window = MainWindow()

    mock_set_hook.assert_called_once_with(window._mount_boot_privileged)


@patch("r36s_studio.gui.main_window.set_privileged_mount_hook")
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.platform.system", return_value="Linux")
def test_does_not_install_privileged_mount_hook_outside_macos(mock_system, mock_list, mock_filter, mock_set_hook, qapp):
    """Linux (`pkexec`/`sudo`) et Windows (UAC) n'ont pas cet équivalent
    léger dans ce squelette -- `locate.py` retombe sur son comportement
    non élevé, comme avant ce correctif (§3)."""
    MainWindow()

    mock_set_hook.assert_not_called()


@patch("r36s_studio.gui.main_window.elevate.run_privileged_mount", return_value=True)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.sys")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
def test_mount_boot_privileged_delegates_to_elevate_without_a_session_in_dev_mode(
    mock_system, mock_sys, mock_list, mock_filter, mock_run_mount, qapp
):
    del mock_sys.frozen  # simule l'attribut absent, comme en dev réel
    window = MainWindow()

    result = window._mount_boot_privileged("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")

    mock_run_mount.assert_called_once_with(
        "/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test", auth_ref=None
    )
    assert result is True


@patch("r36s_studio.gui.main_window.elevate.run_privileged_mount", return_value=True)
@patch("r36s_studio.gui.main_window.elevate.MacosAuthorizationSession")
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.sys")
@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
def test_mount_boot_privileged_reuses_the_shared_macos_auth_session(
    mock_system, mock_sys, mock_list, mock_filter, mock_session_class, mock_run_mount, qapp
):
    """Même autorisation qu'un `WorkerRunner` (backup/flash) -- jamais une
    invite mot de passe séparée pour le montage forcé."""
    mock_sys.frozen = True
    window = MainWindow()
    session = window._get_or_create_macos_auth_session()

    window._mount_boot_privileged("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")

    mock_run_mount.assert_called_once_with(
        "/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test", auth_ref=session.auth_ref
    )


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_two_worker_operations_share_the_same_macos_auth_session(mock_list, mock_filter, mock_detect, qapp):
    """Enchaîne backup puis flash (deux opérations élevées séparées, comme
    le ferait un utilisateur en mode expert) et vérifie que le second
    `WorkerRunner` reçoit exactement la même session que le premier --
    coeur du correctif : une seule invite mot de passe pour les deux."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class), patch(
        "r36s_studio.gui.main_window.platform.system", return_value="Darwin"
    ), patch("r36s_studio.gui.main_window.sys") as mock_sys, patch(
        "r36s_studio.gui.main_window.elevate.MacosAuthorizationSession"
    ) as mock_session_class:
        mock_sys.frozen = True
        window = MainWindow()

        window._home.backup_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()
        with patch("r36s_studio.gui.screens.QFileDialog.getSaveFileName", return_value=("/tmp/out.img", "")):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

        window._home.flash_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()
        with patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())
        window._confirm_dialog._checkbox.setChecked(True)
        window._confirm_dialog.confirmed.emit()

    mock_session_class.assert_called_once()  # une seule AuthorizationRef créée pour les deux
    assert len(runner_class.instances) == 2
    assert (
        runner_class.instances[0].macos_auth_session
        is runner_class.instances[1].macos_auth_session
        is mock_session_class.return_value
    )


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_system_backup_worker_shares_the_same_macos_auth_session_as_flash(mock_list, mock_filter, mock_detect, qapp):
    """Vérifie que la sauvegarde système, une fois lancée (fichier choisi,
    pas seulement l'estimation), s'élève exactement comme backup/flash --
    même session d'autorisation, jamais une invite séparée (§4.3, point 3
    du rapport : « vérifie que la sauvegarde elle-même... s'élève
    correctement »)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class), patch(
        "r36s_studio.gui.main_window.platform.system", return_value="Darwin"
    ), patch("r36s_studio.gui.main_window.sys") as mock_sys, patch(
        "r36s_studio.gui.main_window.elevate.MacosAuthorizationSession"
    ) as mock_session_class:
        mock_sys.frozen = True
        window = MainWindow()

        # La sauvegarde système passe par l'estimation d'abord -- appelée
        # directement ici (déjà couverte séparément ci-dessus), seul le
        # lancement réel du worker nous intéresse pour ce test.
        window._mode = "backup_system"
        window._device = device
        window._file_path = "/tmp/systeme.img"
        window._start_worker()

        window._home.flash_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()
        with patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())
        window._confirm_dialog._checkbox.setChecked(True)
        window._confirm_dialog.confirmed.emit()

    mock_session_class.assert_called_once()
    assert len(runner_class.instances) == 2
    assert runner_class.instances[0].argv[0] == "backup"
    assert "--system-only" in runner_class.instances[0].argv
    assert (
        runner_class.instances[0].macos_auth_session
        is runner_class.instances[1].macos_auth_session
        is mock_session_class.return_value
    )


# --- format d'image invalide (§5, imaging/image_source.py) : rejeté avant --
# --- même la fenêtre Confirmation, sans jamais demander l'élévation --------


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_choosing_a_seven_zip_file_for_flash_blocks_confirm_dialog(
    mock_list, mock_filter, mock_detect, mock_warning, qapp, tmp_path
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    seven_zip_path = tmp_path / "ArkOS.img"  # renommé -- détecté par octets d'en-tête
    seven_zip_path.write_bytes(bytes.fromhex("377ABCAF271C") + b"\x00" * 20)

    window = MainWindow()
    window._home.flash_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()
    window._file_dialog.file_chosen.emit(str(seven_zip_path))

    assert window._confirm_dialog.isVisible() is False
    mock_warning.assert_called_once()
    assert "archive 7-Zip" in mock_warning.call_args[0][2]


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_choosing_an_unsupported_format_for_flash_blocks_confirm_dialog(
    mock_list, mock_filter, mock_detect, mock_warning, qapp, tmp_path
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    zip_path = tmp_path / "sd.img.zip"
    zip_path.write_bytes(b"PK\x03\x04" + b"\x00" * 20)

    window = MainWindow()
    window._home.flash_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()
    window._file_dialog.file_chosen.emit(str(zip_path))

    assert window._confirm_dialog.isVisible() is False
    mock_warning.assert_called_once()
    assert "pas une image utilisable" in mock_warning.call_args[0][2]


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_confirm_dialog_cancel_never_starts_the_worker(mock_list, mock_filter, mock_detect, qapp):
    """Annuler ferme simplement la fenêtre de confirmation (§5, refonte
    navigation) -- plus de retour à une fenêtre Fichier chaînée, juste un
    abandon qui laisse la vue principale inchangée derrière."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.flash_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()
        window._file_dialog.file_chosen.emit("/tmp/sd.img")
        assert window._confirm_dialog.isVisible() is True

        window._confirm_dialog.close()

    assert window._confirm_dialog.isVisible() is False
    runner_class.assert_not_called()


# --- « Remettre la carte à zéro » (§4.3 bis, mode expert uniquement) -------
# Sous « Par sécurité », à côté des sauvegardes -- jamais dans le parcours
# assisté. Pas de fichier à choisir : carte -> étiquette (ResetCardLabel
# Dialog) -> confirmation obligatoire (§2 n°6) -> worker.


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_reset_card_flow_goes_from_device_to_label_to_confirmation(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window._home.reset_card_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    assert window._file_dialog.isVisible() is False  # jamais de fichier à choisir
    assert window._reset_card_label_dialog.isVisible() is True
    assert window._reset_card_label_dialog._label_edit.text() == "SDCARD"  # valeur par défaut simple

    window._reset_card_label_dialog._label_edit.setText("MACARTE")
    window._reset_card_label_dialog._continue_button.click()

    assert window._reset_card_label_dialog.isVisible() is False
    assert window._confirm_dialog.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_reset_card_start_worker_builds_the_expected_argv(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "reset_card"
    window._reset_card_label = "MACARTE"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert runner_class.instances[0].argv == [
        "reset-card",
        "--device",
        window._device.path,
        "--label",
        "MACARTE",
        "--filesystem",
        "exfat",
    ]


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_reset_card_never_gets_eject_after_flag(mock_list, mock_filter, mock_load, qapp):
    """`--eject-after` existe pour un risque propre au flash d'un
    firmware (Windows propose de formater des partitions illisibles,
    §4.6) -- une partition exFAT neuve ne pose pas ce problème."""
    window = MainWindow()
    window._device = _make_device()
    window._mode = "reset_card"
    window._reset_card_label = "SDCARD"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--eject-after" not in runner_class.instances[0].argv


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_reset_card_fat32_choice_is_passed_to_the_worker_and_persisted(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    """Cas réel qui motive ce choix : une console (SF3000HD) qui ne lit
    que le FAT32, rendue inutilisable par le formatage exFAT jusque-là
    systématique (§4.3 bis)."""
    window = MainWindow()
    window._device = _make_device()
    window._mode = "reset_card"

    window._on_reset_card_label_chosen("MACARTE", "fat32")

    assert window._reset_card_filesystem == "fat32"
    assert window._app_config.reset_card_filesystem == "fat32"
    mock_save.assert_called_once_with(window._app_config)

    runner_class = _mock_runner_class()
    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert runner_class.instances[0].argv == [
        "reset-card",
        "--device",
        window._device.path,
        "--label",
        "MACARTE",
        "--filesystem",
        "fat32",
    ]


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_reset_card_fat32_infeasible_warns_and_never_opens_confirm_dialog(
    mock_list, mock_filter, mock_load, mock_save, mock_warning, qapp
):
    """Demande explicite : « si le FAT32 s'avère impossible sur une taille
    donnée, le dire clairement avant de lancer l'opération, jamais après »
    -- ici, avant même la fenêtre Confirmation (§4.3 bis)."""
    window = MainWindow()
    window._device = _make_device(size_bytes=20 * 1024 * 1024)  # bien en dessous du minimum FAT32
    window._mode = "reset_card"

    window._on_reset_card_label_chosen("MACARTE", "fat32")

    assert window._confirm_dialog.isVisible() is False
    mock_warning.assert_called_once()
    mock_save.assert_not_called()  # rien à mémoriser, le choix n'a pas abouti


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_on_step_progress_forwards_to_log_panel(mock_list, mock_filter, qapp):
    """Progression par étapes réelles (§2 n°5, §4.3 bis) -- distincte de
    `_on_progress` (bytes/débit), pour une opération qui n'a rien à
    copier."""
    window = MainWindow()

    window._on_step_progress(2, 4, "Formatage exFAT…")

    assert window._log_panel._bar.value() == 50
    assert window._log_panel._speed_label.text() == "Formatage exFAT…"


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_reset_card_start_worker_connects_step_progress_signal(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "reset_card"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    runner_class.instances[0].step_progress.connect.assert_called_once_with(window._on_step_progress)


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_reset_card_success_hides_eject_button_since_already_ejected(
    mock_list, mock_filter, mock_load, qapp
):
    """La remise à zéro éjecte déjà automatiquement à sa dernière étape
    (§4.3 bis, suivie par la barre de progression) -- un bouton en plus
    serait redondant, même principe qu'un flash Android (§4.6)."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._device = _make_device()
    window._mode = "reset_card"

    window._on_worker_finished(True)

    log_text = window._log_panel._log_view.toPlainText()
    assert "remise à zéro" in log_text
    assert window._log_panel._eject_button.isVisible() is False


# --- câblage réel signal/slot, pas un WorkerRunner mocké --------------------
#
# Toutes les autres traversées du flash/backup passent par `_mock_runner_class`
# (un `MagicMock`) : `.progress` y est lui-même un `MagicMock`, donc
# `.connect(...)` ne fait qu'enregistrer un appel -- aucun signal Qt réel
# n'est jamais émis. Une régression du câblage (mauvais nom de méthode,
# signature de slot qui ne correspond plus au signal, connexion oubliée)
# passerait entièrement inaperçue dans ces tests. Celui-ci utilise un vrai
# `WorkerRunner` (vrai `QObject`, vrai `Signal("qint64", "qint64", float)`)
# et vérifie que le journal de bord de `MainWindow` se met à jour quand ce
# signal est réellement émis -- seule `elevate.launch_elevated_worker` est
# mockée, pour ne lancer aucune élévation ni sous-processus réel.


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_progress_reaches_log_panel_through_real_worker_runner(
    mock_list, mock_filter, mock_detect, mock_launch, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_launch.return_value = MagicMock(poll=MagicMock(return_value=None))

    window = MainWindow()
    window._home.flash_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    with patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")):
        window._file_dialog._browse()
    window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    window._confirm_dialog._checkbox.setChecked(True)
    window._confirm_dialog.confirmed.emit()

    assert isinstance(window._runner, WorkerRunner)  # pas un mock : le vrai câblage Qt est en jeu
    assert window._home._tiles["flash"].isEnabled() is False  # occupé pendant l'opération

    window._runner.progress.emit(50, 200, 12_000_000.0)

    assert window._log_panel._bar.value() == 25  # 50/200 = 25 %
    assert "12.0" in window._log_panel._speed_label.text()


# --- bug corrigé : débordement d'entier 32 bits sur les tailles en octets --
#
# Constaté en conditions réelles (flash d'une carte de 32 Go) : `Signal(int,
# int, float)` mappe `int` sur un entier C++ 32 bits (~2,1 milliards max),
# dépassé par n'importe quel compte d'octets au-delà de 2 Go. PySide6 ne
# lève alors aucune exception Python -- il échoue silencieusement à livrer
# le signal (`libshiboken: Overflow`, `OverflowError` côté C++), ce qui se
# manifestait côté GUI par le message trompeur `AttributeError: Slot
# '...(int,int,double)' not found`, comme si le slot n'existait pas. Les
# tests précédents (50, 200 octets) ne pouvaient pas l'attraper : trop
# petits pour dépasser 2^31. Corrigé en déclarant `Signal("qint64",
# "qint64", float)` (`worker_runner.py`/`partition_runner.py`) et le
# `@Slot` assorti sur `MainWindow._on_progress`.


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_progress_survives_byte_counts_beyond_32_bit_int(
    mock_list, mock_filter, mock_detect, mock_launch, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_launch.return_value = MagicMock(poll=MagicMock(return_value=None))

    window = MainWindow()
    window._home.flash_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    with patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")):
        window._file_dialog._browse()
    window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    window._confirm_dialog._checkbox.setChecked(True)
    window._confirm_dialog.confirmed.emit()

    total_32gb = 34_359_738_368  # 32 Go, très au-delà de 2**31 - 1 (~2,1 milliards)
    assert total_32gb > 2**31

    window._runner.progress.emit(total_32gb // 2, total_32gb, 12_000_000.0)

    assert window._log_panel._bar.value() == 50
    assert window._last_progress_bytes == total_32gb // 2


@patch("r36s_studio.gui.partition_runner.copy_games")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_copy_games_progress_reaches_log_panel_through_real_cross_thread_signal(
    mock_list, mock_filter, mock_detect, mock_copy_games, qapp
):
    """`PartitionJobRunner` est un vrai `QThread` (contrairement à
    `WorkerRunner`, qui reste sur le thread Qt principal via `QTimer`) :
    son signal `progress` traverse donc réellement une frontière de
    thread jusqu'à `MainWindow._on_progress` -- la connexion devient une
    file d'attente Qt (`Qt.QueuedConnection` automatique), le seul endroit
    de ce projet où une régression de câblage se manifesterait
    différemment qu'en même thread. À couvrir spécifiquement."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_copy_games.side_effect = lambda device, source_path, on_progress=None, should_cancel=None: on_progress(
        ProgressEvent(done=30, total=100, speed=2_000_000.0)
    )

    window = MainWindow()
    window._mode = "copy_games"
    window._device = device
    window._file_path = "/tmp/games"
    window._start_worker()

    assert window._runner.wait(2000)  # laisse le vrai QThread se terminer
    for _ in range(20):
        qapp.processEvents()  # livre les signaux mis en file d'attente entre threads

    assert window._log_panel._bar.value() == 30


@patch("r36s_studio.gui.partition_runner.extract_easyroms")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_easyroms_progress_survives_byte_counts_beyond_32_bit_int_cross_thread(
    mock_list, mock_filter, mock_detect, mock_extract_easyroms, qapp
):
    """Même bug que `test_flash_progress_survives_byte_counts_beyond_32_bit_int`,
    mais sur le seul chemin réellement inter-thread du projet
    (`PartitionJobRunner`, un vrai `QThread`) -- une EASYROMS de plusieurs
    dizaines de Go dépasse tout aussi facilement 2**31 octets."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    total_32gb = 34_359_738_368  # 32 Go, très au-delà de 2**31 - 1 (~2,1 milliards)
    assert total_32gb > 2**31
    mock_extract_easyroms.side_effect = (
        lambda device, source_path, on_progress=None, should_cancel=None: on_progress(
            ProgressEvent(done=total_32gb // 2, total=total_32gb, speed=2_000_000.0)
        )
    )

    window = MainWindow()
    window._mode = "extract_easyroms"
    window._device = device
    window._file_path = "/tmp/EASYROMS_archive"
    window._start_worker()

    assert window._runner.wait(2000)
    for _ in range(20):
        qapp.processEvents()

    assert window._log_panel._bar.value() == 50
    assert window._last_progress_bytes == total_32gb // 2


# --- colonne gauche désactivée pendant une opération (§5, refonte nav.) ----


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_start_worker_disables_home_and_reenables_on_finish(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
        for row in window._home._tiles.values():
            assert row.isEnabled() is False
        assert window._home._backup_row.isEnabled() is False

        window._on_worker_finished(True)

    for row in window._home._tiles.values():
        assert row.isEnabled() is True
    assert window._home._backup_row.isEnabled() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_start_worker_disables_both_mode_switch_buttons_and_reenables_on_finish(mock_list, mock_filter, qapp):
    """Changer de mode en plein flash ou en pleine copie laisserait un job
    orphelin (§5 mode assisté) -- les deux boutons de bascule (Mode
    assisté sur HomeScreen, Mode expert sur AssistedLandingScreen) doivent
    être désactivés pendant toute opération disque, dans les deux sens."""
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
        assert window._home._assisted_mode_button.isEnabled() is False
        assert window._assisted_landing._expert_button.isEnabled() is False

        window._on_worker_finished(True)

    assert window._home._assisted_mode_button.isEnabled() is True
    assert window._assisted_landing._expert_button.isEnabled() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_start_worker_starts_and_stops_console_stage_activity(mock_list, mock_filter, qapp):
    """§5 : le terminal d'activité de l'écran de la console repart vierge
    au début d'une opération disque (`start_activity`) et revient à un
    curseur seul à la fin (`stop_activity`). Correction de conception,
    confirmée sur du vrai matériel : ce terminal avait été soupçonné (puis
    retiré) d'un ralentissement de la sauvegarde système d'un facteur dix
    -- la cause réelle était une carte SD d'origine de console non
    reconnue (~6 Mo/s contre ~88 Mo/s pour une SanDisk), pas ce code."""
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    window._console_stage = MagicMock()
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
        window._console_stage.start_activity.assert_called_once()
        window._console_stage.stop_activity.assert_not_called()

        window._on_worker_finished(True)

    window._console_stage.stop_activity.assert_called_once()


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_on_progress_appends_a_real_activity_line_to_the_console_terminal(mock_list, mock_filter, qapp):
    """Terminal d'activité disque de l'écran de la console (§5) : une
    ligne par événement de progression réellement émis par
    `copy_range`/`copy_tree` -- jamais une ligne inventée (§2 règle 5)."""
    window = MainWindow()
    window._console_stage = MagicMock()
    window._last_progress_bytes = 4 * 1024 * 1024

    window._on_progress(8 * 1024 * 1024, 32 * 1024 * 1024, 18_400_000.0)

    window._console_stage.append_line.assert_called_once()
    line = window._console_stage.append_line.call_args[0][0]
    assert line.startswith("0x")
    assert "4.0 Mo" in line  # le bloc : delta depuis le dernier événement
    assert window._last_progress_bytes == 8 * 1024 * 1024


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_on_progress_without_console_stage_still_updates_log_panel(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._console_stage = None

    window._on_progress(100, 1000, 50.0)

    assert window._last_progress_bytes == 100


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_on_progress_without_console_stage_still_updates_log_panel(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._console_stage = None

    window._on_progress(100, 1000, 50.0)

    assert window._last_progress_bytes == 100


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_cancel_requested_calls_runner_cancel(mock_list, mock_filter, qapp):
    window = MainWindow()
    fake_runner = MagicMock()
    window._runner = fake_runner

    window._on_cancel_requested()

    fake_runner.cancel.assert_called_once()


# --- résultats dans le journal de bord, pas un écran séparé (§5) -----------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_success_logs_message_and_hides_eject_for_flash(mock_list, mock_filter, mock_load, qapp):
    """Constaté en usage réel : tout flash mode expert déclenche
    potentiellement une boîte Windows « Vous devez formater le disque »
    (§4.6, pas seulement Android) -- déjà éjectée par `--eject-after`, donc
    le bouton Éjecter du succès serait redondant."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché (MainWindow, pas un descendant)
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/sd.img"

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is False
    assert "prête" in window._log_panel._log_view.toPlainText()


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_error_logs_cancelled_message(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_error("CANCELLED", "Sauvegarde annulée après 1024 octets")
    window._on_worker_finished(False)

    assert "annulée" in window._log_panel._log_view.toPlainText()


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_requested_runs_eject_command_via_elevated_worker(mock_list, mock_filter, qapp):
    r"""Bug corrigé, confirmé sur du vrai matériel : ouvrir
    `\\.\PhysicalDriveN` pour éjecter exige l'élévation sur Windows,
    exactement comme l'écriture brute -- le bouton du journal ne doit donc
    plus jamais appeler `partitions.eject.eject` directement dans le
    processus GUI (`ERROR_ACCESS_DENIED`), mais passer par un worker élevé
    dédié, comme `backup`/`flash` (§4.3/§4.4)."""
    window = MainWindow()
    window._device = _make_device(path="/dev/fake-disk-test-3")
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._on_eject_requested()

    assert runner_class.instances[0].argv == ["eject", "--device", "/dev/fake-disk-test-3"]


# --- colonne gauche : six étapes toujours visibles, statut informatif ------
# (§4.5) ----------------------------------------------------------------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_detects_single_card_and_annotates_home(mock_list, mock_filter, mock_detect, mock_load, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    status = _all_status(StepStatus.AVAILABLE)
    mock_detect.return_value = status
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(device)
    # Les six lignes restent visibles quel que soit le statut (§4.5).
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_with_no_card_still_shows_all_six_tiles(mock_list, mock_filter, mock_detect, mock_load, qapp):
    mock_list.return_value = []
    mock_filter.return_value = []
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(None)
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.NOT_RELEVANT))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_no_card_disables_backup_rows_but_not_the_six_tiles(mock_list, mock_filter, mock_detect, mock_load, qapp):
    """Bug rapporté : la sauvegarde système sans les jeux restait
    lançable alors que la carte venait d'être éjectée (bandeau « Aucune
    carte détectée »). « Par sécurité » exige une carte, contrairement
    aux six étapes lettrées (toujours cliquables par principe, §4.5)."""
    window = MainWindow()
    window.show()

    assert window._home._backup_row.isEnabled() is False
    assert window._home._backup_system_row.isEnabled() is False
    for tile in window._home._tiles.values():
        assert tile.isEnabled() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_single_card_enables_backup_rows(mock_list, mock_filter, mock_detect, mock_load, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()

    assert window._home._backup_row.isEnabled() is True
    assert window._home._backup_system_row.isEnabled() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.NOT_RELEVANT))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_multiple_candidate_cards_keep_backup_rows_enabled(mock_list, mock_filter, mock_detect, mock_load, qapp):
    """Plusieurs cartes candidates à la fois (§4.2) : ambigu quant à
    laquelle, mais il y a bien au moins une carte -- choisir laquelle
    reste possible via la fenêtre Choix de la carte, contrairement à
    zéro carte du tout."""
    devices = [_make_device(path="/dev/fake-disk-test-1"), _make_device(path="/dev/fake-disk-test-2")]
    mock_list.return_value = devices
    mock_filter.return_value = devices

    window = MainWindow()
    window.show()

    assert window._home._backup_row.isEnabled() is True
    assert window._home._backup_system_row.isEnabled() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_with_multiple_cards_passes_none_to_detection(mock_list, mock_filter, mock_detect, mock_load, qapp):
    """Cas non couvert par une carte unique : plusieurs cartes candidates
    -- `detect_workflow_status` reçoit `None` (aucune mise en avant
    possible), mais les six lignes restent affichées normalement."""
    devices = [_make_device(path="/dev/fake-disk-test-3"), _make_device(path="/dev/fake-disk-test-4")]
    mock_list.return_value = devices
    mock_filter.return_value = devices
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(None)
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_home_refresh_requested_re_runs_detection(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_detect.return_value = _all_status(StepStatus.AVAILABLE)
    window = MainWindow()
    mock_detect.reset_mock()

    window._home.refresh_requested.emit()

    mock_detect.assert_called_once_with(device)


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_finished_re_runs_detection(mock_list, mock_filter, mock_detect, qapp):
    """La carte a changé d'état après une opération (flash, injection...) --
    la détection doit se relancer automatiquement, sans qu'il y ait de
    bouton "retour à l'accueil" à cliquer (§5, refonte navigation : plus
    d'écran Résultat séparé avec un tel bouton, la vue est déjà là)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_detect.return_value = _all_status(StepStatus.AVAILABLE)
    window = MainWindow()
    window._mode = "flash"
    window._device = device
    window._file_path = "/tmp/sd.img"
    mock_detect.reset_mock()

    mock_detect.return_value = _all_status(StepStatus.DONE)
    window._on_worker_finished(True)

    mock_detect.assert_called_once_with(device)


# --- fenêtre Aide (macOS uniquement, §3) ------------------------------------


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
@patch("r36s_studio.gui.screens.platform.system", return_value="Darwin")
def test_home_help_requested_opens_help_dialog(mock_platform, mock_list, mock_filter, mock_detect, qapp):
    mock_list.return_value = []
    mock_filter.return_value = []
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()

    window._home.help_requested.emit()

    assert window._help_dialog.isVisible() is True


@patch("r36s_studio.gui.main_window.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.main_window.subprocess.run")
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_help_dialog_open_settings_opens_full_disk_access_pane(
    mock_list, mock_filter, mock_detect, mock_run, mock_system, qapp
):
    """`platform.system` doit être mocké ici comme ailleurs (§ diagnostic CI
    Windows) : ce test mocke aussi `subprocess.run` (même référence de
    module partout, tests/conftest.py) pour vérifier l'appel `open` --
    laissé non mocké, `platform.system()` non mocké appellerait pour de
    vrai `subprocess.run('ver', ...)` sous Windows, qui recevrait alors ce
    même mock et lui renverrait un `MagicMock` là où l'implémentation
    interne de `platform` attend une vraie chaîne à analyser par regex :
    `TypeError: expected string or bytes-like object, got 'MagicMock'`."""
    mock_list.return_value = []
    mock_filter.return_value = []
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()

    window._help_dialog.open_settings_requested.emit()

    mock_run.assert_called_once_with(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"], check=True
    )


# --- inject-boot / copy-games (étapes D/E) : PartitionJobRunner, archives --


@patch("r36s_studio.gui.main_window.archives.list_archives", return_value=["/tmp/R36S Studio/BOOT_x"])
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_inject_boot_flow_offers_existing_archive_and_uses_partition_runner(
    mock_list, mock_filter, mock_detect, mock_list_archives, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.inject_boot_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        mock_list_archives.assert_called_once_with("BOOT")
        assert window._file_dialog.isVisible() is True
        assert window._file_dialog._archive_list.count() == 1

        window._file_dialog._archive_list.setCurrentRow(0)
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    runner_class.assert_called_once_with("inject_boot", device, "/tmp/R36S Studio/BOOT_x", parent=window)
    runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.archives.list_archives", return_value=[])
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_copy_games_flow_falls_back_to_manual_browse_when_no_archives(
    mock_list, mock_filter, mock_detect, mock_list_archives, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.copy_games_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        mock_list_archives.assert_called_once_with("EASYROMS")

        with patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/games"):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    runner_class.assert_called_once_with("copy_games", device, "/tmp/games", parent=window)


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_copy_games_success_message_and_allows_eject(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window.show()
    window._mode = "copy_games"
    window._device = _make_device(display="Carte de Léo")

    window._on_worker_finished(True)

    assert "Carte de Léo" in window._log_panel._log_view.toPlainText()
    assert window._log_panel._eject_button.isVisible() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_success_never_allows_eject(mock_list, mock_filter, qapp):
    """La sauvegarde n'écrit que dans un fichier, jamais sur la carte
    (§5 point 6) -- rien à éjecter."""
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is False


# --- extract-boot / extract-easyroms (étapes A/B) : choix du dossier ------
#
# Régression corrigée : la destination était devenue un chemin généré
# automatiquement, sans que l'utilisateur puisse décider où son archive est
# enregistrée. La fenêtre Fichier est rétablie, avec un dossier par défaut
# (~/Documents/R36S Studio) que l'utilisateur peut accepter tel quel ou
# remplacer par n'importe quel emplacement -- seul le nom horodaté à
# l'intérieur reste automatique.


@patch("r36s_studio.gui.main_window.archives.default_archives_dir")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_shows_file_dialog_with_default_path_preselected(
    mock_list, mock_filter, mock_detect, mock_default_dir, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_default_dir.return_value = "/home/x/Documents/R36S Studio"

    window = MainWindow()
    window._home.extract_boot_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    assert window._file_dialog.isVisible() is True
    assert window._file_dialog._path_label.text() == "/home/x/Documents/R36S Studio"
    assert window._file_dialog._next_button.isEnabled() is True  # défaut déjà accepté


@patch("r36s_studio.gui.main_window.archives.new_archive_path")
@patch("r36s_studio.gui.main_window.archives.default_archives_dir", return_value="/home/x/Documents/R36S Studio")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_accepting_default_uses_it_as_base_dir(
    mock_list, mock_filter, mock_detect, mock_default_dir, mock_new_path, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_new_path.return_value = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.extract_boot_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        # L'utilisateur accepte simplement le défaut proposé.
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    from pathlib import Path

    mock_new_path.assert_called_once_with("BOOT", base_dir=Path("/home/x/Documents/R36S Studio"))
    runner_class.assert_called_once_with(
        "extract_boot", device, "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21", parent=window
    )


@patch("r36s_studio.gui.main_window.archives.new_archive_path")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_can_replace_default_with_external_drive(
    mock_list, mock_filter, mock_detect, mock_new_path, qapp
):
    """L'utilisateur peut remplacer le dossier proposé par n'importe quel
    autre emplacement, y compris un disque externe."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_new_path.return_value = "/Volumes/DisqueExterne/BOOT_2026-07-06_00-21"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.extract_boot_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        with patch(
            "r36s_studio.gui.screens.QFileDialog.getExistingDirectory",
            return_value="/Volumes/DisqueExterne",
        ):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    from pathlib import Path

    mock_new_path.assert_called_once_with("BOOT", base_dir=Path("/Volumes/DisqueExterne"))


@patch("r36s_studio.gui.main_window.archives.new_archive_path")
@patch("r36s_studio.gui.main_window.archives.default_archives_dir", return_value="/home/x/Documents/R36S Studio")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_easyroms_uses_easyroms_label(
    mock_list, mock_filter, mock_detect, mock_default_dir, mock_new_path, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_new_path.return_value = "/home/x/Documents/R36S Studio/EASYROMS_2026-07-06_00-21"

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", _mock_partition_runner_class()):
        window = MainWindow()
        window._home.extract_easyroms_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    from pathlib import Path

    mock_new_path.assert_called_once_with("EASYROMS", base_dir=Path("/home/x/Documents/R36S Studio"))


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_success_logs_archive_path_size_and_shows_reveal(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window.show()
    window._mode = "extract_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._last_progress_bytes = 12_582_912  # 12 Mo

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "ordinateur" in log_text
    assert "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in log_text
    assert "12.0 Mo" in log_text
    assert window._log_panel._reveal_button.isVisible() is True


# --- chemin de destination annoncé dès le début de la copie (§5 mode --------
# --- assisté) : un débutant qui ne le voit qu'au succès final n'a aucune --
# --- idée d'où va sa sauvegarde pendant que ça copie. --------------------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_extract_boot_logs_destination_path_at_start_not_only_at_end(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._mode = "extract_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._start_worker()

    log_text = window._log_panel._log_view.toPlainText()
    assert "Destination : /home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in log_text


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_extract_easyroms_logs_destination_path_at_start(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._mode = "extract_easyroms"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/EASYROMS_2026-07-06_00-25"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._start_worker()

    log_text = window._log_panel._log_view.toPlainText()
    assert "Destination : /home/x/Documents/R36S Studio/EASYROMS_2026-07-06_00-25" in log_text


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_inject_boot_does_not_log_a_destination_line(mock_list, mock_filter, mock_load, qapp):
    """La destination est ici une partition de la carte, pas un dossier de
    l'ordinateur -- pas la même confusion que pour les étapes A/B, donc pas
    la même annonce (§5 mode assisté, portée volontairement limitée aux
    étapes d'extraction)."""
    window = MainWindow()
    window._mode = "inject_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._start_worker()

    log_text = window._log_panel._log_view.toPlainText()
    assert "Destination :" not in log_text


@patch("r36s_studio.gui.main_window.reveal")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_reveal_requested_calls_reveal_with_archive_path(mock_list, mock_filter, mock_reveal, qapp):
    window = MainWindow()
    window._mode = "extract_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._on_worker_finished(True)

    window._log_panel._reveal_button.click()

    mock_reveal.assert_called_once_with("/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21")


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_inject_boot_success_logs_source_archive_path(mock_list, mock_filter, mock_load, qapp):
    """Étapes D/E : la même ligne indique quelle archive a servi de
    source, plutôt que « archive créée »."""
    window = MainWindow()
    window.show()
    window._mode = "inject_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"

    window._on_worker_finished(True)

    log_text = window._log_panel._log_view.toPlainText()
    assert "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in log_text
    assert window._log_panel._reveal_button.isVisible() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_success_shows_no_reveal_button(mock_list, mock_filter, qapp):
    """backup/flash ne manipulent pas de dossier d'archive -- rien à
    révéler."""
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_finished(True)

    assert window._log_panel._reveal_button.isVisible() is False


# --- eject (étape F) : immédiat, sans fenêtre Fichier ni opération ----------


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_flow_runs_via_elevated_worker_and_confirms_success(mock_list, mock_filter, mock_detect, qapp):
    """Bug corrigé, confirmé sur du vrai matériel : l'étape F appelait
    `partitions.eject.eject` directement dans le processus GUI -- échoue
    systématiquement sur Windows (élévation requise, §4.3/§4.4)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    window = MainWindow()
    window.show()
    window._home.eject_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._device_dialog._emit_chosen()
        assert runner_class.instances[0].argv == ["eject", "--device", device.path]
        window._on_perform_eject_finished(True, None, None)

    assert "retirée en toute sécurité" in window._log_panel._log_view.toPlainText()
    assert window._file_dialog.isVisible() is False  # étape F : aucune fenêtre Fichier


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_flow_logs_friendly_error_and_raw_detail_on_failure(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    window = MainWindow()
    window.show()
    window._home.eject_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._device_dialog._emit_chosen()
        window._on_perform_eject_finished(False, "EJECT_FAILED", "carte occupée")

    log_text = window._log_panel._log_view.toPlainText()
    assert "carte occupée" in log_text  # journal de bord : tout y va, plus de panneau Détails séparé (§5)


# --- messages d'erreur conviviaux + détail brut dans le journal (§5) -------


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_partition_not_found_error_logs_friendly_message_then_raw_detail(
    mock_list, mock_filter, qapp
):
    window = MainWindow()
    window.show()
    window._mode = "inject_boot"
    window._device = _make_device()

    window._on_worker_error("PARTITION_NOT_FOUND", "Partition « BOOT » introuvable sur /dev/fake-disk-test-3")
    window._on_worker_finished(False)

    lines = window._log_panel._log_view.toPlainText().splitlines()
    assert any("carte" in line.lower() and "/dev/fake-disk-test-3" not in line for line in lines)
    assert any("/dev/fake-disk-test-3" in line for line in lines)


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_unrecognized_error_code_falls_back_to_generic_friendly_message(mock_list, mock_filter, qapp):
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()

    window._on_worker_error("SOME_FUTURE_CODE", "détail technique quelconque")
    window._on_worker_finished(False)

    log_text = window._log_panel._log_view.toPlainText()
    assert "Une erreur est survenue" in log_text
    assert "détail technique quelconque" in log_text  # journal de bord : le détail brut suit quand même


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_macos_tcc_protected_folder_error_shows_dedicated_friendly_message(mock_list, mock_filter, qapp):
    """La détection élargie (worker_runner.py) ne sert à rien si le
    message dédié reste caché derrière le message générique -- vérifie
    qu'il apparaît bien dans le journal."""
    window = MainWindow()
    window.show()
    window._mode = "flash"
    window._device = _make_device()

    window._on_worker_error(
        "MACOS_TCC_PROTECTED_FOLDER",
        "[Errno 1] Operation not permitted: '/Users/x/Downloads/ArkOS.img.xz'",
    )
    window._on_worker_finished(False)

    log_text = window._log_panel._log_view.toPlainText()
    assert "dossier protégé" in log_text
    assert "/Users/x/Downloads" in log_text  # détail brut, en ligne suivante -- pas masqué (§5)


# --- mode assisté (§5 mode assisté) -----------------------------------------
#
# ui_mode (config.py) pilote l'écran affiché au lancement ; le mode assisté
# enchaîne 5 étapes (gui/wizard_flow.py, parcours de clonage) sur la même
# MainView que le mode expert (colonne gauche remplacée par WizardStepPanel).

from r36s_studio.gui.wizard_flow import WizardJob


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_default_startup_shows_assisted_landing_screen(mock_list, mock_filter, mock_detect, mock_load, qapp):
    window = MainWindow()

    assert window._root_stack.currentWidget() is window._assisted_landing


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_expert_ui_mode_startup_shows_main_view_with_home(mock_list, mock_filter, mock_detect, mock_load, qapp):
    window = MainWindow()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._home


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_expert_mode_button_from_landing_persists_config_and_shows_home(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()

    window._assisted_landing.expert_mode_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._home
    mock_save.assert_called_once()
    assert mock_save.call_args[0][0].ui_mode == "expert"


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_catalog_access_from_identify_result_dialog_switches_screen(
    mock_list, mock_filter, mock_detect, mock_load, qapp
):
    """Section « Consoles diverses » (consoles_diverses/, étape 1) --
    plus de tuile séparée dans l'accueil assisté (§5, correctif visuel :
    fusionnée dans « Identifier ma console »), l'accès au catalogue se
    fait désormais depuis l'écran de résultat de l'identification, jamais
    un changement de `ui_mode` (ce n'est pas un mode, juste une section
    indépendante)."""
    window = MainWindow()

    window._identify_result_dialog.catalog_requested.emit()

    assert window._root_stack.currentWidget() is window._consoles_diverses_screen


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_consoles_diverses_button_from_home_switches_screen_and_back_returns(
    mock_list, mock_filter, mock_detect, mock_load, qapp
):
    window = MainWindow()

    window._home.consoles_diverses_requested.emit()
    assert window._root_stack.currentWidget() is window._consoles_diverses_screen

    window._consoles_diverses_screen.back_requested.emit()
    assert window._root_stack.currentWidget() is window._main_view


@patch("r36s_studio.gui.main_window.consoles_diverses_settings_store.lire_licence", return_value="cle-existante")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(consoles_diverses_server_url="https://exemple.invalid"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_consoles_diverses_settings_requested_prefills_dialog(
    mock_list, mock_filter, mock_detect, mock_load, mock_lire_licence, qapp
):
    window = MainWindow()

    window._consoles_diverses_screen.settings_requested.emit()

    assert window._consoles_diverses_settings_dialog.isVisible() is True
    assert window._consoles_diverses_settings_dialog._server_url_edit.text() == "https://exemple.invalid"
    assert window._consoles_diverses_settings_dialog._licence_edit.text() == "cle-existante"


@patch("r36s_studio.gui.main_window.consoles_diverses_settings_store.enregistrer_licence")
@patch("r36s_studio.gui.main_window.consoles_diverses_settings_store.lire_licence", return_value="nouvelle-cle")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig())
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_consoles_diverses_settings_saved_persists_url_and_licence(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, mock_lire_licence, mock_enregistrer, qapp
):
    window = MainWindow()

    window._consoles_diverses_settings_dialog.settings_saved.emit("https://nouveau-serveur.invalid", "nouvelle-cle")

    mock_save.assert_called_once()
    assert mock_save.call_args[0][0].consoles_diverses_server_url == "https://nouveau-serveur.invalid"
    mock_enregistrer.assert_called_once_with("nouvelle-cle")
    assert window._consoles_diverses_screen._server_url == "https://nouveau-serveur.invalid"
    assert window._consoles_diverses_screen._licence_key == "nouvelle-cle"


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_ui_mode_switch_works_both_ways_and_config_follows(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Sans bouton de retour, basculer en mode expert était un aller
    simple -- ui_mode étant persisté (config.py), l'utilisateur restait
    bloqué en mode expert même après redémarrage."""
    window = MainWindow()
    assert window._root_stack.currentWidget() is window._assisted_landing

    window._assisted_landing.expert_mode_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._home
    assert mock_save.call_args[0][0].ui_mode == "expert"

    window._home.assisted_mode_requested.emit()

    assert window._root_stack.currentWidget() is window._assisted_landing
    assert mock_save.call_args[0][0].ui_mode == "assisted"
    assert mock_save.call_count == 2


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_prepare_button_starts_wizard_on_step_one(mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp):
    window = MainWindow()

    window._assisted_landing.prepare_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._wizard_panel
    assert window._wizard_flow.current_job() == WizardJob.DETECT_SOURCE
    assert window._wizard_poll_timer.isActive() is True


# --- cycle de vie du sondage automatique journalisé une fois chacun -------
#
# Bug rapporté sur le binaire empaqueté : impossible de savoir depuis le
# journal si `_wizard_poll_timer` démarre bien et reste actif -- seul son
# absence totale de détection automatique (jusqu'au clic manuel sur
# Rafraîchir) était visible. `_start_wizard_poll_timer`/
# `_stop_wizard_poll_timer` journalisent désormais chaque vraie transition
# arrêté <-> actif, une seule fois -- jamais à chaque relance interne
# pendant l'attente (§5 mode assisté).


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_poll_start_is_logged_once_not_on_every_internal_restart(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()

    window._assisted_landing.prepare_requested.emit()  # démarre le sondage (étape 1)
    window._on_wizard_refresh_requested()  # relance manuelle -- déjà actif, rien à trouver
    window._on_wizard_poll()  # tick automatique -- toujours rien à trouver

    log_text = window._log_panel._log_view.toPlainText()
    assert log_text.count("Sondage automatique de la carte démarré") == 1


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_poll_stop_is_logged_once_when_card_found(mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()  # trouve la carte -> arrête le minuteur pour l'empreinte
        window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, device, "fp-1")  # déjà arrêté

    log_text = window._log_panel._log_view.toPlainText()
    assert log_text.count("Sondage automatique de la carte démarré") == 1
    assert log_text.count("Sondage automatique de la carte arrêté") == 1
    assert window._wizard_poll_timer.isActive() is False


def _mock_fingerprint_runner_class():
    """Même principe que `_mock_identify_runner_class`, pour
    `WizardFingerprintRunner` (§5 mode assisté, correctif : plus de
    `compute_boot_fingerprint` synchrone sur le thread principal)."""
    instances = []

    def _factory(device_path, parent=None):
        instance = MagicMock()
        instance.device_path = device_path
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


# --- plusieurs cartes candidates à l'étape 1/4 : proposer un choix --------
#
# Bug rapporté : _list_safe_devices() peut retourner plusieurs candidates
# (ex. un disque USB qui passe le filtre en plus de la carte SD) -- avant
# ce correctif, `candidate` retombait à None dans ce cas, indiscernable de
# "aucune carte" (même statut "en attente"), ce qui donnait l'impression
# que la détection était cassée en mode assisté alors qu'elle voit
# exactement la même chose que le mode expert (_list_safe_devices()
# partagée par les deux).


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_one_poll_with_multiple_candidates_opens_device_dialog(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    sd_card = _make_device(path="/dev/fake-disk-test-1", display="Carte SD")
    usb_disk = _make_device(path="/dev/fake-disk-test-2", display="Disque USB 123 Go")
    mock_list.return_value = [sd_card, usb_disk]
    mock_filter.return_value = [sd_card, usb_disk]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window.show()
    window._assisted_landing.prepare_requested.emit()

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_not_called()  # pas de choix fait -> pas d'empreinte encore
    assert window._device_dialog.isVisible() is True
    assert window._device_dialog._devices == [sd_card, usb_disk]
    assert window._wizard_poll_timer.isActive() is False


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_choosing_a_candidate_from_device_dialog_starts_fingerprint_check(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    sd_card = _make_device(path="/dev/fake-disk-test-1", display="Carte SD")
    usb_disk = _make_device(path="/dev/fake-disk-test-2", display="Disque USB 123 Go")
    mock_list.return_value = [sd_card, usb_disk]
    mock_filter.return_value = [sd_card, usb_disk]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._on_wizard_poll()  # ouvre la fenêtre Choix de la carte (2 candidates)

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._device_dialog.device_chosen.emit(sd_card)

    assert window._device_dialog.isVisible() is False
    fingerprint_runner_class.assert_called_once_with(sd_card.path, parent=window)
    # Ne doit pas non plus avoir déclenché le chemin mode expert.
    assert window._device is None


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_poll_logs_rejected_devices_with_reason_once(mock_list, mock_load, mock_save, qapp):
    """Trace diagnosticable (§5 mode assisté) : combien de périphériques
    trouvés et lesquels écartés, avec la raison -- sans filtre
    supplémentaire côté assisté (même appel que le mode expert). Ne doit
    pas se répéter à chaque sondage identique (pas de spam du journal)."""
    system_disk = Device(
        path="/dev/fake-disk-test-1",
        display="Disque système",
        size_bytes=500_000_000_000,
        removable=False,
        bus="Internal",
        is_system=True,
        mountpoints=["/"],
    )
    mock_list.return_value = [system_disk]

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_poll()
    window._on_wizard_poll()  # état identique -> ne doit pas dupliquer la ligne

    log_text = window._log_panel._log_view.toPlainText()
    assert log_text.count("Détection") == 1
    assert "Disque système" in log_text
    assert "carte système" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_panel_refresh_button_triggers_immediate_poll(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_poll_timer.stop()

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._wizard_panel.refresh_requested.emit()

    # Relance immédiatement une recherche, sans attendre le prochain tick
    # (jusqu'à 1,5 s) -- la carte est trouvée du premier coup, le sondage
    # s'arrête donc de nouveau (comportement normal, déjà couvert par
    # test_wizard_step_one_poll_starts_fingerprint_runner_on_a_separate_thread).
    fingerprint_runner_class.assert_called_once_with(device.path, parent=window)


# --- diagnostic d'un sondage automatique resté silencieux (§5 mode
# assisté, `_check_wizard_poll_stall`) : bug rapporté ("la carte n'est
# plus retenue après un retour à l'accueil puis une relance, jusqu'au clic
# manuel sur Rafraîchir") mais non reproduit en relisant `_start_wizard`/
# `_cancel_wizard` ni en rejouant exactement ce scénario (voir
# test_wizard_relaunch_after_cancelling_backup_kind_dialog_restarts_poll_
# and_immediately_redetects_the_device ci-dessous, qui passe) -- ce
# diagnostic pur permet de confirmer sur du vrai matériel si le minuteur
# s'arrête réellement de sonner, sans rien changer au comportement.


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_poll_logs_nothing_on_first_poll_or_normal_cadence(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    # `_start_wizard_poll_timer` (appelé par `prepare_requested`) a déjà
    # posé un vrai horodatage -- remis à `None` pour repartir d'un « rien
    # à comparer » propre sous l'horloge simulée ci-dessous.
    window._wizard_last_poll_monotonic = None

    with patch("r36s_studio.gui.main_window.time.monotonic", side_effect=[100.0, 101.4]):
        window._on_wizard_poll()  # fixe le premier horodatage (100.0)
        window._on_wizard_poll()  # 1,4 s plus tard -- cadence normale (1,5 s)

    log_text = window._log_panel._log_view.toPlainText()
    assert "sondage automatique" not in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_poll_logs_a_stall_when_gap_far_exceeds_the_normal_interval(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_last_poll_monotonic = None

    with patch("r36s_studio.gui.main_window.time.monotonic", side_effect=[100.0, 310.0]):
        window._on_wizard_poll()
        window._on_wizard_poll()  # 210 s plus tard -- très au-delà du seuil (6 s)

    log_text = window._log_panel._log_view.toPlainText()
    assert "sondage automatique" in log_text
    assert "210" in log_text
    # Corrige plutôt que seulement constater (§1) : le minuteur est relancé
    # directement (`.start()`), sans passer par `_start_wizard_poll_timer`
    # (qui remettrait `_wizard_poll_stall_warned` à `False` et rouvrirait la
    # porte à répéter la même ligne si le ralentissement persiste).
    assert window._wizard_poll_timer.isActive() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_poll_stall_message_does_not_repeat_while_the_stall_persists(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Défaut rapporté sur le binaire empaqueté : la même ligne de chien de
    garde apparaissait à chaque tick tant que l'énumération des disques
    restait lente, noyant le journal. Deux sondages consécutifs, tous deux
    très au-delà du seuil (ralentissement qui persiste) -- une seule ligne
    doit apparaître, pas deux."""
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_last_poll_monotonic = None

    with patch("r36s_studio.gui.main_window.time.monotonic", side_effect=[100.0, 310.0, 520.0]):
        window._on_wizard_poll()  # t=100, rien à comparer
        window._on_wizard_poll()  # t=310, 210 s plus tard -- stall, journalisé
        window._on_wizard_poll()  # t=520, 210 s plus tard -- stall persistant, pas rejournalisé

    log_text = window._log_panel._log_view.toPlainText()
    assert log_text.count("sondage automatique") == 1


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_poll_stall_diagnostic_does_not_fire_after_a_legitimate_pause_for_backup(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Faux positif rapporté sur du vrai matériel : `_wizard_poll_timer`
    s'arrête légitimement pendant toute l'étape CREATE_IMAGE (sauvegarde
    de plusieurs minutes) -- son redémarrage à l'étape DETECT_TARGET
    (`_on_wizard_source_eject_finished`) ne doit jamais être comparé au
    dernier sondage d'*avant* cette pause, sans quoi le tout premier
    sondage suivant la reprise ressemble à un arrêt de plusieurs centaines
    de secondes alors qu'il ne s'agit que du comportement voulu."""
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()  # DETECT_SOURCE, pose un premier horodatage

    with patch("r36s_studio.gui.main_window.time.monotonic", return_value=100.0):
        window._on_wizard_poll()  # dernier sondage avant la pause de la sauvegarde

    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()), patch(
        "r36s_studio.gui.main_window.time.monotonic", return_value=100.0 + 615.0
    ):
        # Simule la reprise du sondage à l'étape 3, après ~10 min de
        # sauvegarde (`_wizard_poll_timer` resté arrêté tout ce temps) --
        # `_start_wizard_poll_timer` doit reposer sa propre référence ici,
        # pas hériter de celle d'avant la pause.
        window._on_wizard_source_eject_finished(True, None, None)

    with patch("r36s_studio.gui.main_window.time.monotonic", return_value=100.0 + 615.0 + 1.5):
        window._on_wizard_poll()  # premier sondage réel après la reprise, 1,5 s plus tard

    log_text = window._log_panel._log_view.toPlainText()
    assert "sondage automatique" not in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_poll_stall_diagnostic_does_not_fire_across_repeated_same_card_fingerprint_checks(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Second faux positif rapporté, répété toutes les 6 à 12 s en boucle :
    tant que la carte neuve n'est pas encore branchée, chaque sondage qui
    retrouve la même carte que la source arrête le minuteur pour lancer
    une vérification d'empreinte (montage/démontage du BOOT, plusieurs
    secondes), puis le redémarre une fois « même carte » confirmé
    (`_on_wizard_fingerprint_ready`). Comparer le sondage suivant à celui
    d'*avant* ce cycle déclenchait un faux positif à chaque itération,
    alors que la carte n'a simplement pas encore été échangée (cas
    normal)."""
    same_card = _make_device(path="/dev/fake-disk-test-9")
    mock_list.return_value = [same_card]
    mock_filter.return_value = [same_card]

    window = MainWindow()
    _target_setup(window, same_card)
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()), patch(
        "r36s_studio.gui.main_window.time.monotonic", return_value=100.0
    ):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
        window._on_wizard_source_eject_finished(True, None, None)  # démarre le sondage, t=100

    with patch(
        "r36s_studio.gui.main_window.WizardFingerprintRunner", _mock_fingerprint_runner_class()
    ), patch("r36s_studio.gui.main_window.time.monotonic", return_value=100.0):
        window._on_wizard_poll()  # trouve la même carte -> arrête le minuteur, lance l'empreinte

    with patch("r36s_studio.gui.main_window.time.monotonic", return_value=100.0 + 8.0):
        # Empreinte recalculée (~8 s, une vérification BOOT réelle) --
        # même carte que la source : le minuteur redémarre à la fin.
        window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, same_card, "fp-source")

    with patch("r36s_studio.gui.main_window.time.monotonic", return_value=100.0 + 8.0 + 1.5):
        window._on_wizard_poll()  # tick suivant, cadence normale depuis le redémarrage

    log_text = window._log_panel._log_view.toPlainText()
    assert "sondage automatique" not in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_relaunch_after_cancelling_backup_kind_dialog_restarts_poll_and_immediately_redetects_the_device(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Rejoue le scénario rapporté (§5 mode assisté) : détection de la
    carte source, Continuer vers `BackupKindDialog`, annulation (retour à
    l'accueil), relance -- le minuteur doit redémarrer et retrouver la
    même carte dès le premier sondage, sans nécessiter de clic manuel sur
    Rafraîchir. Passe avec le code actuel : aucun état périmé n'a été
    trouvé dans `_start_wizard`/`_cancel_wizard` pour ce chemin précis
    (voir la note ci-dessus)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    assert window._wizard_poll_timer.isActive() is True

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, device, "fp-source")
    window._on_wizard_continue()
    assert window._wizard_flow.current_job() == WizardJob.CREATE_IMAGE
    assert window._backup_kind_dialog.isVisible() is True

    window._backup_kind_dialog.cancelled.emit()
    assert window._root_stack.currentWidget() is window._assisted_landing
    assert window._wizard_active is False
    assert window._wizard_poll_timer.isActive() is False

    window._assisted_landing.prepare_requested.emit()
    assert window._wizard_poll_timer.isActive() is True
    assert window._wizard_flow.current_job() == WizardJob.DETECT_SOURCE

    fingerprint_runner_class = _mock_fingerprint_runner_class()
    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_called_once_with(device.path, parent=window)


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_panel_refresh_button_resumes_automatic_polling_when_nothing_found(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Cas d'un rafraîchissement manuel après un choix annulé dans la
    fenêtre Choix de la carte : le sondage automatique doit reprendre,
    pas seulement une recherche isolée."""
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_poll_timer.stop()

    window._wizard_panel.refresh_requested.emit()

    assert window._wizard_poll_timer.isActive() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_one_shows_refresh_button(mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()

    window._assisted_landing.prepare_requested.emit()

    assert window._wizard_panel._refresh_button.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_one_poll_starts_fingerprint_runner_on_a_separate_thread(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Correctif : monter BOOT pour calculer l'empreinte (§4.4) peut
    bloquer jusqu'à MOUNT_WAIT_SECONDS -- un gel de l'interface pendant ce
    montage se lit comme un plantage. `_on_wizard_poll` ne doit donc plus
    jamais appeler `compute_boot_fingerprint` directement sur le thread Qt
    principal, seulement démarrer `WizardFingerprintRunner`."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    assert window._wizard_panel._continue_button.isEnabled() is False

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_called_once_with(device.path, parent=window)
    fingerprint_runner_class.instances[0].start.assert_called_once()
    # Toujours en attente du résultat -- rien n'est encore décidé.
    assert window._wizard_panel._continue_button.isEnabled() is False
    assert window._wizard_source_device is None
    assert window._wizard_poll_timer.isActive() is False  # pas de deuxième calcul en parallèle


@patch("r36s_studio.detect.list_partitions", return_value=[])
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_fingerprint_ready_for_detect_source_stores_device_and_enables_continue(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, mock_partitions, qapp
):
    device = _make_device()
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, device, "fp-source")

    assert window._wizard_panel._continue_button.isEnabled() is True
    assert window._wizard_source_device is device
    assert window._wizard_source_fingerprint == "fp-source"


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_continue_on_step_one_advances_to_create_image_and_opens_backup_kind_dialog(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    device = _make_device()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, device, "fp-source")

    window._wizard_panel.continue_requested.emit()

    assert window._wizard_flow.is_done(WizardJob.DETECT_SOURCE) is True
    assert window._wizard_flow.current_job() == WizardJob.CREATE_IMAGE
    assert window._backup_kind_dialog.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_wizard_resets_stale_ad_hoc_prepare_card_state(mock_list, mock_filter, mock_load, qapp):
    """Bug corrigé, confirmé sur du vrai matériel : un `_prepare_card_
    candidate`/`_assisted_ad_hoc_active` resté vrai d'un passage précédent
    par « Préparer une carte avec cette sauvegarde » (§4.3, sans retour
    explicite à l'accueil) détournait le Continuer du vrai parcours guidé
    vers cette branche ad-hoc -- `_start_wizard` doit repartir d'un état
    propre, quel que soit ce qui a été laissé derrière."""
    window = MainWindow()
    stale_source_device = _make_device(path="/dev/fake-disk-test-stale", display="Carte laissée par erreur")
    window._prepare_card_candidate = stale_source_device
    window._assisted_ad_hoc_active = True
    window._prepare_card_poll_timer.start()

    window._assisted_landing.prepare_requested.emit()

    assert window._prepare_card_candidate is None
    assert window._assisted_ad_hoc_active is False
    assert window._prepare_card_poll_timer.isActive() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_continue_ignores_stale_prepare_card_candidate_while_wizard_active(
    mock_list, mock_filter, mock_load, qapp, tmp_path
):
    """Garde-fou supplémentaire dans `_on_wizard_continue` lui-même (en
    plus de la réinitialisation dans `_start_wizard` ci-dessus) : même si
    `_prepare_card_candidate` est resté non `None` par un autre chemin,
    le Continuer du vrai parcours guidé (`_wizard_active`) ne doit jamais
    router vers la fenêtre Confirmation avec cette carte-là -- c'est
    exactement le bug constaté sur du vrai matériel (la carte source de
    128 Go annoncée à la place de la carte cible de 32 Go, court-
    circuitant la vérification d'empreinte)."""
    window = MainWindow()
    stale_source_device = _make_device(path="/dev/fake-disk-test-source", display="Carte source 128 Go")
    target_device = _make_device(path="/dev/fake-disk-test-target", display="Carte cible 32 Go")
    image_path = tmp_path / "clone.img"
    image_path.write_bytes(b"x" * 1024)
    window._assisted_landing.prepare_requested.emit()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_flow.mark_done(WizardJob.CREATE_IMAGE)
    window._wizard_target_device = target_device
    window._file_path = str(image_path)
    window._wizard_panel.set_can_continue(True)
    # Simule l'état incohérent lui-même (contourne la réinitialisation de
    # `_start_wizard`, pour vérifier ce garde-fou précis en isolation).
    window._prepare_card_candidate = stale_source_device

    with patch("r36s_studio.gui.main_window.MainWindow._proceed_to_flash_confirmation") as mock_proceed:
        window._wizard_panel.continue_requested.emit()

    mock_proceed.assert_not_called()
    assert window._wizard_flow.is_done(WizardJob.DETECT_TARGET) is True
    assert window._wizard_flow.current_job() == WizardJob.RESTORE_IMAGE
    assert window._device is target_device
    assert window._confirm_dialog.isVisible() is True


# --- étape 2 : choix complet/système, puis copie (§5 mode assisté) ---------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_choosing_full_copy_opens_file_dialog_in_backup_mode_with_size_hint(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._wizard_source_device = _make_device(size_bytes=64_000_000_000)

    window._on_backup_kind_chosen("full")

    assert window._mode == "backup"
    assert window._device is window._wizard_source_device
    assert window._wizard_backup_kind == "full"
    assert window._wizard_estimated_backup_bytes == 64_000_000_000
    assert window._file_dialog.isVisible() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "64" in log_text or "Go" in log_text  # taille annoncée avant même le choix du fichier


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_choosing_system_only_reuses_the_estimate_pipeline(mock_list, mock_filter, mock_load, qapp):
    """Réutilise `_start_system_backup_estimate` (§4.3) sans le dupliquer --
    même pipeline à deux niveaux (estimation non élevée, puis élevée en
    repli) que l'opération ad-hoc équivalente de l'accueil assisté."""
    window = MainWindow()
    window._wizard_source_device = _make_device()
    estimate_runner_class = _mock_estimate_runner_class()

    with patch("r36s_studio.gui.main_window.SystemBackupEstimateRunner", estimate_runner_class):
        window._on_backup_kind_chosen("system")

    assert window._mode == "backup_system"
    assert window._wizard_backup_kind == "system"
    estimate_runner_class.assert_called_once_with(window._wizard_source_device.path, parent=window)


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_system_only_estimate_populates_free_space_precheck_size(mock_list, mock_filter, mock_load, qapp):
    """`_finish_system_backup_estimate` est partagé avec l'opération ad-hoc
    de l'accueil assisté -- doit tout de même alimenter `_wizard_estimated_
    backup_bytes` pour que le pré-contrôle d'espace disque libre (§ pré-vol)
    ne soit pas silencieusement sans effet pour une sauvegarde système."""
    window = MainWindow()

    window._finish_system_backup_estimate(9_000_000_000, None)

    assert window._wizard_estimated_backup_bytes == 9_000_000_000


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_create_image_free_space_precheck_blocks_before_starting_worker(
    mock_list, mock_filter, mock_load, qapp, tmp_path
):
    """Pré-vol (§5 mode assisté, parcours de clonage) : jamais un échec
    après une longue copie déjà lancée -- vérifié avant `_start_worker()`,
    pas seulement côté worker élevé."""
    window = MainWindow()
    window._wizard_active = True
    window._mode = "backup"
    window._wizard_backup_kind = "full"
    window._wizard_estimated_backup_bytes = 999_000_000_000_000  # bien plus que l'espace libre réel

    with patch("r36s_studio.gui.main_window.MainWindow._start_worker") as mock_start_worker, patch(
        "r36s_studio.gui.main_window.QMessageBox.warning"
    ) as mock_warning:
        window._on_file_chosen(str(tmp_path / "out.img"))

    mock_start_worker.assert_not_called()
    mock_warning.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_create_image_free_space_precheck_passes_with_enough_space(
    mock_list, mock_filter, mock_load, qapp, tmp_path
):
    window = MainWindow()
    window._wizard_active = True
    window._mode = "backup"
    window._wizard_backup_kind = "full"
    window._wizard_estimated_backup_bytes = 1  # 1 octet requis, toujours disponible

    with patch("r36s_studio.gui.main_window.MainWindow._start_worker") as mock_start_worker:
        window._on_file_chosen(str(tmp_path / "out.img"))

    mock_start_worker.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_job_finished_for_create_image_logs_created_path(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._wizard_active = True
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._mode = "backup"
    window._device = _make_device()
    window._wizard_source_device = window._device  # entrer dans DETECT_TARGET éjecte cette carte
    window._file_path = "/home/x/clone.img"

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._on_wizard_job_finished(True)

    log_text = window._log_panel._log_view.toPlainText()
    assert "/home/x/clone.img" in log_text
    assert window._wizard_flow.is_done(WizardJob.CREATE_IMAGE) is True
    assert window._wizard_flow.current_job() == WizardJob.DETECT_TARGET


# --- étapes 3->4 : éjection de la carte source avant d'inviter à la -------
# --- retirer -- elle reste montée pendant les étapes 2/3 (lecture des -----
# --- .dtb, copie BOOT/EASYROMS) puisque c'est de là qu'elles sont lues ; --
# --- l'éjection n'intervient qu'en tout début de l'étape 4, avant la ------
# --- consigne de retrait, et le sondage de la carte neuve n'y démarre -----
# --- qu'une fois cette éjection effectivement réussie. ---------------------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_entering_detect_target_ejects_the_source_card_first(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    source = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_device = source
    mock_list.return_value = [source]
    mock_filter.return_value = [source]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)

    assert runner_class.instances[0].argv == ["eject", "--device", source.path]


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_entering_detect_target_logs_before_starting_the_eject_worker(mock_list, mock_filter, mock_load, qapp):
    """Quatrième signalement, diagnostic : sur du vrai matériel, aucune
    ligne d'éjection n'apparaissait entre la fin de la sauvegarde et la
    détection suivante -- ni succès ni échec. Cette ligne doit désormais
    apparaître en tout premier, avant même que le worker élevé démarre --
    si elle manque encore au prochain test réel, `_run_wizard_source_eject`
    elle-même n'est jamais atteinte."""
    window = MainWindow()
    source = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_device = source
    mock_list.return_value = [source]
    mock_filter.return_value = [source]

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)

    log_text = window._log_panel._log_view.toPlainText()
    assert "Éjection de ta carte d'origine" in log_text


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_entering_detect_target_with_no_source_device_logs_instead_of_vanishing(
    mock_list, mock_filter, mock_load, qapp
):
    """Si `_wizard_source_device` est `None` au moment d'entrer dans
    DETECT_TARGET (état incohérent) -- et qu'aucune carte n'est détectée
    non plus (`list_devices`/`filter_devices` vides, comme ici) -- la
    redétection avant éjection (`_refresh_device_before_eject_retry`, bug
    distinct corrigé séparément) ne trouve rien à éjecter : message
    explicite et écran d'erreur, jamais un blocage muet ni la levée brute
    d'origine (`AttributeError` sur `None.path`, symptôme du quatrième
    signalement -- aucune trace du tout)."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)
    window._wizard_source_device = None

    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    log_text = window._log_panel._log_view.toPlainText()
    assert "introuvable" in log_text  # jamais un blocage muet
    assert window._wizard_panel._resume_button.isVisible() is True  # écran d'erreur, pas un blocage muet


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_detect_target_confirms_source_card_can_be_removed_after_eject(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    source = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_device = source
    mock_list.return_value = [source]
    mock_filter.return_value = [source]

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(True, None, None)

    log_text = window._log_panel._log_view.toPlainText()
    assert "toute sécurité" in log_text


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_detect_target_eject_failure_shows_explicit_error_and_no_polling(mock_list, mock_filter, mock_load, qapp):
    """Bug corrigé, confirmé sur du vrai matériel : cette éjection
    échouait auparavant *silencieusement* sur Windows (`eject_device`
    exécuté dans le processus GUI, non élevé) -- aucune ligne au journal,
    ni succès ni échec. Passe désormais par le worker élevé (`_start_
    eject`) ; simulé ici en appelant directement le callback de fin comme
    le ferait `WorkerRunner.error`/`.finished` une fois le worker élevé
    terminé."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)
    source = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_device = source
    mock_list.return_value = [source]
    mock_filter.return_value = [source]
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE):
        window._wizard_flow.mark_done(job)

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(False, "EJECT_FAILED", "carte occupée")

    log_text = window._log_panel._log_view.toPlainText()
    assert "carte occupée" in log_text  # détail brut, journal de bord (§5)
    assert window._wizard_panel._resume_button.isVisible() is True  # bouton pour réessayer
    assert window._wizard_poll_timer.isActive() is False
    # Le job n'est jamais marqué fait sur un échec -- Reprendre le relance.
    assert window._wizard_flow.current_job() == WizardJob.DETECT_TARGET


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_detect_target_resume_after_eject_failure_retries_the_eject(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    source = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_device = source
    mock_list.return_value = [source]
    mock_filter.return_value = [source]
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE):
        window._wizard_flow.mark_done(job)

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(False, "EJECT_FAILED", "carte occupée")
    assert window._wizard_poll_timer.isActive() is False

    runner_class = _mock_runner_class()
    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._wizard_panel.resume_requested.emit()
        assert runner_class.instances[0].argv == ["eject", "--device", "/dev/fake-disk-test-source"]
        window._on_wizard_source_eject_finished(True, None, None)

    assert window._wizard_poll_timer.isActive() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_detect_target_eject_retry_redetects_device_and_uses_the_fresh_path(
    mock_list, mock_filter, mock_load, qapp
):
    """Bug corrigé, confirmé sur du vrai matériel : une deuxième tentative
    après un échec (ex. invite UAC refusée) réutilisait tel quel l'ancien
    chemin Windows (`\\\\.\\PhysicalDriveN`) -- Windows a pu le libérer/
    renuméroter entre-temps, rejeté ensuite par le worker élevé lui-même
    comme introuvable (`DEVICE_NOT_ALLOWED`). La carte est redétectée avant
    chaque tentative (`_refresh_device_before_eject_retry`) : un chemin qui
    a changé entre les deux essais est donc suivi, pas figé sur le
    premier."""
    window = MainWindow()
    source_v1 = _make_device(path="/dev/fake-disk-test-source-v1")
    window._wizard_source_device = source_v1
    mock_list.return_value = [source_v1]
    mock_filter.return_value = [source_v1]
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE):
        window._wizard_flow.mark_done(job)

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(False, "ELEVATION_REFUSED", "invite UAC refusée")

    # Windows a renuméroté le disque entre les deux tentatives -- même
    # carte physique, chemin différent.
    source_v2 = _make_device(path="/dev/fake-disk-test-source-v2")
    mock_list.return_value = [source_v2]
    mock_filter.return_value = [source_v2]

    runner_class = _mock_runner_class()
    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._wizard_panel.resume_requested.emit()

    assert runner_class.instances[0].argv == ["eject", "--device", "/dev/fake-disk-test-source-v2"]
    assert window._wizard_source_device is source_v2


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_source_card_stays_mounted_during_create_image_step(mock_list, mock_filter, mock_load, qapp):
    """La carte source n'est éjectée qu'à l'entrée de l'étape 3 -- elle
    reste montée pendant l'étape 2 (l'image est créée depuis cette même
    carte)."""
    window = MainWindow()
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._enter_wizard_job(WizardJob.CREATE_IMAGE)

    runner_class.assert_not_called()


# --- éjection de la carte source chaînée dans le worker de l'étape 2 -------
# (bug corrigé : une invite UAC dédiée rien que pour cette éjection,
# en plus de celle déjà demandée pour la sauvegarde -- `backup --eject-
# after` chaîne les deux dans le même worker élevé dans le cas courant).


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_backup_start_worker_chains_eject_after_and_connects_result_signal(
    mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path
):
    window = MainWindow()
    window._wizard_active = True
    window._mode = "backup"
    window._device = _make_device(path="/dev/fake-disk-test-source")
    window._file_path = str(tmp_path / "out.img")
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--eject-after" in runner_class.instances[0].argv
    runner_class.instances[0].eject_result.connect.assert_called_once_with(window._on_wizard_source_eject_result)


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_expert_mode_backup_never_gets_eject_after_flag(mock_list, mock_filter, mock_load, mock_save, qapp, tmp_path):
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = str(tmp_path / "out.img")
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--eject-after" not in runner_class.instances[0].argv
    runner_class.instances[0].eject_result.connect.assert_not_called()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_on_wizard_source_eject_result_stores_outcome(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()

    window._on_wizard_source_eject_result(True, "")
    assert window._wizard_source_ejected is True
    assert window._wizard_source_eject_error_msg is None

    window._on_wizard_source_eject_result(False, "carte occupée")
    assert window._wizard_source_ejected is False
    assert window._wizard_source_eject_error_msg == "carte occupée"


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_run_wizard_source_eject_skips_dedicated_worker_when_already_chained(
    mock_list, mock_filter, mock_load, qapp
):
    """Cas courant : `backup --eject-after` (étape 2) a déjà éjecté la
    carte source dans son propre worker élevé -- entrer dans l'étape 3 ne
    doit jamais relancer un second worker d'éjection dédié (ce qui
    redemanderait une invite UAC rien que pour ça)."""
    window = MainWindow()
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_ejected = True
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)

    runner_class.assert_not_called()
    assert window._wizard_poll_timer.isActive() is True  # bien passé à l'étape suivante


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_run_wizard_source_eject_falls_back_to_dedicated_worker_when_chained_eject_failed(
    mock_list, mock_filter, mock_load, qapp
):
    """L'éjection chaînée de l'étape 2 a échoué (rapportée séparément, la
    sauvegarde elle-même a déjà réussi) -- retombe sur le worker d'éjection
    dédié existant, sans jamais avoir à refaire toute la sauvegarde pour
    ça."""
    source = _make_device(path="/dev/fake-disk-test-source")
    window = MainWindow()
    window._wizard_source_device = source
    window._wizard_source_ejected = False
    mock_list.return_value = [source]
    mock_filter.return_value = [source]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)

    assert runner_class.instances[0].argv == ["eject", "--device", source.path]


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_wizard_resets_chained_eject_state(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._wizard_source_ejected = True
    window._wizard_source_eject_error_msg = "carte occupée"

    window._start_wizard()

    assert window._wizard_source_ejected is None
    assert window._wizard_source_eject_error_msg is None


# --- étape 5 : éjection de la carte cible, via le worker élevé -------------
# (§4.3/§4.4 : bug corrigé, même correctif que l'étape 3 et le mode expert) -


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_run_wizard_eject_starts_elevated_worker_with_target_device(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    target = _make_device(path="/dev/fake-disk-test-target")
    window._wizard_target_device = target
    mock_list.return_value = [target]
    mock_filter.return_value = [target]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._run_wizard_eject()

    assert runner_class.instances[0].argv == ["eject", "--device", "/dev/fake-disk-test-target"]


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_eject_finished_success_marks_job_done_and_finishes_wizard(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._wizard_target_device = _make_device(path="/dev/fake-disk-test-target")
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE, WizardJob.DETECT_TARGET, WizardJob.RESTORE_IMAGE):
        window._wizard_flow.mark_done(job)

    window._on_wizard_eject_finished(True, None, None)

    assert window._wizard_flow.is_done(WizardJob.EJECT) is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "toute sécurité" in log_text


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_eject_finished_failure_shows_explicit_error(mock_list, mock_filter, mock_load, qapp):
    """Bug corrigé, confirmé sur du vrai matériel : le même échec silencieux
    (élévation manquante) concernait aussi l'éjection finale de la carte
    cible -- désormais journalisé explicitement, jamais un succès (ni un
    échec) silencieux (§4.4)."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)
    window._wizard_target_device = _make_device(path="/dev/fake-disk-test-target")
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE, WizardJob.DETECT_TARGET, WizardJob.RESTORE_IMAGE):
        window._wizard_flow.mark_done(job)

    window._on_wizard_eject_finished(False, "EJECT_FAILED", "carte occupée")

    assert window._wizard_flow.is_done(WizardJob.EJECT) is False
    log_text = window._log_panel._log_view.toPlainText()
    assert "carte occupée" in log_text
    assert window._wizard_panel._resume_button.isVisible() is True


# --- étape 4 : garde-fou par empreinte de contenu, pas path/size_bytes -----


def _target_setup(window, device):
    window._wizard_flow.reset()
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE):
        window._wizard_flow.mark_done(job)
    window._wizard_source_fingerprint = "fp-source"
    # Entrer dans DETECT_TARGET éjecte désormais la carte source en tout
    # premier -- il lui faut donc un périphérique distinct de la carte
    # cible utilisée par ces tests.
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_three_poll_also_starts_fingerprint_runner(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    same_card = _make_device(path="/dev/fake-disk-test-9")
    mock_list.return_value = [same_card]
    mock_filter.return_value = [same_card]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    _target_setup(window, same_card)
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(True, None, None)

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_called_once_with(same_card.path, parent=window)
    assert window._wizard_poll_timer.isActive() is False  # pas de deuxième calcul en parallèle


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_three_refuses_to_continue_when_fingerprint_matches_source(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    same_card = _make_device(path="/dev/fake-disk-test-9")

    window = MainWindow()
    _target_setup(window, same_card)
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(True, None, None)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, same_card, "fp-source")

    assert window._wizard_panel._continue_button.isEnabled() is False
    assert window._wizard_target_device is None
    assert window._wizard_poll_timer.isActive() is True  # continue d'attendre une vraie carte différente


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_three_allows_continue_when_fingerprint_differs(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    new_card = _make_device(path="/dev/fake-disk-test-9")

    window = MainWindow()
    _target_setup(window, new_card)
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(True, None, None)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, new_card, "fp-blank-or-different")

    assert window._wizard_panel._continue_button.isEnabled() is True
    assert window._wizard_target_device is new_card
    assert window._wizard_poll_timer.isActive() is False


# --- étape 3, confirmation explicite quand ni le contenu ni la taille ------
# ne peuvent prouver un changement de carte : bug corrigé, confirmé sur -----
# du vrai matériel (chemin de périphérique inutilisable comme repli sur ----
# certains lecteurs Windows -- remplace une tentative précédente basée sur -
# le chemin, qui bloquait indéfiniment sur ce type de lecteur, §4.4) --------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_three_opens_confirmation_dialog_when_unverifiable(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Scénario réel rapporté : carte source vierge (ou firmware non
    reconnu), carte cible détectée de même taille -- ni `is_same_card` ni
    `size_proves_different_card` ne peuvent trancher. Doit ouvrir
    `SameCardUnverifiedDialog` plutôt que de laisser passer silencieusement
    ou de bloquer indéfiniment sans confirmation possible."""
    window = MainWindow()
    window._wizard_flow.reset()
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE):
        window._wizard_flow.mark_done(job)
    window._wizard_source_fingerprint = None
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source", size_bytes=32_000_000_000)
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(True, None, None)
    candidate = _make_device(path="/dev/fake-disk-test-target", size_bytes=32_000_000_000)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, candidate, None)

    assert window._same_card_unverified_dialog.isVisible() is True
    assert window._pending_target_candidate is candidate
    assert window._wizard_target_device is None
    assert window._wizard_panel._continue_button.isEnabled() is False
    assert window._wizard_poll_timer.isActive() is False  # pas de deuxième calcul en parallèle


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_three_confirming_dialog_accepts_the_candidate(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._wizard_flow.reset()
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE):
        window._wizard_flow.mark_done(job)
    window._wizard_source_fingerprint = None
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source", size_bytes=32_000_000_000)
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(True, None, None)
    candidate = _make_device(path="/dev/fake-disk-test-target", size_bytes=32_000_000_000)
    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, candidate, None)

    window._same_card_unverified_dialog.confirmed.emit()

    assert window._same_card_unverified_dialog.isVisible() is False
    assert window._pending_target_candidate is None
    assert window._wizard_target_device is candidate
    assert window._wizard_panel._continue_button.isEnabled() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_three_allows_continue_without_confirmation_when_sizes_differ(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Une différence de taille est une preuve positive (une carte ne
    change jamais de capacité) -- ne doit pas ouvrir la fenêtre de
    confirmation, contrairement au cas de taille identique ci-dessus."""
    window = MainWindow()
    window._wizard_flow.reset()
    for job in (WizardJob.DETECT_SOURCE, WizardJob.CREATE_IMAGE):
        window._wizard_flow.mark_done(job)
    window._wizard_source_fingerprint = None
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source", size_bytes=128_000_000_000)
    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    window._on_wizard_source_eject_finished(True, None, None)
    candidate = _make_device(path="/dev/fake-disk-test-target", size_bytes=32_000_000_000)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, candidate, None)

    assert window._same_card_unverified_dialog.isVisible() is False
    assert window._wizard_target_device is candidate
    assert window._wizard_panel._continue_button.isEnabled() is True
    assert window._wizard_poll_timer.isActive() is False


# --- reprise après erreur : ne rejoue jamais un job déjà réussi -------------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_resume_after_create_image_failure_reopens_backup_kind_dialog_not_detect_source(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """`current_job()` désigne toujours le job qui a réellement échoué --
    reprendre après un échec de création d'image ne refait jamais la
    détection de la carte source, déjà réussie (`WizardFlow`, voir aussi
    son propre test de reprise partielle)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)
    window._wizard_flow.reset()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_source_device = device
    window._wizard_active = True

    window._enter_wizard_job(WizardJob.CREATE_IMAGE)
    window._on_worker_error("IO_ERROR", "disque plein")
    window._on_wizard_job_finished(False)

    assert window._wizard_flow.is_done(WizardJob.CREATE_IMAGE) is False
    assert window._wizard_panel._resume_button.isVisible() is True

    window._backup_kind_dialog.hide()
    window._wizard_panel.resume_requested.emit()

    assert window._wizard_flow.is_done(WizardJob.DETECT_SOURCE) is True  # jamais rejoué
    assert window._backup_kind_dialog.isVisible() is True


# --- fin de parcours : simple message de succès (§5 mode assisté) ----------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_finish_shows_simple_success_message(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)  # _log_panel vit dans _main_view

    window._finish_wizard()

    log_text = window._log_panel._log_view.toPlainText()
    assert "prête" in log_text
    assert window._wizard_active is False


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_cancel_returns_to_landing_and_stops_polling(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    assert window._wizard_poll_timer.isActive() is True

    window._wizard_panel.cancel_requested.emit()

    assert window._root_stack.currentWidget() is window._assisted_landing
    assert window._wizard_poll_timer.isActive() is False
    assert window._wizard_active is False


# --- bouton "Voir les versions disponibles" (flash, mode expert, §4.6) ----


@patch("r36s_studio.gui.main_window.webbrowser.open")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_releases_button_opens_darkos_r36s_releases_url(mock_list, mock_filter, mock_load, mock_open, qapp):
    from r36s_studio.identify.releases import DARKOS_R36S_RELEASES_URL

    window = MainWindow()

    window._file_dialog.releases_requested.emit("arkos")

    mock_open.assert_called_once_with(DARKOS_R36S_RELEASES_URL)


@patch("r36s_studio.gui.main_window.webbrowser.open")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_releases_button_opens_emuelec_r36s_releases_url(mock_list, mock_filter, mock_load, mock_open, qapp):
    from r36s_studio.identify.releases import EMUELEC_R36S_RELEASES_URL

    window = MainWindow()

    window._file_dialog.releases_requested.emit("emuelec")

    mock_open.assert_called_once_with(EMUELEC_R36S_RELEASES_URL)


@patch("r36s_studio.gui.main_window.webbrowser.open")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_releases_button_does_nothing_for_unknown_firmware_id(mock_list, mock_filter, mock_load, mock_open, qapp):
    """Corrige un bug confirmé en lisant l'ancien code : l'ancien ternaire
    à deux choix retombait silencieusement sur l'URL ArkOS pour tout id
    non reconnu -- le nouveau code catalogue-driven n'ouvre plus rien
    plutôt que la mauvaise page (§4.6)."""
    window = MainWindow()

    window._file_dialog.releases_requested.emit("firmware-inconnu")

    mock_open.assert_not_called()


@patch("r36s_studio.gui.main_window.webbrowser.open")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_releases_button_does_nothing_for_rocknix(mock_list, mock_filter, mock_load, mock_open, qapp):
    """ROCKNIX n'a pas d'URL manuelle (téléchargement automatique) --
    n'ouvrirait rien même si ce signal était émis par erreur pour elle."""
    window = MainWindow()

    window._file_dialog.releases_requested.emit("rocknix")

    mock_open.assert_not_called()


# --- choix du firmware (§4.6 catalogue) à l'étape de flash -----------------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_entering_flash_mode_initializes_file_dialog_firmware_from_config(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    window = MainWindow()
    device = _make_device()
    window._device = device
    window._mode = "flash"

    window._on_device_chosen(device)

    assert window._file_dialog._firmware == "rocknix"


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_restore_image_step_skips_file_dialog_and_uses_own_created_image(mock_list, mock_filter, mock_load, qapp):
    """L'étape 4 (§5 mode assisté, parcours de clonage) restaure
    directement l'image créée à l'étape 2 -- aucun choix de firmware,
    aucune fenêtre Choix du fichier, contrairement au flash du mode
    expert."""
    window = MainWindow()
    window._wizard_target_device = _make_device()
    window._file_path = "/home/x/clone.img"

    with patch("r36s_studio.gui.main_window.estimate_total_bytes", return_value=1_000):
        window._enter_wizard_job(WizardJob.RESTORE_IMAGE)

    assert window._mode == "flash"
    assert window._file_dialog.isVisible() is False
    assert window._confirm_dialog.isVisible() is True


# --- partition de jeux, décision automatique post-écriture (§4.3) ----------
# Retour d'usage réel : la GUI devinait auparavant s'il fallait recréer un
# espace de jeux (comparaison de chemin avec la dernière sauvegarde système
# de la session, puis une case à cocher explicite en mode expert) -- les
# deux ont été retirées. L'app ne demande plus jamais à l'utilisateur une
# information qu'il n'a pas (est-ce que cette image laissera de l'espace
# libre ?) : `__main__.py::cmd_flash` décide seul, après l'écriture, à
# partir de la taille réelle de la carte (`imaging.games_partition.
# create_and_format_games_partition_if_worthwhile`, couvert dans `tests/
# test_imaging_games_partition.py` et `tests/test_cli_flash.py`). Ici, on
# vérifie seulement que la GUI ne construit plus jamais elle-même ce
# drapeau ni cette case.


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_worker_never_builds_a_games_partition_flag(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    window._file_path = "/tmp/systeme.img"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--create-games-partition" not in runner_class.instances[0].argv


def test_confirm_dialog_has_no_games_partition_checkbox(qapp):
    from r36s_studio.gui.screens import ConfirmDialog

    dialog = ConfirmDialog()

    assert not hasattr(dialog, "_games_partition_checkbox")
    assert not hasattr(dialog, "set_games_partition_option")
    assert not hasattr(dialog, "games_partition_requested")


# --- ligne de commande complète journalisée au lancement (§4.4) ------------
# Signalé sur du vrai matériel : impossible de vérifier depuis les traces
# d'élévation ce que l'app avait réellement lancé (un drapeau donné était-il
# bien présent ?), sans instrumenter le worker élevé lui-même. La ligne de
# commande complète (argv) doit désormais apparaître dans le journal de bord
# à chaque lancement, backup/flash comme éjection.


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_worker_logs_the_full_command_line(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    window._file_path = "/tmp/rocknix.img"
    window._app_config.firmware = "rocknix"

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._start_worker()

    log_text = window._log_panel._log_view.toPlainText()
    assert "flash --image /tmp/rocknix.img --device /dev/fake-disk-test-3" in log_text
    assert "--eject-after" in log_text  # ROCKNIX déclenche aussi ce drapeau (§4.6)


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_eject_logs_the_full_command_line(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    device = _make_device()

    with patch("r36s_studio.gui.main_window.WorkerRunner", _mock_runner_class()):
        window._start_eject(device, lambda ok, code, msg: None)

    log_text = window._log_panel._log_view.toPlainText()
    assert f"eject --device {device.path}" in log_text


# --- éjection : refus d'élévation distingué d'un échec ordinaire ----------
# Bug corrigé, confirmé sur du vrai matériel : une invite UAC refusée
# (`elevate.ElevationRefusedError`, `runner.start()`) était auparavant non
# interceptée -- soit elle remontait telle quelle jusqu'à un appelant dont
# le `try/except` générique la retombait sur `EJECT_FAILED` codé en dur
# (`_run_wizard_source_eject`), soit elle n'était interceptée nulle part du
# tout (`_run_wizard_eject`, `_perform_eject`, `_on_eject_requested`) --
# menant au message trompeur « ferme les fichiers ouverts... » ou à un
# plantage silencieux selon le chemin. `_start_eject` intercepte
# maintenant `runner.start()` lui-même et route toujours vers `on_finished`.


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_eject_maps_elevation_refused_error_to_dedicated_code(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    device = _make_device()
    results = []

    def _factory(argv, parent=None, macos_auth_session=None):
        instance = MagicMock()
        instance.argv = argv
        instance.start.side_effect = elevate.ElevationRefusedError("invite UAC refusée")
        return instance

    with patch("r36s_studio.gui.main_window.WorkerRunner", side_effect=_factory):
        window._start_eject(device, lambda ok, code, msg: results.append((ok, code, msg)))

    ok, code, msg = results[-1]
    assert ok is False
    assert code == "ELEVATION_REFUSED"
    assert "invite UAC refusée" in msg
    # Ne doit jamais laisser l'interface bloquée « occupée » sans issue.
    assert window._home._busy is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_eject_maps_other_start_failures_to_eject_failed(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    device = _make_device()
    results = []

    def _factory(argv, parent=None, macos_auth_session=None):
        instance = MagicMock()
        instance.argv = argv
        instance.start.side_effect = OSError("exécutable introuvable")
        return instance

    with patch("r36s_studio.gui.main_window.WorkerRunner", side_effect=_factory):
        window._start_eject(device, lambda ok, code, msg: results.append((ok, code, msg)))

    ok, code, msg = results[-1]
    assert ok is False
    assert code == "EJECT_FAILED"
    assert "exécutable introuvable" in msg


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_on_eject_requested_shows_the_elevation_refused_friendly_message(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._device = _make_device()

    def _factory(argv, parent=None, macos_auth_session=None):
        instance = MagicMock()
        instance.argv = argv
        instance.start.side_effect = elevate.ElevationRefusedError("invite UAC refusée")
        return instance

    with patch("r36s_studio.gui.main_window.WorkerRunner", side_effect=_factory):
        window._on_eject_requested()

    log_text = window._log_panel._log_view.toPlainText()
    assert "L'autorisation Windows a été refusée" in log_text
    assert "Ferme les fichiers ouverts" not in log_text  # jamais le message générique pour ce cas


# --- flash Android : avertissement + éjection automatique (§4.6) -----------
# Windows ne sait lire aucune partition d'une image Android (boot/system/
# vendor/userdata...) et propose de les formater dès qu'il les découvre --
# un débutant risque d'accepter et de détruire ce qui vient d'être écrit.


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_is_flashing_android_firmware_true_for_android_entries(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._mode = "flash"

    for firmware_id in ("r36droid", "andr36oid"):
        window._app_config.firmware = firmware_id
        assert window._is_flashing_android_firmware() is True

    window._app_config.firmware = "rocknix"
    assert window._is_flashing_android_firmware() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_is_flashing_android_firmware_false_outside_flash_mode(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._app_config.firmware = "r36droid"
    window._mode = "backup"

    assert window._is_flashing_android_firmware() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_is_flashing_android_firmware_false_during_wizard(mock_list, mock_filter, mock_load, qapp):
    """Le parcours de clonage du mode assisté n'a pas de choix de firmware
    (il restaure la propre sauvegarde de l'utilisateur, §5) --
    `_app_config.firmware` n'a alors aucun rapport avec ce qui est
    réellement écrit, même si sa valeur mémorisée est un firmware
    Android d'une session précédente en mode expert."""
    window = MainWindow()
    window._app_config.firmware = "r36droid"
    window._mode = "flash"
    window._wizard_active = True

    assert window._is_flashing_android_firmware() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_flash_may_trigger_windows_format_prompt_true_for_any_expert_flash(
    mock_list, mock_filter, mock_load, qapp
):
    """Aucune entrée du catalogue n'est entièrement lisible par Windows
    (§4.6) -- vrai pour tout flash mode expert, pas seulement Android,
    contrairement à `_is_flashing_android_firmware`."""
    window = MainWindow()
    window._mode = "flash"

    for firmware_id in ("rocknix", "arkos", "emuelec", "amberelec", "minui", "r36droid", "andr36oid"):
        window._app_config.firmware = firmware_id
        assert window._flash_may_trigger_windows_format_prompt() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_flash_may_trigger_windows_format_prompt_false_outside_flash_mode(
    mock_list, mock_filter, mock_load, qapp
):
    window = MainWindow()
    window._mode = "backup"

    assert window._flash_may_trigger_windows_format_prompt() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_flash_may_trigger_windows_format_prompt_false_during_wizard(
    mock_list, mock_filter, mock_load, qapp
):
    """Le parcours de clonage éjecte déjà la carte neuve à l'étape 5,
    immédiatement après la restauration -- pas besoin de ce mécanisme en
    plus."""
    window = MainWindow()
    window._mode = "flash"
    window._wizard_active = True

    assert window._flash_may_trigger_windows_format_prompt() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_worker_appends_eject_after_for_android_firmware(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/r36droid.img"
    window._app_config.firmware = "r36droid"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--eject-after" in runner_class.instances[0].argv


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_worker_appends_eject_after_for_non_android_firmware_too(mock_list, mock_filter, mock_load, qapp):
    """Constaté en usage réel : la même boîte « Vous devez formater le
    disque » apparaît aussi après un flash ROCKNIX/ArkOS/EmuELEC/AmberELEC/
    MinUI (une seule boîte, pour leur partition ext4 -- §4.6), pas
    seulement pour Android. Toute entrée du catalogue en bénéficie
    désormais, `_is_flashing_android_firmware` restant réservé au choix du
    message (détaillé pour Android, générique sinon)."""
    window = MainWindow()
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/rocknix.img"
    window._app_config.firmware = "rocknix"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--eject-after" in runner_class.instances[0].argv


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_worker_does_not_append_eject_after_outside_flash_mode(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--eject-after" not in runner_class.instances[0].argv


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_worker_does_not_append_eject_after_during_wizard(mock_list, mock_filter, mock_load, qapp):
    """Le parcours de clonage éjecte déjà la carte neuve à l'étape 5
    (`_run_wizard_eject`), immédiatement après la restauration -- une
    seconde éjection via `--eject-after` ferait double emploi."""
    window = MainWindow()
    window._mode = "flash"
    window._wizard_active = True
    window._device = _make_device()
    window._file_path = "/tmp/clone.img"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert "--eject-after" not in runner_class.instances[0].argv


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_android_flash_success_warns_and_hides_eject_button(mock_list, mock_filter, mock_load, qapp):
    """Éjectée automatiquement par le worker (`--eject-after`) -- proposer
    de l'éjecter à nouveau serait redondant. Le message d'avertissement,
    lui, reste affiché même si l'éjection automatique a réussi (§4.6 :
    aucune garantie de gagner la course contre les fenêtres de Windows, et
    aucune protection si la carte est un jour rebranchée ailleurs). Le
    message sur les écrans de rechange (dossier "Panels" du BOOT, §4.6)
    doit aussi apparaître -- constaté en usage réel qu'un écran figé sans
    cette explication laisse un débutant croire que le logiciel ne marche
    pas."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/r36droid.img"
    window._app_config.firmware = "r36droid"

    window._on_worker_finished(True)

    log_text = window._log_panel._log_view.toPlainText()
    assert "formater" in log_text.lower()
    assert "panels" in log_text.lower()
    assert window._log_panel._eject_button.isVisible() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_non_android_flash_success_warns_generically_and_hides_eject_button(
    mock_list, mock_filter, mock_load, qapp
):
    """Constaté en usage réel : la même boîte « Vous devez formater le
    disque » apparaît aussi après un flash ROCKNIX (une seule boîte, pour
    sa partition ext4, §4.6) -- pas seulement Android. Message générique
    (sans le détail des partitions multiples ni le mécanisme d'écran de
    rechange, propres à Android), et bouton Éjecter masqué comme pour
    Android : déjà éjectée par `--eject-after`."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/rocknix.img"
    window._app_config.firmware = "rocknix"

    window._on_worker_finished(True)

    log_text = window._log_panel._log_view.toPlainText()
    assert "formater" in log_text.lower()
    assert "panels" not in log_text.lower()  # mécanisme propre à Android, pas ici
    assert window._log_panel._eject_button.isVisible() is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_flash_success_shows_eject_button_when_chained_eject_actually_failed(
    mock_list, mock_filter, mock_load, qapp
):
    """Bug corrigé, confirmé sur du vrai matériel : le bouton Éjecter
    restait masqué même quand l'éjection chaînée (`flash --eject-after`)
    avait réellement échoué (best-effort côté CLI, jamais fatal pour le
    flash) -- l'utilisateur devait alors passer par l'étape F séparée,
    une invite UAC dédiée en plus, minutes plus tard. `_flash_ejected`
    (rempli par `_on_flash_eject_result`, connecté au signal `eject_result`
    du worker) doit désormais réafficher ce bouton quand ce résultat est
    connu et négatif."""
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/rocknix.img"
    window._app_config.firmware = "rocknix"
    window._flash_ejected = False

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_start_worker_resets_flash_ejected_and_connects_eject_result_signal(
    mock_list, mock_filter, mock_load, qapp
):
    window = MainWindow()
    window._flash_ejected = False  # état périmé d'une opération précédente
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/rocknix.img"
    window._app_config.firmware = "rocknix"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()

    assert window._flash_ejected is None  # remis à neuf avant le nouveau worker
    assert "--eject-after" in runner_class.instances[0].argv
    runner_class.instances[0].eject_result.connect.assert_called_once_with(window._on_flash_eject_result)


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_on_flash_eject_result_stores_outcome(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()

    window._on_flash_eject_result(True, "")
    assert window._flash_ejected is True

    window._on_flash_eject_result(False, "carte occupée")
    assert window._flash_ejected is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_restore_image_destination_too_small_shows_error_without_opening_confirm_dialog(
    mock_list, mock_filter, mock_load, qapp
):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)
    window._wizard_target_device = _make_device(size_bytes=1_000_000)
    window._file_path = "/home/x/clone.img"

    with patch("r36s_studio.gui.main_window.estimate_total_bytes", return_value=2_000_000):
        window._enter_wizard_job(WizardJob.RESTORE_IMAGE)

    assert window._confirm_dialog.isVisible() is False
    assert window._last_error_code == "DESTINATION_TOO_SMALL"
    assert window._wizard_panel._resume_button.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_choosing_rocknix_persists_firmware_to_config(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()

    window._file_dialog.firmware_changed.emit("rocknix")

    assert window._app_config.firmware == "rocknix"
    mock_save.assert_called_once()
    assert mock_save.call_args[0][0].firmware == "rocknix"


# --- téléchargement automatique ROCKNIX (§5, étape de flash) ---------------
#
# `RocknixListRunner`/`RocknixDownloadRunner` (partition_runner.py) sont
# mockés ici -- aucun accès réseau réel, même principe que
# `PartitionJobRunner`/`WorkerRunner` mockés ailleurs dans ce fichier. Une
# vraie release ROCKNIX peut publier plusieurs variantes à la fois (§5,
# CLAUDE.md) : le parcours passe donc par une recherche (RocknixListRunner)
# puis une fenêtre de choix (RocknixVariantDialog) avant le téléchargement
# proprement dit (RocknixDownloadRunner) -- jamais une sélection automatique.


def _mock_rocknix_runner_class():
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


def _rocknix_variant(name, sha=None):
    from r36s_studio.identify.rocknix import RocknixAsset

    return RocknixAsset(name=name, download_url=f"https://example.invalid/{name}", size_bytes=100), sha


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_download_requested_starts_list_runner_and_marks_busy(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    runner_class = _mock_rocknix_runner_class()

    with patch("r36s_studio.gui.main_window.RocknixListRunner", runner_class):
        window._file_dialog.rocknix_download_requested.emit()

    runner_class.assert_called_once_with(parent=window)
    assert window._home._tiles["flash"].isEnabled() is False  # occupé pendant la recherche
    runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_list_finished_opens_variant_dialog_with_both_candidates(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    variant_a = _rocknix_variant("ROCKNIX-RK3326.aarch64-20260801-a.img.gz")
    variant_b = _rocknix_variant("ROCKNIX-RK3326.aarch64-20260801-b.img.gz")

    window._on_rocknix_list_finished([variant_a, variant_b])

    assert window._rocknix_variant_dialog.isVisible() is True
    assert window._rocknix_variant_dialog._list.count() == 2
    assert window._home._tiles["flash"].isEnabled() is True  # plus occupé, la fenêtre de choix prend le relais


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_list_finished_with_no_candidates_shows_error(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    window._last_error_code = "ROCKNIX_ASSET_NOT_FOUND"

    window._on_rocknix_list_finished([])

    assert window._rocknix_variant_dialog.isVisible() is False
    log_text = window._log_panel._log_view.toPlainText()
    assert "trouver la version ROCKNIX" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_choosing_a_variant_starts_download_runner_with_that_asset(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    variant_b = _rocknix_variant("ROCKNIX-RK3326.aarch64-20260801-b.img.gz", sha="cafebabe" * 8)
    runner_class = _mock_rocknix_runner_class()

    with patch("r36s_studio.gui.main_window.RocknixDownloadRunner", runner_class):
        window._rocknix_variant_dialog.variant_chosen.emit(*variant_b)

    runner_class.assert_called_once_with(variant_b[0], variant_b[1], parent=window)
    assert window._rocknix_variant_dialog.isVisible() is False
    assert window._home._tiles["flash"].isEnabled() is False  # occupé pendant le téléchargement
    runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_download_success_opens_confirm_dialog_with_downloaded_path(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    window = MainWindow()
    device = _make_device()
    window._device = device
    window._mode = "flash"

    window._on_rocknix_download_finished(True, "/tmp/ROCKNIX-RK3326.aarch64-20260801-a.img.gz")

    assert window._file_path == "/tmp/ROCKNIX-RK3326.aarch64-20260801-a.img.gz"
    assert window._confirm_dialog.isVisible() is True
    assert window._home._tiles["flash"].isEnabled() is True  # plus occupé, la fenêtre Confirmation prend le relais


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_download_failure_shows_friendly_message_in_log_panel(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    window._last_error_code = "ROCKNIX_CHECKSUM_MISMATCH"

    window._on_rocknix_download_finished(False, "")

    log_text = window._log_panel._log_view.toPlainText()
    assert "corrompu ou incomplet" in log_text
    assert window._confirm_dialog.isVisible() is False


# --- Tuile personnelle « Web » (config.py::personal_web_url) ---------------
# Réservée à l'auteur du projet -- jamais visible dans la version
# distribuée à un client (aucune valeur par défaut, aucune persistance).


@patch("r36s_studio.gui.main_window.app_config.personal_web_url", return_value="https://nonotrichlozz.github.io/mon-dashboard/")
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_web_tile_visible_in_both_modes_when_url_configured(mock_list, mock_filter, mock_web_url, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    # `_home` vit dans `_main_view` (mode expert) -- pas l'écran actif par
    # défaut (mode assisté) : un widget non courant d'un `QStackedWidget`
    # reste caché quel que soit `setVisible`, il faut donc le rendre actif
    # pour que `isVisible()` reflète l'appel fait à la construction.
    assert window._assisted_landing._web_tile.isVisible() is True
    window._root_stack.setCurrentWidget(window._main_view)
    assert window._home._web_row.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.personal_web_url", return_value=None)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_web_tile_hidden_in_both_modes_when_url_not_configured(mock_list, mock_filter, mock_web_url, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    assert window._assisted_landing._web_tile.isVisible() is False
    window._root_stack.setCurrentWidget(window._main_view)
    assert window._home._web_row.isVisible() is False


@patch("r36s_studio.gui.main_window.QDesktopServices.openUrl")
@patch("r36s_studio.gui.main_window.app_config.personal_web_url", return_value="https://nonotrichlozz.github.io/mon-dashboard/")
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_web_requested_from_home_opens_configured_url(mock_list, mock_filter, mock_web_url, mock_open_url, qapp):
    window = MainWindow()

    window._home.web_requested.emit()

    mock_open_url.assert_called_once()
    (opened_url,), _kwargs = mock_open_url.call_args
    assert opened_url.toString() == "https://nonotrichlozz.github.io/mon-dashboard/"


@patch("r36s_studio.gui.main_window.QDesktopServices.openUrl")
@patch("r36s_studio.gui.main_window.app_config.personal_web_url", return_value="https://nonotrichlozz.github.io/mon-dashboard/")
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_web_requested_from_assisted_landing_opens_same_url(mock_list, mock_filter, mock_web_url, mock_open_url, qapp):
    window = MainWindow()

    window._assisted_landing.web_requested.emit()

    mock_open_url.assert_called_once()
    (opened_url,), _kwargs = mock_open_url.call_args
    assert opened_url.toString() == "https://nonotrichlozz.github.io/mon-dashboard/"


@patch("r36s_studio.gui.main_window.QDesktopServices.openUrl")
@patch("r36s_studio.gui.main_window.app_config.personal_web_url", return_value=None)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_web_requested_does_nothing_when_url_not_https(mock_list, mock_filter, mock_web_url, mock_open_url, qapp):
    """Défense en profondeur : `personal_web_url()` est relue au clic --
    une valeur devenue invalide (ou absente) entre le démarrage et le
    clic ne doit jamais ouvrir quoi que ce soit, jamais planter non plus."""
    window = MainWindow()

    window._home.web_requested.emit()

    mock_open_url.assert_not_called()
