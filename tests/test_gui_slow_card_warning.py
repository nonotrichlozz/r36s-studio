"""Avertissement « carte lente » après une sauvegarde (cas réel : carte
d'origine à ~6 Mo/s, docs/claude/testing.md)."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.config import AppConfig
from r36s_studio.devices import Device
from r36s_studio.gui.main_window import MainWindow, _slow_card_read_speed
from r36s_studio.gui.strings import tr

MIB = 1024 * 1024


def test_slow_only_on_enough_low_median_samples():
    assert _slow_card_read_speed([6 * MIB] * 10) == 6 * MIB
    assert _slow_card_read_speed([6 * MIB] * 9) is None  # trop peu de mesures
    assert _slow_card_read_speed([80 * MIB] * 10) is None
    # Quelques à-coups lents sur une bonne carte : la médiane les ignore.
    assert _slow_card_read_speed([2 * MIB] * 4 + [80 * MIB] * 7 + [0.0] * 5) is None


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_warning_logged_after_slow_backup_only(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._device = Device("/dev/fake-disk-test-5", "Carte SD factice", 32_000_000_000, True, "USB", False, [])
    window._file_path = "/tmp/sauvegarde.img"
    logged = []
    window._log_panel.append_log = logged.append
    warning = tr("card_slow_read_warning", speed="6.0").split("(")[0]

    for mode, speed, expected in (("backup", 6 * MIB, True), ("flash", 6 * MIB, False), ("backup", 80 * MIB, False)):
        logged.clear()
        window._mode = mode
        window._read_speeds = []
        for i in range(12):
            window._on_progress(i * MIB, 12 * MIB, speed)
        window._on_worker_finished(True)
        assert any(line.startswith(warning) for line in logged) is expected, (mode, speed)
