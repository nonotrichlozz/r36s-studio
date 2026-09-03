"""Tests d'éjection (partitions/eject.py, étape F du workflow §4.4/§4.5).
`subprocess.run`/`platform.system` sont mockés — aucune carte réelle n'est
éjectée."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio.partitions.eject import _windows_drive_letters, eject


@patch("r36s_studio.partitions.eject.subprocess.run")
@patch("r36s_studio.partitions.eject.platform.system", return_value="Darwin")
def test_macos_uses_diskutil_eject(mock_platform, mock_run):
    eject("/dev/fake-disk-test-4")

    mock_run.assert_called_once_with(["diskutil", "eject", "/dev/fake-disk-test-4"], check=True)


@patch("r36s_studio.partitions.eject.subprocess.run")
@patch("r36s_studio.partitions.eject.platform.system", return_value="Linux")
def test_linux_uses_udisksctl_power_off(mock_platform, mock_run):
    eject("/dev/fake-disk-test-4")

    mock_run.assert_called_once_with(
        ["udisksctl", "power-off", "-b", "/dev/fake-disk-test-4"], check=True
    )


@patch("r36s_studio.partitions.eject.platform.system", return_value="Windows")
@patch("r36s_studio.imaging.winlock.unlock_volumes")
@patch("r36s_studio.imaging.winlock.eject_media")
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes", return_value=["handle-a"])
@patch("r36s_studio.partitions.eject._windows_drive_letters", return_value=["D:\\"])
def test_windows_dismounts_volumes_then_ejects_media(
    mock_letters, mock_lock, mock_eject_media, mock_unlock, mock_platform
):
    eject(r"\\.\PhysicalDrive9902")

    mock_letters.assert_called_once_with(9902)
    mock_lock.assert_called_once_with(["D:\\"])
    mock_eject_media.assert_called_once_with(r"\\.\PhysicalDrive9902")
    mock_unlock.assert_called_once_with(["handle-a"])


@patch("r36s_studio.partitions.eject.platform.system", return_value="Windows")
@patch("r36s_studio.imaging.winlock.unlock_volumes")
@patch("r36s_studio.imaging.winlock.eject_media")
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes")
@patch("r36s_studio.partitions.eject._windows_drive_letters", return_value=[])
def test_windows_ejects_without_dismounting_when_no_drive_letters(
    mock_letters, mock_lock, mock_eject_media, mock_unlock, mock_platform
):
    """Une partition BOOT sans lettre de lecteur (§4.4) n'a rien à
    démonter -- l'éjection matérielle doit quand même avoir lieu."""
    eject(r"\\.\PhysicalDrive9902")

    mock_lock.assert_not_called()
    mock_eject_media.assert_called_once_with(r"\\.\PhysicalDrive9902")
    mock_unlock.assert_called_once_with([])


@patch("r36s_studio.partitions.eject.platform.system", return_value="Windows")
@patch("r36s_studio.imaging.winlock.eject_media", side_effect=OSError("device busy"))
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes", return_value=[])
@patch("r36s_studio.partitions.eject._windows_drive_letters", return_value=[])
def test_windows_eject_media_failure_propagates(mock_letters, mock_lock, mock_eject_media, mock_platform):
    with pytest.raises(OSError):
        eject(r"\\.\PhysicalDrive9902")


@patch("r36s_studio.partitions.eject.platform.system", return_value="Windows")
def test_windows_unexpected_device_path_raises(mock_platform):
    with pytest.raises(OSError):
        eject("/dev/fake-disk-test-4")


@patch("r36s_studio.partitions.eject.platform.system", return_value="Plan9")
def test_unsupported_os_raises_not_implemented(mock_platform):
    with pytest.raises(NotImplementedError):
        eject("/dev/fake-disk-test-4")


@patch("r36s_studio.partitions.eject.subprocess.run", side_effect=OSError("busy"))
@patch("r36s_studio.partitions.eject.platform.system", return_value="Darwin")
def test_failure_propagates(mock_platform, mock_run):
    with pytest.raises(OSError):
        eject("/dev/fake-disk-test-4")


@patch("r36s_studio.partitions.eject.subprocess.run")
def test_windows_drive_letters_parses_powershell_output(mock_run):
    mock_run.return_value.stdout = "D:\\\r\nE:\\\r\n"

    letters = _windows_drive_letters(9902)

    assert letters == ["D:\\", "E:\\"]
    args = mock_run.call_args[0][0]
    assert "9902" in args[-1]


@patch("r36s_studio.partitions.eject.subprocess.run")
def test_windows_drive_letters_empty_when_no_lettered_partition(mock_run):
    mock_run.return_value.stdout = ""

    assert _windows_drive_letters(9902) == []
