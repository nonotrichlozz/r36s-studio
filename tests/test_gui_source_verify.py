"""GUI et double lecture / `.sha256blocks` (imaging/source_verify.py) :
contrôles gratuits avant toute élévation (image `.instable`, en-tête et
taille du compagnon), case du mode expert, drapeaux transmis au worker.
`WorkerRunner` et `QMessageBox` sont mockés -- aucun worker lancé."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QMessageBox

from r36s_studio.devices import Device
from r36s_studio.gui.main_window import MainWindow
from r36s_studio.imaging.source_verify import write_block_digests


def _make_device() -> Device:
    return Device(
        path="/dev/fake-disk-test-3", display="Carte SD factice", size_bytes=32_000_000_000, removable=True,
        bus="USB", is_system=False, mountpoints=[],
    )


@pytest.fixture(autouse=True)
def _no_real_devices():
    with patch("r36s_studio.gui.main_window.list_devices", return_value=[]), patch(
        "r36s_studio.gui.main_window.filter_devices", return_value=[]
    ):
        yield


def _argv_of_started_worker(window) -> list:
    runner_class = MagicMock()
    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
    return runner_class.call_args.args[0]


def _window(mode: str, file_path: str, ui_mode: str = "assisted") -> MainWindow:
    window = MainWindow()
    window._app_config.ui_mode = ui_mode
    window._mode = mode
    window._device = _make_device()
    window._file_path = file_path
    return window


def test_backup_argv_has_no_source_verify_flag_only_when_disabled(qapp):
    window = _window("backup", "/tmp/out.img")
    assert "--no-source-verify" not in _argv_of_started_worker(window)

    window._app_config.verify_backup_source = False
    assert "--no-source-verify" in _argv_of_started_worker(window)


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
def test_unstable_image_refused_outside_expert_mode_before_elevation(mock_warning, qapp, tmp_path):
    image = tmp_path / "out.img.instable"
    image.write_bytes(b"x" * 1024)
    window = _window("flash", str(image))

    assert window._check_flash_image_integrity_or_warn() is False
    mock_warning.assert_called_once()


@patch("r36s_studio.gui.main_window.QMessageBox.question", return_value=QMessageBox.Yes)
def test_unstable_image_allowed_in_expert_mode_after_explicit_confirmation(mock_question, qapp, tmp_path):
    image = tmp_path / "out.img.instable"
    image.write_bytes(b"x" * 1024)
    window = _window("flash", str(image), ui_mode="expert")

    assert window._check_flash_image_integrity_or_warn() is True
    mock_question.assert_called_once()
    assert "--allow-unstable" in _argv_of_started_worker(window)


@patch("r36s_studio.gui.main_window.QMessageBox.question", return_value=QMessageBox.No)
def test_unstable_image_expert_refusal_stops_the_flow(mock_question, qapp, tmp_path):
    image = tmp_path / "out.img.instable"
    image.write_bytes(b"x" * 1024)
    window = _window("flash", str(image), ui_mode="expert")

    assert window._check_flash_image_integrity_or_warn() is False
    assert window._allow_unstable_image is False


@patch("r36s_studio.gui.main_window.QMessageBox.warning")
def test_sidecar_size_mismatch_refused_before_elevation(mock_warning, qapp, tmp_path):
    image = tmp_path / "sauvegarde.img"
    image.write_bytes(b"x" * 1024)
    write_block_digests(str(image), ["0" * 64], 4096, 2048)  # taille annoncée fausse
    window = _window("flash", str(image))

    assert window._check_flash_image_integrity_or_warn() is False
    mock_warning.assert_called_once()


def test_image_with_intact_sidecar_header_passes_cheap_checks(qapp, tmp_path):
    image = tmp_path / "sauvegarde.img"
    image.write_bytes(b"x" * 1024)
    write_block_digests(str(image), ["0" * 64], 4096, 1024)  # recalcul complet : worker seulement
    window = _window("flash", str(image))

    assert window._check_flash_image_integrity_or_warn() is True
    assert "--allow-unstable" not in _argv_of_started_worker(window)


def test_source_verify_checkbox_only_in_expert_mode_and_persisted(qapp):
    window = _window("backup", "/tmp/out.img")
    window._file_dialog.set_mode("backup")
    window._offer_source_verify_option()
    assert window._file_dialog._source_verify_check.isVisibleTo(window._file_dialog) is False

    window._app_config.ui_mode = "expert"
    window._offer_source_verify_option()
    check = window._file_dialog._source_verify_check
    assert check.isVisibleTo(window._file_dialog) is True and check.isChecked() is True

    check.setChecked(False)
    assert window._app_config.verify_backup_source is False
