"""Tests de l'orchestration extract_boot/extract_easyroms/inject_boot/
copy_games (partitions/jobs.py). `locate_mounted` et `copy_tree` sont
mockés — aucune partition réelle n'est localisée ni montée."""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from r36s_studio.devices import Device
from r36s_studio.partitions.jobs import (
    MacosNtfsWriteUnsupported,
    copy_games,
    extract_boot,
    extract_easyroms,
    inject_boot,
)
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


# --- extract_boot / extract_easyroms : ancienne carte -> ordinateur -------


@patch("r36s_studio.partitions.jobs.copy_tree", return_value=321)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_extract_boot_copies_from_boot_partition_mountpoint_to_dest_dir(mock_locate, mock_copy):
    mock_locate.return_value = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", "/Volumes/BOOT")
    device = _make_device()

    copied = extract_boot(device, "/tmp/R36S Studio/BOOT_2026-07-06_00-21")

    mock_locate.assert_called_once_with(device.path, BOOT_LABEL)
    assert mock_copy.call_args.args[:2] == ("/Volumes/BOOT", "/tmp/R36S Studio/BOOT_2026-07-06_00-21")
    assert copied == 321


@patch("r36s_studio.partitions.jobs.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.jobs.copy_tree", return_value=654)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_extract_easyroms_copies_from_easyroms_partition_even_when_ntfs_on_macos(
    mock_locate, mock_copy, mock_platform
):
    """L'extraction ne fait que lire EASYROMS : contrairement à
    `copy_games`, elle ne doit jamais lever `MacosNtfsWriteUnsupported` --
    macOS monte nativement le NTFS en lecture seule, ce qui suffit pour
    extraire."""
    mock_locate.return_value = PartitionInfo(
        "/dev/fake-disk-test-4s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"
    )
    device = _make_device()

    copied = extract_easyroms(device, "/tmp/R36S Studio/EASYROMS_2026-07-06_00-21")

    mock_locate.assert_called_once_with(device.path, EASYROMS_LABEL)
    assert mock_copy.call_args.args[:2] == (
        "/Volumes/EASYROMS",
        "/tmp/R36S Studio/EASYROMS_2026-07-06_00-21",
    )
    assert copied == 654


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


# --- démontage propre d'un montage forcé après usage (§4.4, cartes GPT/ ----
# --- EFI dont l'automontage macOS échoue) -- no-op pour un montage --------
# --- diskutil/udisksctl normal (`unmount_forced`, locate.py). -------------


@patch("r36s_studio.partitions.jobs.unmount_forced")
@patch("r36s_studio.partitions.jobs.copy_tree", return_value=321)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_extract_boot_unmounts_forced_mount_after_copying(mock_locate, mock_copy, mock_unmount):
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "", "", "/tmp/r36s-studio-test", partition_type="efi")
    mock_locate.return_value = partition
    device = _make_device()

    extract_boot(device, "/tmp/R36S Studio/BOOT_2026-07-06_00-21")

    mock_unmount.assert_called_once_with(partition)


@patch("r36s_studio.partitions.jobs.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.jobs.unmount_forced")
@patch("r36s_studio.partitions.jobs.copy_tree", return_value=654)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_extract_easyroms_unmounts_forced_mount_after_copying(mock_locate, mock_copy, mock_unmount, mock_platform):
    partition = PartitionInfo("/dev/fake-disk-test-4s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS")
    mock_locate.return_value = partition
    device = _make_device()

    extract_easyroms(device, "/tmp/R36S Studio/EASYROMS_2026-07-06_00-21")

    mock_unmount.assert_called_once_with(partition)


@patch("r36s_studio.partitions.jobs.unmount_forced")
@patch("r36s_studio.partitions.jobs.copy_tree", return_value=123)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_inject_boot_unmounts_forced_mount_after_copying(mock_locate, mock_copy, mock_unmount):
    partition = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", "/Volumes/BOOT")
    mock_locate.return_value = partition
    device = _make_device()

    inject_boot(device, "/tmp/boot_backup")

    mock_unmount.assert_called_once_with(partition)


@patch("r36s_studio.partitions.jobs.platform.system", return_value="Linux")
@patch("r36s_studio.partitions.jobs.unmount_forced")
@patch("r36s_studio.partitions.jobs.copy_tree", return_value=456)
@patch("r36s_studio.partitions.jobs.locate_mounted")
def test_copy_games_unmounts_forced_mount_after_copying(mock_locate, mock_copy, mock_unmount, mock_platform):
    partition = PartitionInfo("/dev/fake-disk-test-sdb2", "EASYROMS", "ntfs", "/media/user/EASYROMS")
    mock_locate.return_value = partition
    device = _make_device()

    copy_games(device, "/tmp/games")

    mock_unmount.assert_called_once_with(partition)

