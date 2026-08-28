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


# --- WizardIdentifyRunner (étape 2 du mode assisté, §5) ---------------------
#
# Distingue trois échecs (message d'étape 2 différent pour chacun) :
# montage impossible (carte défaillante), montée mais aucun .dtb, .dtb
# présents mais tous invalides -- les deux derniers sont décidés par
# identify_from_boot_directory (identify/__init__.py, ses propres tests) ;
# ici on vérifie seulement le cas du montage, propre à ce runner.

from r36s_studio.gui.partition_runner import WizardIdentifyRunner
from r36s_studio.identify import IdentifyFailureReason, IdentifyResult
from r36s_studio.partitions.locate import PartitionInfo


@patch("r36s_studio.gui.partition_runner.locate_mounted", side_effect=PartitionNotMounted("BOOT", "/dev/x"))
def test_wizard_identify_runner_emits_mount_failed_when_locate_mounted_raises(mock_locate, qapp):
    runner = WizardIdentifyRunner("/dev/fake-disk-test-5")
    results = []
    runner.finished_identify.connect(lambda result: results.append(result))

    runner.run()

    assert results == [IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED)]


@patch(
    "r36s_studio.gui.partition_runner.locate_mounted",
    return_value=PartitionInfo("/dev/fake-disk-test-5s1", "", "fat16", None),
)
def test_wizard_identify_runner_emits_mount_failed_when_mountpoint_is_empty(mock_locate, qapp):
    """`locate_mounted` peut réussir sans lever tout en renvoyant une
    partition sans mountpoint effectif (cas limite) -- traité comme un
    montage raté, pas comme « aucun .dtb trouvé » (qui suppose une
    partition lisible)."""
    runner = WizardIdentifyRunner("/dev/fake-disk-test-5")
    results = []
    runner.finished_identify.connect(lambda result: results.append(result))

    runner.run()

    assert results == [IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED)]


@patch("r36s_studio.gui.partition_runner.identify_from_boot_directory")
@patch(
    "r36s_studio.gui.partition_runner.locate_mounted",
    return_value=PartitionInfo("/dev/fake-disk-test-5s1", "", "fat16", "/Volumes/BOOT"),
)
def test_wizard_identify_runner_delegates_to_identify_from_boot_directory_once_mounted(
    mock_locate, mock_identify, qapp
):
    expected = IdentifyResult(failure_reason=IdentifyFailureReason.NO_DTB_FOUND)
    mock_identify.return_value = expected
    runner = WizardIdentifyRunner("/dev/fake-disk-test-5")
    results = []
    runner.finished_identify.connect(lambda result: results.append(result))

    runner.run()

    mock_identify.assert_called_once_with("/Volumes/BOOT")
    assert results == [expected]
