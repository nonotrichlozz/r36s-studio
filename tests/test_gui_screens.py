"""Tests des écrans de l'assistant (gui/screens.py) — construction et
logique des signaux, en mode Qt "offscreen" (fixture `qapp`)."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.gui.screens import (
    ConfirmScreen,
    DeviceScreen,
    ExecuteScreen,
    FileScreen,
    HomeScreen,
    ResultScreen,
    _format_duration,
)


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


# --- HomeScreen --------------------------------------------------------


def test_home_screen_backup_tile_emits_signal(qapp):
    screen = HomeScreen()
    received = []
    screen.backup_selected.connect(lambda: received.append(True))

    screen.findChildren(type(screen))  # sanity: widget constructed
    screen.backup_selected.emit()

    assert received == [True]


def test_home_screen_disabled_tiles_are_not_clickable(qapp):
    from PySide6.QtWidgets import QPushButton

    screen = HomeScreen()
    buttons = screen.findChildren(QPushButton)
    disabled = [b for b in buttons if not b.isEnabled()]
    assert len(disabled) == 2  # inject_boot et copy_games, phase 5


# --- DeviceScreen --------------------------------------------------------


def test_device_screen_no_default_selection(qapp):
    screen = DeviceScreen()
    screen.set_devices([_make_device()])

    assert screen._list.selectedItems() == []
    assert screen._next_button.isEnabled() is False


def test_device_screen_selecting_enables_next_and_emits_correct_device(qapp):
    screen = DeviceScreen()
    device_a = _make_device(path="/dev/fake-disk-test-3", display="A")
    device_b = _make_device(path="/dev/fake-disk-test-4", display="B")
    screen.set_devices([device_a, device_b])

    screen._list.setCurrentRow(1)
    assert screen._next_button.isEnabled() is True

    chosen = []
    screen.device_chosen.connect(lambda d: chosen.append(d))
    screen._emit_chosen()

    assert chosen == [device_b]


def test_device_screen_empty_list_shows_empty_message(qapp):
    screen = DeviceScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois le parent affiché
    screen.set_devices([])

    assert screen._empty_label.isVisible() is True
    assert screen._list.isVisible() is False


# --- FileScreen ----------------------------------------------------------


def test_file_screen_set_mode_resets_state(qapp):
    screen = FileScreen()
    screen.set_mode("flash")
    assert screen._next_button.isEnabled() is False
    assert screen._path_label.text() == ""


@patch("r36s_studio.gui.screens.QFileDialog.getSaveFileName", return_value=("/tmp/out.img", ""))
def test_file_screen_backup_browse_enables_next(mock_dialog, qapp):
    screen = FileScreen()
    screen.set_mode("backup")

    screen._browse()

    assert screen._path_label.text() == "/tmp/out.img"
    assert screen._next_button.isEnabled() is True


@patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("", ""))
def test_file_screen_cancelled_dialog_does_not_enable_next(mock_dialog, qapp):
    screen = FileScreen()
    screen.set_mode("flash")

    screen._browse()

    assert screen._next_button.isEnabled() is False


# --- ConfirmScreen ---------------------------------------------------------


def test_confirm_screen_go_disabled_until_checkbox_checked(qapp):
    screen = ConfirmScreen()
    screen.set_device(_make_device())
    assert screen._go_button.isEnabled() is False

    screen._checkbox.setChecked(True)
    assert screen._go_button.isEnabled() is True

    screen._checkbox.setChecked(False)
    assert screen._go_button.isEnabled() is False


def test_confirm_screen_shows_device_display_and_size(qapp):
    screen = ConfirmScreen()
    screen.set_device(_make_device(display="SanDisk Ultra", size_bytes=31_914_983_424))

    text = screen._message.text()
    assert "SanDisk Ultra" in text
    assert "31.9" in text


def test_confirm_screen_cancel_resets_checkbox_and_emits(qapp):
    screen = ConfirmScreen()
    screen.set_device(_make_device())
    screen._checkbox.setChecked(True)

    cancelled = []
    screen.cancelled.connect(lambda: cancelled.append(True))
    screen._cancel()

    assert cancelled == [True]
    assert screen._checkbox.isChecked() is False


# --- ExecuteScreen ---------------------------------------------------------


def test_execute_screen_update_progress_sets_percentage(qapp):
    screen = ExecuteScreen()
    screen.reset("flash")

    screen.update_progress(done=50, total=200, speed=1_000_000)

    assert screen._bar.value() == 25
    assert screen._bar.minimum() == 0 and screen._bar.maximum() == 100


def test_execute_screen_unknown_total_shows_indeterminate_bar(qapp):
    screen = ExecuteScreen()
    screen.reset("flash")

    screen.update_progress(done=50, total=0, speed=1_000_000)

    assert screen._bar.minimum() == 0 and screen._bar.maximum() == 0


def test_format_duration():
    assert _format_duration(45) == "45 s"
    assert _format_duration(125) == "2 min 05 s"
    assert _format_duration(3725) == "1 h 02 min"


# --- ResultScreen ---------------------------------------------------------


def test_result_screen_success_shows_eject_only_for_flash(qapp):
    screen = ResultScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois le parent affiché
    screen.show_success("ok", allow_eject=True)
    assert screen._eject_button.isVisible() is True

    screen.show_success("ok", allow_eject=False)
    assert screen._eject_button.isVisible() is False


def test_result_screen_error_hides_eject(qapp):
    screen = ResultScreen()
    screen.show()
    screen.show_error("boom")
    assert screen._eject_button.isVisible() is False
