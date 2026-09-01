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
    l'écran expert -- réutilise HomeScreen/MainView le temps de
    l'opération (journal de bord, états occupé) sans en faire un vrai
    changement de mode persisté."""
    window = MainWindow()
    assert window._root_stack.currentWidget() is window._assisted_landing

    window._assisted_landing.backup_system_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._home
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
        window._assisted_landing.backup_system_requested.emit()

    mock_save.assert_not_called()
    assert window._app_config.ui_mode == "assisted"


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


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_flow_requires_confirmation_before_worker_starts(mock_list, mock_filter, mock_detect, qapp):
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
    assert argv == ["flash", "--image", "/tmp/sd.img", "--device", "/dev/fake-disk-test-3"]


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
def test_start_worker_pauses_console_stage_and_resumes_on_finish(mock_list, mock_filter, qapp):
    """§5 (animations console) : mises en pause pendant une opération
    disque pour ne pas consommer de ressources, reprises à la fin."""
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    window._console_stage = MagicMock()
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
        window._console_stage.pause.assert_called_once()
        window._console_stage.resume.assert_not_called()

        window._on_worker_finished(True)

    window._console_stage.resume.assert_called_once()


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
def test_worker_success_logs_message_and_shows_eject_for_flash(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché (MainWindow, pas un descendant)
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/sd.img"

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is True
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


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_requested_calls_eject_module_with_device_path(mock_list, mock_filter, mock_eject, qapp):
    window = MainWindow()
    window._device = _make_device(path="/dev/fake-disk-test-3")

    window._on_eject_requested()

    mock_eject.assert_called_once_with("/dev/fake-disk-test-3")


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


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_flow_is_immediate_and_confirms_success(mock_list, mock_filter, mock_detect, mock_eject, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()
    window._home.eject_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    mock_eject.assert_called_once_with(device.path)
    assert "retirée en toute sécurité" in window._log_panel._log_view.toPlainText()
    assert window._file_dialog.isVisible() is False  # étape F : aucune fenêtre Fichier


@patch("r36s_studio.gui.main_window.eject_device", side_effect=OSError("carte occupée"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_flow_logs_friendly_error_and_raw_detail_on_failure(mock_list, mock_filter, mock_detect, mock_eject, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()
    window._home.eject_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

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
# enchaîne 7 étapes (gui/wizard_flow.py) sur la même MainView que le mode
# expert (colonne gauche remplacée par WizardStepPanel).

from r36s_studio.gui.wizard_flow import WizardJob


def _mock_identify_runner_class():
    instances = []

    def _factory(device_path, parent=None):
        instance = MagicMock()
        instance.device_path = device_path
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


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


@patch(
    "r36s_studio.detect.list_partitions",
    return_value=[
        PartitionInfo("/dev/fake-disk-test-3s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-3s3", "EASYROMS", "ntfs", None),
    ],
)
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_continue_on_step_one_advances_to_identify_and_starts_identify_runner(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, mock_partitions, qapp
):
    device = _make_device()
    identify_runner_class = _mock_identify_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, device, "fp-source")

    with patch("r36s_studio.gui.main_window.WizardIdentifyRunner", identify_runner_class):
        window._wizard_panel.continue_requested.emit()

    assert window._wizard_flow.is_done(WizardJob.DETECT_SOURCE) is True
    assert window._wizard_flow.current_job() == WizardJob.IDENTIFY
    identify_runner_class.assert_called_once_with(device.path, parent=window)
    identify_runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_success_enables_continue_and_logs_result(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_panel._continue_button.setEnabled(False)

    info = DtbInfo(board_compatible="rk3326-evb-lp3-v12", panel_compatible="sitronix,st7703", timings={})
    window._on_wizard_identify_finished(IdentifyResult(info=info))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "rk3326-evb-lp3-v12" in log_text


# --- console clone détectée à l'identification (§5 mode assisté, étape 2) --
# --- critère validé par l'outil officiel ArkOS (identify/__init__.py) ------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_clone_detected_logs_a_clear_warning(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    info = DtbInfo(board_compatible="rk3326-evb-lp3-v12", panel_compatible="sitronix,st7703", timings={})
    window._on_wizard_identify_finished(IdentifyResult(info=info, is_clone=True))

    log_text = window._log_panel._log_view.toPlainText()
    assert "clone" in log_text.lower()
    assert "EmuELEC" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_clone_flag_remembered_for_the_flash_step(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    info = DtbInfo(board_compatible="rk3326-evb-lp3-v12", panel_compatible="sitronix,st7703", timings={})
    window._on_wizard_identify_finished(IdentifyResult(info=info, is_clone=True))

    assert window._wizard_source_is_clone is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_non_clone_does_not_set_clone_flag(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    info = DtbInfo(board_compatible="rk3326-r35s", panel_compatible="sitronix,st7703", timings={})
    window._on_wizard_identify_finished(IdentifyResult(info=info, is_clone=False))

    assert window._wizard_source_is_clone is False
    log_text = window._log_panel._log_view.toPlainText()
    assert "clone" not in log_text.lower()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_starting_a_new_wizard_resets_the_clone_flag(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._wizard_source_is_clone = True

    window._assisted_landing.prepare_requested.emit()

    assert window._wizard_source_is_clone is False


# --- échec d'identification : trois causes distinctes, trois messages -----


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_mount_failed_suggests_a_faulty_card(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_identify_finished(IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "défaillante" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_no_dtb_found_message_differs_from_mount_failed(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_identify_finished(IdentifyResult(failure_reason=IdentifyFailureReason.NO_DTB_FOUND))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "défaillante" not in log_text
    assert "fraîchement flashée" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_invalid_dtb_message_differs_from_the_other_two(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_identify_finished(IdentifyResult(failure_reason=IdentifyFailureReason.ALL_DTB_INVALID))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "défaillante" not in log_text
    assert "fraîchement flashée" not in log_text
    assert "illisible, corrompu" in log_text


# --- journal : chemin examiné et fichiers .dtb, dans tous les cas ---------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_logs_scanned_directory_and_examined_files_on_success(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    info = DtbInfo(board_compatible="rk3326-evb-lp3-v12", panel_compatible="sitronix,st7703", timings={})
    result = IdentifyResult(info=info, scanned_directory="/Volumes/BOOT", examined_files=["/Volumes/BOOT/board.dtb"])
    window._on_wizard_identify_finished(result)

    log_text = window._log_panel._log_view.toPlainText()
    assert "/Volumes/BOOT" in log_text
    assert "board.dtb" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_logs_scanned_directory_and_examined_files_on_no_dtb_found(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    result = IdentifyResult(
        failure_reason=IdentifyFailureReason.NO_DTB_FOUND,
        scanned_directory="/Volumes/BOOT",
        examined_files=[],
    )
    window._on_wizard_identify_finished(result)

    log_text = window._log_panel._log_view.toPlainText()
    assert "/Volumes/BOOT" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_logs_raw_detail_on_mount_failed(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    result = IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED, detail="délai dépassé sur /dev/x")
    window._on_wizard_identify_finished(result)

    log_text = window._log_panel._log_view.toPlainText()
    assert "délai dépassé sur /dev/x" in log_text


# --- étape 2 : adaptation au système détecté sur la carte source (§4.5) ----
# ROCKNIX ne gère pas le BOOT/EASYROMS comme ArkOS (structure réelle relevée
# sur du vrai matériel : MBR, 2 partitions -- ROCKNIX en FAT32 et une
# partition Linux opaque, aucune partition de jeux séparée) : les étapes
# 2/3 sont sautées automatiquement. Un système non reconnu, en revanche,
# affiche un avertissement et laisse l'utilisateur choisir via Continuer --
# jamais un aller simple vers le mode expert dans un cas comme dans l'autre.

from r36s_studio.detect import CardSystem


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.eject_device")
def test_wizard_rocknix_source_skips_identify_and_extraction_with_explanation(
    mock_eject, mock_list, mock_filter, mock_load, qapp
):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_source_system = CardSystem.ROCKNIX
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")

    window._enter_wizard_job(WizardJob.IDENTIFY)

    log_text = window._log_panel._log_view.toPlainText()
    assert "ROCKNIX" in log_text
    assert window._wizard_flow.is_done(WizardJob.IDENTIFY) is True
    assert window._wizard_flow.is_done(WizardJob.EXTRACT_BOOT) is True
    assert window._wizard_flow.is_done(WizardJob.EXTRACT_EASYROMS) is True
    assert window._wizard_flow.current_job() == WizardJob.DETECT_TARGET


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_unknown_source_shows_warning_and_waits_for_continue(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_source_system = CardSystem.UNKNOWN

    window._enter_wizard_job(WizardJob.IDENTIFY)

    log_text = window._log_panel._log_view.toPlainText()
    assert "Impossible de reconnaître le système" in log_text
    assert window._wizard_panel._continue_button.isEnabled() is True
    # Rien n'est encore sauté -- contrairement à ROCKNIX, l'utilisateur doit
    # activement choisir de continuer.
    assert window._wizard_flow.is_done(WizardJob.EXTRACT_BOOT) is False


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.eject_device")
def test_wizard_continue_after_unknown_warning_skips_extraction(mock_eject, mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_source_system = CardSystem.UNKNOWN
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    window._enter_wizard_job(WizardJob.IDENTIFY)

    window._wizard_panel.continue_requested.emit()

    assert window._wizard_flow.is_done(WizardJob.IDENTIFY) is True
    assert window._wizard_flow.is_done(WizardJob.EXTRACT_BOOT) is True
    assert window._wizard_flow.is_done(WizardJob.EXTRACT_EASYROMS) is True
    assert window._wizard_flow.current_job() == WizardJob.DETECT_TARGET
    assert window._wizard_skip_extraction_on_continue is False  # remis à plat


@patch("r36s_studio.detect.list_partitions", return_value=[PartitionInfo("/dev/x1", "ROCKNIX", "fat32", None)])
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_fingerprint_ready_stores_detected_rocknix_system(
    mock_list, mock_filter, mock_load, mock_partitions, qapp
):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, _make_device(), "fp-source")

    assert window._wizard_source_system == CardSystem.ROCKNIX


# --- étape 6 : rien à réinjecter si l'extraction a été sautée ------------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_inject_boot_skipped_when_no_boot_archive(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    device = _make_device()
    window._wizard_target_device = device
    window._wizard_boot_archive = None  # extraction sautée (ROCKNIX ou non reconnue)
    window._wizard_flow.reset()
    for job in (
        WizardJob.DETECT_SOURCE,
        WizardJob.IDENTIFY,
        WizardJob.EXTRACT_BOOT,
        WizardJob.EXTRACT_EASYROMS,
        WizardJob.DETECT_TARGET,
        WizardJob.FLASH,
    ):
        window._wizard_flow.mark_done(job)
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_job(WizardJob.INJECT_BOOT)

    runner_class.assert_not_called()
    assert window._wizard_flow.is_done(WizardJob.INJECT_BOOT) is True
    assert window._wizard_flow.current_job() == WizardJob.EJECT
    log_text = window._log_panel._log_view.toPlainText()
    assert "ignorée" in log_text


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_inject_boot_runs_normally_when_archive_present(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    device = _make_device()
    window._wizard_target_device = device
    window._wizard_boot_archive = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._wizard_flow.reset()
    for job in (
        WizardJob.DETECT_SOURCE,
        WizardJob.IDENTIFY,
        WizardJob.EXTRACT_BOOT,
        WizardJob.EXTRACT_EASYROMS,
        WizardJob.DETECT_TARGET,
        WizardJob.FLASH,
    ):
        window._wizard_flow.mark_done(job)
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_job(WizardJob.INJECT_BOOT)

    runner_class.assert_called_once_with("inject_boot", device, window._wizard_boot_archive, parent=window)


# --- étapes A/B : réutiliser une sauvegarde déjà connue pour la carte -----
# --- source (§5 mode assisté) plutôt que de tout recopier à nouveau ------
#
# Chaque test construit sa propre AppConfig fraîche (jamais _EXPERT_MODE_
# CONFIG, un singleton partagé entre tests -- le muter ici polluerait les
# autres tests qui le réutilisent).


def _config_with_archive_record(fingerprint, label, path, created_at="2026-07-06T00:21:00"):
    cfg = AppConfig(ui_mode="expert")
    app_config.set_archive_record(cfg, fingerprint, label, path, created_at=datetime.fromisoformat(created_at))
    return cfg


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_extraction_step_opens_reuse_dialog_when_a_valid_record_exists(mock_list, mock_filter, qapp, tmp_path):
    existing = tmp_path / "BOOT_2026-07-06_00-21"
    existing.mkdir()
    cfg = _config_with_archive_record("fp-source", "BOOT", str(existing))

    with patch("r36s_studio.gui.main_window.app_config.load_config", return_value=cfg):
        window = MainWindow()
    window.show()
    window._wizard_source_fingerprint = "fp-source"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_extraction_step(WizardJob.EXTRACT_BOOT)

    runner_class.assert_not_called()
    assert window._archive_reuse_dialog.isVisible() is True
    assert str(existing) in window._archive_reuse_dialog._message.text()


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_extraction_step_ignores_stale_record_when_path_no_longer_exists(mock_list, mock_filter, qapp, tmp_path):
    """L'utilisateur a pu déplacer ou supprimer l'archive depuis --
    `config.py` ne mémorise qu'un chemin, jamais une garantie de
    présence : ne jamais proposer un dossier qui n'existe plus."""
    missing = tmp_path / "BOOT_gone"  # jamais créé
    cfg = _config_with_archive_record("fp-source", "BOOT", str(missing))

    with patch("r36s_studio.gui.main_window.app_config.load_config", return_value=cfg):
        window = MainWindow()
    window._wizard_source_fingerprint = "fp-source"
    window._wizard_source_device = _make_device()
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_extraction_step(WizardJob.EXTRACT_BOOT)

    assert window._archive_reuse_dialog.isVisible() is False
    runner_class.assert_called_once()  # repart directement sur une nouvelle extraction


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_extraction_step_runs_directly_without_any_record(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._wizard_source_fingerprint = "fp-source-without-record"
    window._wizard_source_device = _make_device()
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_extraction_step(WizardJob.EXTRACT_EASYROMS)

    assert window._archive_reuse_dialog.isVisible() is False
    runner_class.assert_called_once()


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
@patch("r36s_studio.gui.main_window.eject_device")
def test_reuse_requested_sets_archive_and_advances_without_running_the_job(
    mock_eject, mock_list, mock_filter, qapp, tmp_path
):
    existing = tmp_path / "EASYROMS_2026-07-06_00-25"
    existing.mkdir()
    cfg = _config_with_archive_record("fp-source", "EASYROMS", str(existing))

    with patch("r36s_studio.gui.main_window.app_config.load_config", return_value=cfg):
        window = MainWindow()
    window._wizard_source_fingerprint = "fp-source"
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_flow.reset()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_flow.mark_done(WizardJob.IDENTIFY)
    window._wizard_flow.mark_done(WizardJob.EXTRACT_BOOT)
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_extraction_step(WizardJob.EXTRACT_EASYROMS)
        window._archive_reuse_dialog.reuse_requested.emit()

    runner_class.assert_not_called()
    assert window._wizard_easyroms_archive == str(existing)
    assert window._wizard_flow.is_done(WizardJob.EXTRACT_EASYROMS) is True
    assert window._wizard_flow.current_job() == WizardJob.DETECT_TARGET
    log_text = window._log_panel._log_view.toPlainText()
    assert str(existing) in log_text


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_redo_requested_runs_the_partition_job_with_a_freshly_generated_path(mock_list, mock_filter, qapp, tmp_path):
    existing = tmp_path / "BOOT_2026-07-06_00-21"
    existing.mkdir()
    cfg = _config_with_archive_record("fp-source", "BOOT", str(existing))

    with patch("r36s_studio.gui.main_window.app_config.load_config", return_value=cfg):
        window = MainWindow()
    window.show()
    window._wizard_source_fingerprint = "fp-source"
    window._wizard_source_device = _make_device()
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_extraction_step(WizardJob.EXTRACT_BOOT)
        window._archive_reuse_dialog._redo_button.click()

    runner_class.assert_called_once()
    assert window._archive_reuse_dialog.isVisible() is False


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_reuse_cancelled_cancels_the_whole_wizard(mock_list, mock_filter, qapp, tmp_path):
    existing = tmp_path / "BOOT_2026-07-06_00-21"
    existing.mkdir()
    cfg = _config_with_archive_record("fp-source", "BOOT", str(existing))

    with patch("r36s_studio.gui.main_window.app_config.load_config", return_value=cfg):
        window = MainWindow()
    window._wizard_source_fingerprint = "fp-source"
    window._wizard_active = True
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)

    window._enter_wizard_extraction_step(WizardJob.EXTRACT_BOOT)
    window._archive_reuse_dialog.cancelled.emit()

    assert window._wizard_active is False
    assert window._root_stack.currentWidget() is window._assisted_landing


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_successful_extraction_persists_archive_record_to_config(mock_list, mock_filter, qapp):
    # `_on_wizard_job_finished` avance de lui-même vers l'étape suivante
    # (EXTRACT_EASYROMS) une fois EXTRACT_BOOT marqué fait -- `PartitionJobRunner`
    # doit donc être mocké ici aussi, sans quoi ce test lancerait pour de
    # vrai un job avec un périphérique source jamais défini (`None`).
    cfg = AppConfig(ui_mode="expert")
    runner_class = _mock_partition_runner_class()
    with patch("r36s_studio.gui.main_window.app_config.load_config", return_value=cfg), patch(
        "r36s_studio.gui.main_window.app_config.save_config"
    ) as mock_save, patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._wizard_source_fingerprint = "fp-source"
        window._wizard_source_device = _make_device()
        window._mode = "extract_boot"
        window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
        window._wizard_flow.reset()
        window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
        window._wizard_flow.mark_done(WizardJob.IDENTIFY)

        window._on_wizard_job_finished(True)

    record = app_config.get_archive_record(window._app_config, "fp-source", "BOOT")
    assert record["path"] == "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    mock_save.assert_called_once_with(window._app_config)


# --- étapes 3->4 : éjection de la carte source avant d'inviter à la -------
# --- retirer -- elle reste montée pendant les étapes 2/3 (lecture des -----
# --- .dtb, copie BOOT/EASYROMS) puisque c'est de là qu'elles sont lues ; --
# --- l'éjection n'intervient qu'en tout début de l'étape 4, avant la ------
# --- consigne de retrait, et le sondage de la carte neuve n'y démarre -----
# --- qu'une fois cette éjection effectivement réussie. ---------------------


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_entering_detect_target_ejects_the_source_card_first(mock_list, mock_filter, mock_load, mock_eject, qapp):
    window = MainWindow()
    source = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_device = source

    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    mock_eject.assert_called_once_with(source.path)


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_detect_target_confirms_source_card_can_be_removed_after_eject(
    mock_list, mock_filter, mock_load, mock_eject, qapp
):
    window = MainWindow()
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")

    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    log_text = window._log_panel._log_view.toPlainText()
    assert "toute sécurité" in log_text


@patch("r36s_studio.gui.main_window.eject_device", side_effect=OSError("carte occupée"))
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_detect_target_eject_failure_shows_explicit_error_and_no_polling(
    mock_list, mock_filter, mock_load, mock_eject, qapp
):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    for job in (WizardJob.DETECT_SOURCE, WizardJob.IDENTIFY, WizardJob.EXTRACT_BOOT, WizardJob.EXTRACT_EASYROMS):
        window._wizard_flow.mark_done(job)

    window._enter_wizard_job(WizardJob.DETECT_TARGET)

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
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    for job in (WizardJob.DETECT_SOURCE, WizardJob.IDENTIFY, WizardJob.EXTRACT_BOOT, WizardJob.EXTRACT_EASYROMS):
        window._wizard_flow.mark_done(job)

    with patch("r36s_studio.gui.main_window.eject_device", side_effect=OSError("carte occupée")):
        window._enter_wizard_job(WizardJob.DETECT_TARGET)
    assert window._wizard_poll_timer.isActive() is False

    with patch("r36s_studio.gui.main_window.eject_device") as mock_eject:
        window._wizard_panel.resume_requested.emit()

    mock_eject.assert_called_once_with("/dev/fake-disk-test-source")
    assert window._wizard_poll_timer.isActive() is True


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_source_card_stays_mounted_during_identify_step(mock_list, mock_filter, mock_load, mock_eject, qapp):
    """La carte source n'est éjectée qu'à l'entrée de l'étape 4 -- elle
    reste montée pendant l'étape 2 (identification, lit les .dtb depuis
    cette même carte)."""
    window = MainWindow()
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_system = CardSystem.ARKOS
    identify_runner_class = _mock_identify_runner_class()

    with patch("r36s_studio.gui.main_window.WizardIdentifyRunner", identify_runner_class):
        window._enter_wizard_job(WizardJob.IDENTIFY)

    mock_eject.assert_not_called()


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_source_card_stays_mounted_during_extraction_steps(mock_list, mock_filter, mock_load, mock_eject, qapp):
    """Même garantie pendant l'étape 3 (copie du BOOT/EASYROMS depuis la
    carte source) : `PartitionJobRunner` est mocké ici, donc le job ne se
    termine jamais dans ce test -- l'étape 4 (et son éjection) n'est
    jamais atteinte."""
    window = MainWindow()
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")
    window._wizard_source_fingerprint = "fp-source-no-record"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window._enter_wizard_job(WizardJob.EXTRACT_BOOT)

    mock_eject.assert_not_called()


# --- étape 4 : garde-fou par empreinte de contenu, pas path/size_bytes -----


def _target_setup(window, device):
    window._wizard_flow.reset()
    for job in (WizardJob.DETECT_SOURCE, WizardJob.IDENTIFY, WizardJob.EXTRACT_BOOT, WizardJob.EXTRACT_EASYROMS):
        window._wizard_flow.mark_done(job)
    window._wizard_source_fingerprint = "fp-source"
    # Entrer dans DETECT_TARGET éjecte désormais la carte source en tout
    # premier -- il lui faut donc un périphérique distinct de la carte
    # cible utilisée par ces tests.
    window._wizard_source_device = _make_device(path="/dev/fake-disk-test-source")


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_four_poll_also_starts_fingerprint_runner(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, mock_eject, qapp
):
    same_card = _make_device(path="/dev/fake-disk-test-9")
    mock_list.return_value = [same_card]
    mock_filter.return_value = [same_card]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    _target_setup(window, same_card)
    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_called_once_with(same_card.path, parent=window)
    assert window._wizard_poll_timer.isActive() is False  # pas de deuxième calcul en parallèle


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_four_refuses_to_continue_when_fingerprint_matches_source(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, mock_eject, qapp
):
    same_card = _make_device(path="/dev/fake-disk-test-9")

    window = MainWindow()
    _target_setup(window, same_card)
    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, same_card, "fp-source")

    assert window._wizard_panel._continue_button.isEnabled() is False
    assert window._wizard_target_device is None
    assert window._wizard_poll_timer.isActive() is True  # continue d'attendre une vraie carte différente


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_four_allows_continue_when_fingerprint_differs(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, mock_eject, qapp
):
    new_card = _make_device(path="/dev/fake-disk-test-9")

    window = MainWindow()
    _target_setup(window, new_card)
    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, new_card, "fp-blank-or-different")

    assert window._wizard_panel._continue_button.isEnabled() is True
    assert window._wizard_target_device is new_card
    assert window._wizard_poll_timer.isActive() is False


# --- reprise après erreur : ne rejoue jamais un job déjà réussi -------------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_resume_after_easyroms_failure_only_reruns_easyroms_not_boot(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
        window._main_view.show_wizard_panel()
        window._root_stack.setCurrentWidget(window._main_view)
        window._wizard_flow.reset()
        window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
        window._wizard_flow.mark_done(WizardJob.IDENTIFY)
        window._wizard_source_device = device
        window._wizard_active = True

        # Étape 3a (BOOT) réussie.
        window._enter_wizard_job(WizardJob.EXTRACT_BOOT)
        window._on_worker_finished(True)
        assert window._wizard_flow.is_done(WizardJob.EXTRACT_BOOT) is True

        # Étape 3b (EASYROMS) échoue.
        assert window._wizard_flow.current_job() == WizardJob.EXTRACT_EASYROMS
        window._on_worker_error("IO_ERROR", "disque plein")
        window._on_worker_finished(False)

        assert window._wizard_flow.is_done(WizardJob.EXTRACT_EASYROMS) is False
        assert window._wizard_panel._resume_button.isVisible() is True

        # Reprendre : ne relance qu'EASYROMS, jamais le BOOT une deuxième fois.
        runner_class.reset_mock()
        runner_class.instances.clear()
        window._wizard_panel.resume_requested.emit()

    runner_class.assert_called_once()
    resume_call_args = runner_class.instances[0]
    assert resume_call_args.mode == "extract_easyroms"
    assert resume_call_args.device is device
    assert "EASYROMS" in resume_call_args.source_path


# --- récapitulatif de fin de parcours : où sont les sauvegardes (§5 mode ----
# --- assisté), et qu'elles sont conservées -- jamais supprimées automatiquement


@patch("r36s_studio.gui.main_window.archives.default_archives_dir")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_finish_shows_archives_summary_with_reveal_button(mock_list, mock_filter, mock_load, mock_dir, qapp):
    from pathlib import Path

    mock_dir.return_value = Path("/home/x/Documents/R36S Studio")
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    window._main_view.show_wizard_panel()
    window._root_stack.setCurrentWidget(window._main_view)  # _log_panel vit dans _main_view
    window._wizard_boot_archive = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._wizard_easyroms_archive = "/home/x/Documents/R36S Studio/EASYROMS_2026-07-06_00-25"

    window._finish_wizard()

    log_text = window._log_panel._log_view.toPlainText()
    assert "conservées" in log_text
    assert "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in log_text
    assert "/home/x/Documents/R36S Studio/EASYROMS_2026-07-06_00-25" in log_text
    assert window._log_panel._reveal_button.isVisible() is True
    # str(mock_dir.return_value), pas un littéral codé en dur : Path("/home/x/...")
    # se sérialise avec des antislashs sous Windows (WindowsPath) -- comparer aux
    # deux côtés la même conversion évite de supposer une convention Unix.
    assert window._log_panel._reveal_path == str(mock_dir.return_value)


@patch("r36s_studio.gui.main_window.reveal")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_finish_reveal_button_opens_the_shared_archives_folder(
    mock_list, mock_filter, mock_load, mock_reveal, qapp
):
    window = MainWindow()
    window._wizard_boot_archive = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._wizard_easyroms_archive = "/home/x/Documents/R36S Studio/EASYROMS_2026-07-06_00-25"

    window._finish_wizard()
    window._log_panel._reveal_button.click()

    mock_reveal.assert_called_once()
    from r36s_studio.partitions import archives

    assert mock_reveal.call_args[0][0] == str(archives.default_archives_dir())


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


# --- bouton "Voir les versions disponibles" (flash, §5 mode assisté) -------


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


# --- choix du firmware (ArkOS/ROCKNIX/EmuELEC) à l'étape de flash (§5) -----


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

    assert window._file_dialog._firmware == "arkos"


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_flash_step_passes_clone_flag_to_file_dialog(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._wizard_target_device = _make_device()
    window._wizard_source_is_clone = True

    window._enter_wizard_flash()

    assert window._file_dialog._emuelec_radio.isChecked() is True
    assert window._file_dialog._clone_warning_label.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_flash_step_no_clone_warning_when_not_a_clone(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._wizard_target_device = _make_device()
    window._wizard_source_is_clone = False

    window._enter_wizard_flash()

    assert window._file_dialog._clone_warning_label.isVisible() is False


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
