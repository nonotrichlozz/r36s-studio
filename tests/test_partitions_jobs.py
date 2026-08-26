"""Tests de l'orchestration inject_boot/copy_games (partitions/jobs.py).
`locate_mounted` et `copy_tree` sont mockés — aucune partition réelle n'est
localisée ni montée."""

from __future__ import annotations

import plistlib
from unittest.mock import MagicMock, patch

import pytest

from r36s_studio.devices import Device
from r36s_studio.partitions.jobs import MacosNtfsWriteUnsupported, copy_games, inject_boot
from r36s_studio.partitions.locate import BOOT_LABEL, EASYROMS_LABEL, PartitionInfo


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


@patch("r36s_studio.partitions.jobs.copy_tree", return_value=123)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_inject_boot_copies_to_boot_partition_mountpoint(mock_locate, mock_copy):
    mock_locate.return_value = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", "/Volumes/BOOT")
    device = _make_device()

    copied = inject_boot(device, "/tmp/boot_backup")

    mock_locate.assert_called_once_with(device.path, BOOT_LABEL)
    mock_copy.assert_called_once()
    assert mock_copy.call_args.args[:2] == ("/tmp/boot_backup", "/Volumes/BOOT")
    assert copied == 123


@patch("r36s_studio.partitions.jobs.platform.system", return_value="Linux")
@patch("r36s_studio.partitions.jobs.copy_tree", return_value=456)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_copy_games_copies_to_easyroms_partition_mountpoint(mock_locate, mock_copy, mock_platform):
    mock_locate.return_value = PartitionInfo("/dev/fake-disk-test-sdb2", "EASYROMS", "ntfs", "/media/user/EASYROMS")
    device = _make_device()

    copied = copy_games(device, "/tmp/games")

    mock_locate.assert_called_once_with(device.path, EASYROMS_LABEL)
    assert mock_copy.call_args.args[:2] == ("/tmp/games", "/media/user/EASYROMS")
    assert copied == 456


@patch("r36s_studio.partitions.jobs.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.jobs.copy_tree")
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_copy_games_rejects_ntfs_write_on_macos_before_copying(mock_locate, mock_copy, mock_platform):
    mock_locate.return_value = PartitionInfo("/dev/fake-disk-test-4s2", "EASYROMS", "ntfs", "/Volumes/EASYROMS")
    device = _make_device()

    with pytest.raises(MacosNtfsWriteUnsupported):
        copy_games(device, "/tmp/games")

    mock_copy.assert_not_called()


@patch("r36s_studio.partitions.jobs.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.jobs.copy_tree", return_value=10)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_copy_games_allows_non_ntfs_easyroms_on_macos(mock_locate, mock_copy, mock_platform):
    """Si un jour ArkOS reformate EASYROMS en FAT32 (le brief initial le
    supposait), macOS doit pouvoir y écrire normalement."""
    mock_locate.return_value = PartitionInfo("/dev/fake-disk-test-4s2", "EASYROMS", "msdos", "/Volumes/EASYROMS")
    device = _make_device()

    copied = copy_games(device, "/tmp/games")

    assert copied == 10


@patch("r36s_studio.partitions.jobs.copy_tree")
@patch("r36s_studio.partitions.jobs.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.locate.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_copy_games_end_to_end_rejects_real_world_windows_ntfs_field_value(
    mock_run, mock_locate_platform, mock_jobs_platform, mock_copy
):
    """Bug confirmé sur du vrai matériel : `copy-games` sur macOS vers
    EASYROMS échouait avec `[Errno 30] Read-only file system` au lieu du
    refus explicite -- `diskutil` renvoyait "Windows_NTFS" (pas "ntfs") et
    la comparaison stricte de `_reject_macos_ntfs_write` ne s'en apercevait
    pas. Test bout en bout, sans mocker `locate_mounted` : seul
    `subprocess.run` (utilisé par `locate.py`) est mocké, pour vérifier
    toute la chaîne réelle jusqu'à `_macos_filesystem`."""
    list_plist = plistlib.dumps(
        {
            "AllDisksAndPartitions": [
                {
                    "DeviceIdentifier": "fake-disk-test-4",
                    "Partitions": [{"DeviceIdentifier": "fake-disk-test-4s3"}],
                }
            ]
        }
    )
    info_easyroms = plistlib.dumps(
        {
            "VolumeName": "EASYROMS",
            "FilesystemType": "Windows_NTFS",
            "Content": "Windows_NTFS",
            "MountPoint": "/Volumes/EASYROMS",
        }
    )
    mock_run.side_effect = [
        MagicMock(stdout=list_plist, returncode=0),
        MagicMock(stdout=info_easyroms, returncode=0),
    ]
    device = _make_device()

    with pytest.raises(MacosNtfsWriteUnsupported):
        copy_games(device, "/tmp/games")

    mock_copy.assert_not_called()
