"""Tests de navigation de MainWindow (gui/main_window.py) : traverse
l'assistant de bout en bout pour les six étapes du workflow à deux cartes
(§4.4/§4.5) et la sauvegarde complète. `list_devices`,
`detect_workflow_status`, `WorkerRunner`/`PartitionJobRunner`,
`archives` et `eject_device` sont mockés — aucun périphérique réel, aucune
élévation, aucune écriture disque."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.gui.main_window import MainWindow


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

    def _factory(argv, parent=None):
        instance = MagicMock()
        instance.argv = argv
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
def test_backup_flow_reaches_execute_with_correct_argv(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.backup_selected.emit()

        assert window._stack.currentWidget() is window._device_screen
        window._device_screen._list.setCurrentRow(0)
        window._device_screen._emit_chosen()

        assert window._stack.currentWidget() is window._file_screen

        with patch("r36s_studio.gui.screens.QFileDialog.getSaveFileName", return_value=("/tmp/out.img", "")):
            window._file_screen._browse()
        window._file_screen.file_chosen.emit(window._file_screen._path_label.text())

        # Backup n'écrit jamais sur un périphérique : pas d'écran de
        # confirmation, on va directement à l'exécution.
        assert window._stack.currentWidget() is window._execute_screen

    runner_class.assert_called_once()
    argv = runner_class.instances[0].argv
    assert argv == ["backup", "--device", "/dev/fake-disk-test-3", "--output", "/tmp/out.img"]
    runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_flow_requires_confirmation_before_execute(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.flash_selected.emit()
        window._device_screen._list.setCurrentRow(0)
        window._device_screen._emit_chosen()

        with patch(
            "r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")
        ):
            window._file_screen._browse()
        window._file_screen.file_chosen.emit(window._file_screen._path_label.text())

        # Le flash écrit sur le périphérique : confirmation obligatoire.
        assert window._stack.currentWidget() is window._confirm_screen
        runner_class.assert_not_called()

        window._confirm_screen._checkbox.setChecked(True)
        window._confirm_screen.confirmed.emit()

        assert window._stack.currentWidget() is window._execute_screen

    argv = runner_class.instances[0].argv
    assert argv == ["flash", "--image", "/tmp/sd.img", "--device", "/dev/fake-disk-test-3"]


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_confirm_cancel_returns_to_file_screen(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window._home.flash_selected.emit()
    window._device_screen._list.setCurrentRow(0)
    window._device_screen._emit_chosen()
    window._file_screen.file_chosen.emit("/tmp/sd.img")
    assert window._stack.currentWidget() is window._confirm_screen

    window._confirm_screen.cancelled.emit()

    assert window._stack.currentWidget() is window._file_screen


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_success_shows_result_with_eject_for_flash(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois le parent affiché
    window._mode = "flash"
    window._device = device
    window._file_path = "/tmp/sd.img"

    window._on_worker_finished(True)

    assert window._stack.currentWidget() is window._result_screen
    assert window._result_screen._eject_button.isVisible() is True
    assert "prête" in window._result_screen._message.text()


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_error_shows_message_and_cancelled_flag(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_error("CANCELLED", "Sauvegarde annulée après 1024 octets")
    window._on_worker_finished(False)

    assert window._stack.currentWidget() is window._result_screen
    assert "annulée" in window._result_screen._message.text()


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_requested_calls_eject_module_with_device_path(mock_list, mock_filter, mock_eject, qapp):
    window = MainWindow()
    window._device = _make_device(path="/dev/fake-disk-test-3")

    # Le succès affiche désormais une confirmation explicite (§4.5) via une
    # boîte de dialogue modale -- bloquerait indéfiniment sous le mode Qt
    # "offscreen" des tests si elle n'était pas mockée.
    with patch("r36s_studio.gui.main_window.QMessageBox"):
        window._on_eject_requested()

    mock_eject.assert_called_once_with("/dev/fake-disk-test-3")


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_cancel_requested_calls_runner_cancel(mock_list, mock_filter, qapp):
    window = MainWindow()
    fake_runner = MagicMock()
    window._runner = fake_runner

    window._on_cancel_requested()

    fake_runner.cancel.assert_called_once()


# --- Accueil : six étapes toujours visibles, statut informatif (§4.5) ------


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_detects_single_card_and_annotates_home(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    status = _all_status(StepStatus.AVAILABLE)
    mock_detect.return_value = status
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(device)
    # Les six tuiles restent visibles quel que soit le statut (§4.5).
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_with_no_card_still_shows_all_six_tiles(mock_list, mock_filter, mock_detect, qapp):
    mock_list.return_value = []
    mock_filter.return_value = []
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(None)
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_with_multiple_cards_passes_none_to_detection(mock_list, mock_filter, mock_detect, qapp):
    """Cas non couvert par une carte unique : plusieurs cartes candidates
    -- `detect_workflow_status` reçoit `None` (aucune mise en avant
    possible), mais les six tuiles restent affichées normalement."""
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
def test_returning_home_from_result_screen_re_runs_detection(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_detect.return_value = _all_status(StepStatus.AVAILABLE)
    window = MainWindow()
    mock_detect.reset_mock()

    window._result_screen.home_requested.emit()

    mock_detect.assert_called_once_with(device)
    assert window._stack.currentWidget() is window._home


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
        window._device_screen._list.setCurrentRow(0)
        window._device_screen._emit_chosen()

        mock_list_archives.assert_called_once_with("BOOT")
        assert window._stack.currentWidget() is window._file_screen
        assert window._file_screen._archive_list.count() == 1

        window._file_screen._archive_list.setCurrentRow(0)
        window._file_screen.file_chosen.emit(window._file_screen._path_label.text())

        # Ni sauvegarde de fichier ni écrasement de carte : pas de
        # confirmation, exécution directe.
        assert window._stack.currentWidget() is window._execute_screen

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
        window._device_screen._list.setCurrentRow(0)
        window._device_screen._emit_chosen()

        mock_list_archives.assert_called_once_with("EASYROMS")

        with patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/games"):
            window._file_screen._browse()
        window._file_screen.file_chosen.emit(window._file_screen._path_label.text())

    runner_class.assert_called_once_with("copy_games", device, "/tmp/games", parent=window)


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_copy_games_success_message_and_allows_eject(mock_list, mock_filter, qapp):
    window = MainWindow()
    window.show()
    window._mode = "copy_games"
    window._device = _make_device(display="Carte de Léo")

    window._on_worker_finished(True)

    assert "Carte de Léo" in window._result_screen._message.text()
    assert window._result_screen._eject_button.isVisible() is True


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

    assert window._result_screen._eject_button.isVisible() is False


# --- extract-boot / extract-easyroms (étapes A/B) : choix du dossier ------
#
# Régression corrigée : la destination était devenue un chemin généré
# automatiquement, sans que l'utilisateur puisse décider où son archive est
# enregistrée. L'écran Fichier est rétabli, avec un dossier par défaut
# (~/Documents/R36S Studio) que l'utilisateur peut accepter tel quel ou
# remplacer par n'importe quel emplacement -- seul le nom horodaté à
# l'intérieur reste automatique.


@patch("r36s_studio.gui.main_window.archives.default_archives_dir")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_shows_file_screen_with_default_path_preselected(
    mock_list, mock_filter, mock_detect, mock_default_dir, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_default_dir.return_value = "/home/x/Documents/R36S Studio"

    window = MainWindow()
    window._home.extract_boot_selected.emit()
    window._device_screen._list.setCurrentRow(0)
    window._device_screen._emit_chosen()

    assert window._stack.currentWidget() is window._file_screen
    assert window._file_screen._path_label.text() == "/home/x/Documents/R36S Studio"
    assert window._file_screen._next_button.isEnabled() is True  # défaut déjà accepté


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
        window._device_screen._list.setCurrentRow(0)
        window._device_screen._emit_chosen()

        # L'utilisateur accepte simplement le défaut proposé.
        window._file_screen.file_chosen.emit(window._file_screen._path_label.text())

        assert window._stack.currentWidget() is window._execute_screen

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
        window._device_screen._list.setCurrentRow(0)
        window._device_screen._emit_chosen()

        with patch(
            "r36s_studio.gui.screens.QFileDialog.getExistingDirectory",
            return_value="/Volumes/DisqueExterne",
        ):
            window._file_screen._browse()
        window._file_screen.file_chosen.emit(window._file_screen._path_label.text())

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
        window._device_screen._list.setCurrentRow(0)
        window._device_screen._emit_chosen()
        window._file_screen.file_chosen.emit(window._file_screen._path_label.text())

    from pathlib import Path

    mock_new_path.assert_called_once_with("EASYROMS", base_dir=Path("/home/x/Documents/R36S Studio"))


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_success_shows_archive_path_size_and_reveal_button(mock_list, mock_filter, qapp):
    window = MainWindow()
    window.show()
    window._mode = "extract_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._last_progress_bytes = 12_582_912  # 12 Mo

    window._on_worker_finished(True)

    assert window._result_screen._eject_button.isVisible() is True
    assert "ordinateur" in window._result_screen._message.text()
    info = window._result_screen._archive_info_label.text()
    assert "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in info
    assert "12.0 Mo" in info
    assert window._result_screen._reveal_button.isVisible() is True


@patch("r36s_studio.gui.main_window.reveal")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_reveal_requested_calls_reveal_with_archive_path(mock_list, mock_filter, mock_reveal, qapp):
    window = MainWindow()
    window.show()
    window._mode = "extract_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._on_worker_finished(True)

    window._result_screen._reveal_button.click()

    mock_reveal.assert_called_once_with("/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21")


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_inject_boot_success_shows_source_archive_path(mock_list, mock_filter, qapp):
    """Étapes D/E : la même zone indique quelle archive a servi de source,
    plutôt que « archive créée »."""
    window = MainWindow()
    window.show()
    window._mode = "inject_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"

    window._on_worker_finished(True)

    info = window._result_screen._archive_info_label.text()
    assert "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in info
    assert window._result_screen._reveal_button.isVisible() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_success_shows_no_archive_info(mock_list, mock_filter, qapp):
    """backup/flash ne manipulent pas de dossier d'archive -- rien à
    afficher, rien à révéler."""
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_finished(True)

    assert window._result_screen._archive_info_label.isVisible() is False
    assert window._result_screen._reveal_button.isVisible() is False


# --- eject (étape F) : immédiat, sans écran Fichier ni Exécution -----------


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
    window._device_screen._list.setCurrentRow(0)
    window._device_screen._emit_chosen()

    mock_eject.assert_called_once_with(device.path)
    assert window._stack.currentWidget() is window._result_screen
    assert "retirée en toute sécurité" in window._result_screen._message.text()
    assert window._result_screen._eject_button.isVisible() is False


@patch("r36s_studio.gui.main_window.eject_device", side_effect=OSError("carte occupée"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_flow_shows_friendly_error_on_failure(mock_list, mock_filter, mock_detect, mock_eject, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()
    window._home.eject_selected.emit()
    window._device_screen._list.setCurrentRow(0)
    window._device_screen._emit_chosen()

    assert window._stack.currentWidget() is window._result_screen
    assert "carte occupée" not in window._result_screen._message.text()
    window._result_screen._details_toggle.click()
    assert "carte occupée" in window._result_screen._details_label.text()


# --- messages d'erreur conviviaux + panneau Détails (§5, vocabulaire) ------


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_partition_not_found_error_shows_friendly_message_with_raw_detail_hidden(
    mock_list, mock_filter, qapp
):
    window = MainWindow()
    window.show()
    window._mode = "inject_boot"
    window._device = _make_device()

    window._on_worker_error("PARTITION_NOT_FOUND", "Partition « BOOT » introuvable sur /dev/fake-disk-test-3")
    window._on_worker_finished(False)

    message = window._result_screen._message.text()
    assert "/dev/fake-disk-test-3" not in message
    assert "carte" in message.lower()
    assert window._result_screen._details_toggle.isVisible() is True

    window._result_screen._details_toggle.click()
    assert "/dev/fake-disk-test-3" in window._result_screen._details_label.text()


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_unrecognized_error_code_falls_back_to_generic_friendly_message(mock_list, mock_filter, qapp):
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()

    window._on_worker_error("SOME_FUTURE_CODE", "détail technique quelconque")
    window._on_worker_finished(False)

    assert "détail technique quelconque" not in window._result_screen._message.text()
    assert window._result_screen._details_toggle.isVisible() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_macos_tcc_protected_folder_error_shows_dedicated_friendly_message(mock_list, mock_filter, qapp):
    """La détection élargie (worker_runner.py) ne sert à rien si le
    message dédié reste caché derrière le message générique -- vérifie
    qu'il apparaît bien comme message principal, pas seulement dans les
    Détails."""
    window = MainWindow()
    window.show()
    window._mode = "flash"
    window._device = _make_device()

    window._on_worker_error(
        "MACOS_TCC_PROTECTED_FOLDER",
        "[Errno 1] Operation not permitted: '/Users/x/Downloads/ArkOS.img.xz'",
    )
    window._on_worker_finished(False)

    message = window._result_screen._message.text()
    assert "dossier protégé" in message
    assert "/Users/x/Downloads" not in message
    window._result_screen._details_toggle.click()
    assert "/Users/x/Downloads" in window._result_screen._details_label.text()
