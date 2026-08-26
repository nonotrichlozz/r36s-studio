"""Tests de navigation de MainWindow (gui/main_window.py) : traverse
l'assistant de bout en bout pour `backup` et `flash`, `list_devices`,
`WorkerRunner` et `eject` mockés — aucun périphérique réel, aucune
élévation, aucune écriture disque."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_flow_reaches_execute_with_correct_argv(mock_list, mock_filter, qapp):
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


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_flow_requires_confirmation_before_execute(mock_list, mock_filter, qapp):
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


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_confirm_cancel_returns_to_file_screen(mock_list, mock_filter, qapp):
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


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_success_shows_result_with_eject_for_flash(mock_list, mock_filter, qapp):
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


@patch("r36s_studio.gui.main_window.eject")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_requested_calls_eject_module_with_device_path(mock_list, mock_filter, mock_eject, qapp):
    window = MainWindow()
    window._device = _make_device(path="/dev/fake-disk-test-3")

    window._on_eject_requested()

    mock_eject.eject.assert_called_once_with("/dev/fake-disk-test-3")


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_cancel_requested_calls_runner_cancel(mock_list, mock_filter, qapp):
    window = MainWindow()
    fake_runner = MagicMock()
    window._runner = fake_runner

    window._on_cancel_requested()

    fake_runner.cancel.assert_called_once()
