"""Tests de PartitionJobRunner (gui/partition_runner.py) : traduction des
exceptions de `partitions/jobs.py` en signaux Qt. `inject_boot`/`copy_games`
sont mockés — aucune partition réelle n'est touchée. `run()` est appelé
directement (jamais `.start()`) pour exécuter la logique de façon
synchrone, sans vrai threading, comme le fait déjà `gui/worker_runner.py`
côté worker élevé."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.gui.partition_runner import PartitionJobRunner
from r36s_studio.imaging.copy import OperationCancelled, ProgressEvent
from r36s_studio.partitions import (
    MacosNtfsWriteUnsupported,
    MountpointNotWritable,
    PartitionNotFound,
    PartitionNotMounted,
)


def _make_device(path="/dev/fake-disk-test-4") -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


@patch("r36s_studio.gui.partition_runner.inject_boot")
def test_inject_boot_success_emits_finished_true(mock_inject, qapp):
    runner = PartitionJobRunner("inject_boot", _make_device(), "/tmp/boot_backup")
    finished_events = []
    runner.finished_job.connect(lambda ok: finished_events.append(ok))

    runner.run()

    mock_inject.assert_called_once()
    assert mock_inject.call_args.args[:2] == (runner._device, "/tmp/boot_backup")
    assert finished_events == [True]


@patch("r36s_studio.gui.partition_runner.extract_boot", return_value=10)
def test_extract_boot_success_calls_extract_boot(mock_extract, qapp):
    runner = PartitionJobRunner("extract_boot", _make_device(), "/tmp/R36S Studio/BOOT_x")
    finished_events = []
    runner.finished_job.connect(lambda ok: finished_events.append(ok))

    runner.run()

    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[:2] == (runner._device, "/tmp/R36S Studio/BOOT_x")
    assert finished_events == [True]


@patch("r36s_studio.gui.partition_runner.extract_easyroms", return_value=10)
def test_extract_easyroms_success_calls_extract_easyroms(mock_extract, qapp):
    runner = PartitionJobRunner("extract_easyroms", _make_device(), "/tmp/R36S Studio/EASYROMS_x")

    runner.run()

    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[:2] == (runner._device, "/tmp/R36S Studio/EASYROMS_x")


@patch("r36s_studio.gui.partition_runner.extract_boot", side_effect=PartitionNotFound("BOOT", "/dev/x"))
def test_extract_boot_partition_not_found_maps_to_dedicated_code(mock_extract, qapp):
    runner = PartitionJobRunner("extract_boot", _make_device(), "/tmp/dest")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "PARTITION_NOT_FOUND"


@patch("r36s_studio.gui.partition_runner.copy_games")
def test_copy_games_forwards_progress_events(mock_copy, qapp):
    def _fake_copy(device, source, on_progress=None, should_cancel=None):
        on_progress(ProgressEvent(done=10, total=100, speed=5.0))
        return 10

    mock_copy.side_effect = _fake_copy
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    progress_events = []
    runner.progress.connect(lambda *a: progress_events.append(a))

    runner.run()

    assert progress_events == [(10, 100, 5.0)]


@patch("r36s_studio.gui.partition_runner.copy_games", side_effect=OperationCancelled(2048))
def test_cancellation_emits_cancelled_error(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    finished_events = []
    runner.error.connect(lambda *a: error_events.append(a))
    runner.finished_job.connect(lambda ok: finished_events.append(ok))

    runner.run()

    assert error_events[0][0] == "CANCELLED"
    assert finished_events == [False]


@patch("r36s_studio.gui.partition_runner.copy_games", side_effect=MacosNtfsWriteUnsupported("EASYROMS"))
def test_macos_ntfs_unsupported_maps_to_dedicated_code(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "EASYROMS_NTFS_MACOS"


@patch(
    "r36s_studio.gui.partition_runner.inject_boot",
    side_effect=PartitionNotFound("BOOT", "/dev/fake-disk-test-4"),
)
def test_partition_not_found_maps_to_dedicated_code(mock_inject, qapp):
    runner = PartitionJobRunner("inject_boot", _make_device(), "/tmp/boot_backup")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "PARTITION_NOT_FOUND"


@patch(
    "r36s_studio.gui.partition_runner.inject_boot",
    side_effect=PartitionNotMounted("BOOT", "/dev/fake-disk-test-4"),
)
def test_partition_not_mounted_maps_to_dedicated_code(mock_inject, qapp):
    runner = PartitionJobRunner("inject_boot", _make_device(), "/tmp/boot_backup")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "PARTITION_NOT_MOUNTED"


@patch(
    "r36s_studio.gui.partition_runner.copy_games",
    side_effect=MountpointNotWritable("/Volumes/EASYROMS", "boom"),
)
def test_mountpoint_not_writable_maps_to_dedicated_code(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "MOUNTPOINT_NOT_WRITABLE"


@patch("r36s_studio.gui.partition_runner.copy_games", side_effect=OSError("disk full"))
def test_generic_os_error_maps_to_io_error(mock_copy, qapp):
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")
    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner.run()

    assert error_events[0][0] == "IO_ERROR"


@patch("r36s_studio.gui.partition_runner.copy_games")
def test_cancel_sets_should_cancel_flag_passed_to_job(mock_copy, qapp):
    captured = {}

    def _fake_copy(device, source, on_progress=None, should_cancel=None):
        captured["should_cancel"] = should_cancel
        return 0

    mock_copy.side_effect = _fake_copy
    runner = PartitionJobRunner("copy_games", _make_device(), "/tmp/games")

    runner.cancel()
    runner.run()

    assert captured["should_cancel"]() is True
