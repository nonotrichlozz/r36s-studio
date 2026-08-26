"""Tests de la localisation/montage de partitions (partitions/locate.py),
par OS. `subprocess.run`/`platform.system`/`time.sleep` sont mockés — aucune
carte réelle n'est touchée, aucune vraie attente n'a lieu.

Couvre deux bugs confirmés sur du vrai matériel :
- sur une carte ArkOS R36S réelle, la première partition (BOOT) n'a aucune
  étiquette (« NO NAME », DOS_FAT_16 sous `diskutil`) — l'identification
  par étiquette seule ratait systématiquement cette partition ;
- sur macOS, une partition démontée au préalable (par un flash précédent,
  un `hdiutil detach`...) ne remonte jamais toute seule — attendre
  passivement un montage automatique échouait systématiquement sur
  `PartitionNotMounted`."""

from __future__ import annotations

import json
import plistlib
from unittest.mock import MagicMock, patch

import pytest

from r36s_studio.partitions.locate import (
    BOOT_LABEL,
    EASYROMS_LABEL,
    PartitionInfo,
    PartitionNotFound,
    PartitionNotMounted,
    _list_linux,
    _list_macos,
    _list_windows,
    _macos_filesystem,
    _mount_macos,
    _select_boot,
    _select_easyroms,
    find_partition,
    locate_mounted,
)


def _run_result(stdout=b"", returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


# --- _select_boot / _select_easyroms : le coeur du correctif ---------------


def test_select_boot_by_position_and_fat_filesystem_without_label():
    """Le cas confirmé sur du vrai matériel : aucune étiquette, mais
    première partition + FAT16."""
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", "/Volumes/NO NAME"),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
    ]

    boot = _select_boot(partitions, "/dev/fake-disk-test-4")

    assert boot.device_path == "/dev/fake-disk-test-4s1"


def test_select_boot_ignores_label_when_first_partition_is_fat():
    """La position + le système de fichiers priment sur l'étiquette : même
    si une autre partition s'appelle « BOOT » par erreur, c'est la première
    partition FAT qui est retenue."""
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat32", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "BOOT", "ext4", None),
    ]

    boot = _select_boot(partitions, "/dev/fake-disk-test-4")

    assert boot.device_path == "/dev/fake-disk-test-4s1"


def test_select_boot_falls_back_to_label_when_first_partition_not_fat():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "BOOT", "fat32", "/Volumes/BOOT"),
    ]

    boot = _select_boot(partitions, "/dev/fake-disk-test-4")

    assert boot.device_path == "/dev/fake-disk-test-4s2"


def test_select_boot_raises_when_no_criterion_matches():
    partitions = [PartitionInfo("/dev/fake-disk-test-4s1", "", "ext4", None)]

    with pytest.raises(PartitionNotFound):
        _select_boot(partitions, "/dev/fake-disk-test-4")


def test_select_boot_raises_on_empty_partition_list():
    with pytest.raises(PartitionNotFound):
        _select_boot([], "/dev/fake-disk-test-4")


def test_select_easyroms_prefers_label_over_position():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
    ]

    easyroms = _select_easyroms(partitions, "/dev/fake-disk-test-4")

    assert easyroms.device_path == "/dev/fake-disk-test-4s3"


def test_select_easyroms_falls_back_to_third_partition_position_when_unlabeled():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "", "ntfs", None),  # pas d'étiquette
    ]

    easyroms = _select_easyroms(partitions, "/dev/fake-disk-test-4")

    assert easyroms.device_path == "/dev/fake-disk-test-4s3"


def test_select_easyroms_position_fallback_accepts_fat32_too():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "", "fat32", None),
    ]

    easyroms = _select_easyroms(partitions, "/dev/fake-disk-test-4")

    assert easyroms.device_path == "/dev/fake-disk-test-4s3"


def test_select_easyroms_position_fallback_rejects_wrong_filesystem():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "", "ext4", None),  # ni NTFS ni FAT
    ]

    with pytest.raises(PartitionNotFound):
        _select_easyroms(partitions, "/dev/fake-disk-test-4")


def test_select_easyroms_raises_when_fewer_than_three_partitions_and_no_label():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ntfs", None),
    ]

    with pytest.raises(PartitionNotFound):
        _select_easyroms(partitions, "/dev/fake-disk-test-4")


# --- find_partition : identification complète d'une carte réelle sans BOOT
#     étiquetée --------------------------------------------------------------


@patch("r36s_studio.partitions.locate.list_partitions")
def test_find_partition_boot_on_unlabeled_real_arkos_card(mock_list):
    """Reproduction du bug rapporté : carte réelle, BOOT sans étiquette."""
    mock_list.return_value = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", "/Volumes/NO NAME"),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
    ]

    boot = find_partition("/dev/fake-disk-test-4", BOOT_LABEL)
    easyroms = find_partition("/dev/fake-disk-test-4", EASYROMS_LABEL)

    assert boot.device_path == "/dev/fake-disk-test-4s1"
    assert easyroms.device_path == "/dev/fake-disk-test-4s3"


@patch("r36s_studio.partitions.locate.list_partitions")
def test_find_partition_generic_label_search_for_other_labels(mock_list):
    mock_list.return_value = [PartitionInfo("/dev/fake-disk-test-4s1", "DATA", "ext4", "/mnt/data")]

    partition = find_partition("/dev/fake-disk-test-4", "DATA")

    assert partition.device_path == "/dev/fake-disk-test-4s1"


# --- macOS : _macos_filesystem -- bug confirmé sur du vrai matériel --------
#
# `copy-games` sur macOS vers une vraie partition EASYROMS (NTFS) a échoué
# avec `[Errno 30] Read-only file system` au lieu du refus explicite
# `EASYROMS_NTFS_MACOS` attendu : la garde de `jobs._reject_macos_ntfs_write`
# compare `partition.filesystem == "ntfs"` au sens strict, et `diskutil` a
# manifestement renvoyé autre chose que la chaîne exacte "ntfs" pour cette
# partition (variante de casse, ou le nom de type de partition "Windows_NTFS"
# plutôt que la personnalité de montage attendue). `_macos_filesystem` doit
# normaliser toute variante contenant "ntfs" -- FilesystemType ou Content,
# quelle que soit la casse -- vers la valeur canonique "ntfs".


def test_macos_filesystem_normalizes_windows_ntfs_filesystem_type():
    """Variante suspectée par le rapport de bug : `FilesystemType` renvoie
    le nom de type de partition ("Windows_NTFS") plutôt que la
    personnalité de montage "ntfs"."""
    info = {"FilesystemType": "Windows_NTFS", "Content": "Windows_NTFS"}
    assert _macos_filesystem(info) == "ntfs"


def test_macos_filesystem_normalizes_uppercase_ntfs():
    assert _macos_filesystem({"FilesystemType": "NTFS"}) == "ntfs"


def test_macos_filesystem_normalizes_windows_ntfs_in_content_only():
    """Le cas déjà couvert avant ce correctif : `FilesystemType` vide,
    seul `Content` porte l'information -- doit continuer à fonctionner
    après la réécriture de la normalisation."""
    info = {"FilesystemType": "", "Content": "Windows_NTFS"}
    assert _macos_filesystem(info) == "ntfs"


def test_macos_filesystem_still_returns_ntfs_for_expected_lowercase_value():
    assert _macos_filesystem({"FilesystemType": "ntfs"}) == "ntfs"


def test_macos_filesystem_normalizes_fat_variants_to_msdos():
    assert _macos_filesystem({"FilesystemType": "msdos"}) == "msdos"
    assert _macos_filesystem({"FilesystemType": "", "Content": "Windows_FAT_32"}) == "msdos"


def test_macos_filesystem_passes_through_unrecognized_filesystem():
    assert _macos_filesystem({"FilesystemType": "hfs"}) == "hfs"


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_find_partition_easyroms_detected_as_ntfs_despite_windows_ntfs_field(mock_run):
    """Bout en bout, via `_list_macos`/`find_partition` : la valeur de
    champ suspectée par le rapport de bug ne doit plus faire échapper la
    partition à la détection NTFS."""
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
    mock_run.side_effect = [_run_result(list_plist), _run_result(info_easyroms)]

    partition = find_partition("/dev/fake-disk-test-4", EASYROMS_LABEL)

    assert partition.filesystem == "ntfs"


# --- macOS : _list_macos -----------------------------------------------


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_macos_returns_partitions_in_disk_order(mock_run):
    list_plist = plistlib.dumps(
        {
            "AllDisksAndPartitions": [
                {
                    "DeviceIdentifier": "fake-disk-test-4",
                    "Partitions": [
                        {"DeviceIdentifier": "fake-disk-test-4s1"},
                        {"DeviceIdentifier": "fake-disk-test-4s2"},
                    ],
                }
            ]
        }
    )
    info_boot = plistlib.dumps(
        {"VolumeName": "NO NAME", "FilesystemType": "msdos", "MountPoint": "/Volumes/NO NAME"}
    )
    info_easyroms = plistlib.dumps(
        {"VolumeName": "EASYROMS", "FilesystemType": "ntfs", "MountPoint": "/Volumes/EASYROMS"}
    )
    mock_run.side_effect = [
        _run_result(list_plist),
        _run_result(info_boot),
        _run_result(info_easyroms),
    ]

    partitions = _list_macos("/dev/fake-disk-test-4")

    assert [p.device_path for p in partitions] == ["/dev/fake-disk-test-4s1", "/dev/fake-disk-test-4s2"]
    assert partitions[0].filesystem == "msdos"
    assert partitions[1].filesystem == "ntfs"


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_macos_empty_when_disk_absent(mock_run):
    list_plist = plistlib.dumps({"AllDisksAndPartitions": []})
    mock_run.return_value = _run_result(list_plist)

    assert _list_macos("/dev/fake-disk-test-4") == []


# --- Linux : _list_linux -------------------------------------------------


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_linux_returns_partitions_in_disk_order(mock_run):
    lsblk_output = json.dumps(
        {
            "blockdevices": [
                {
                    "path": "/dev/fake-disk-test-sdb",
                    "children": [
                        {
                            "path": "/dev/fake-disk-test-sdb1",
                            "label": None,
                            "fstype": "vfat",
                            "mountpoints": ["/media/user/NO NAME"],
                        },
                        {
                            "path": "/dev/fake-disk-test-sdb2",
                            "label": "EASYROMS",
                            "fstype": "ntfs",
                            "mountpoints": [None],
                        },
                    ],
                }
            ]
        }
    )
    mock_run.return_value = _run_result(lsblk_output)

    partitions = _list_linux("/dev/fake-disk-test-sdb")

    assert [p.device_path for p in partitions] == ["/dev/fake-disk-test-sdb1", "/dev/fake-disk-test-sdb2"]
    assert partitions[0].label == ""
    assert partitions[1].label == "EASYROMS"


# --- Windows : _list_windows ---------------------------------------------


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_returns_partitions_with_drive_letters(mock_run):
    volumes = json.dumps(
        [
            {"FileSystemLabel": "", "FileSystem": "FAT32", "DriveLetter": "E"},
            {"FileSystemLabel": "EASYROMS", "FileSystem": "NTFS", "DriveLetter": "F"},
        ]
    )
    mock_run.return_value = _run_result(volumes)

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert [p.mountpoint for p in partitions] == ["E:\\", "F:\\"]


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_single_volume_result_is_not_a_bare_dict(mock_run):
    # Get-Volume | ConvertTo-Json renvoie un objet nu, pas une liste, s'il
    # n'y a qu'un seul volume sur le disque.
    mock_run.return_value = _run_result(
        json.dumps({"FileSystemLabel": "", "FileSystem": "FAT32", "DriveLetter": "E"})
    )

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert len(partitions) == 1
    assert partitions[0].mountpoint == "E:\\"


def test_list_windows_rejects_invalid_device_path():
    with pytest.raises(ValueError):
        _list_windows("/dev/fake-disk-test-sdb")


# --- find_partition : dispatch par OS ---------------------------------------


@patch("r36s_studio.partitions.locate.platform.system", return_value="Bidule")
def test_find_partition_raises_on_unsupported_os(mock_platform):
    with pytest.raises(NotImplementedError):
        find_partition("/dev/whatever", "BOOT")


# --- locate_mounted : attente + montage actif sur Linux ---------------------


@patch("r36s_studio.partitions.locate.time.sleep")
@patch("r36s_studio.partitions.locate.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.locate.find_partition")
def test_locate_mounted_returns_immediately_when_already_mounted(
    mock_find, mock_platform, mock_sleep
):
    mock_find.return_value = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", "/Volumes/BOOT")

    partition = locate_mounted("/dev/fake-disk-test-4", "BOOT")

    assert partition.mountpoint == "/Volumes/BOOT"
    mock_sleep.assert_not_called()


@patch("r36s_studio.partitions.locate._mount_macos", side_effect=lambda p: p)
@patch("r36s_studio.partitions.locate.time.sleep")
@patch("r36s_studio.partitions.locate.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.locate.find_partition")
def test_locate_mounted_polls_until_macos_auto_mounts(
    mock_find, mock_platform, mock_sleep, mock_mount_macos
):
    """`_mount_macos` est neutralisé (renvoie la partition inchangée) pour
    isoler ce test de l'attente passive qu'il vérifie -- le montage actif
    lui-même est couvert par `test_locate_mounted_actively_mounts_on_macos`
    et les tests dédiés de `_mount_macos`. Sans ce mock, un vrai `diskutil
    mount` serait exécuté sur la machine qui fait tourner les tests --
    risque confirmé lors du développement : un vrai disque externe branché
    sur la machine de dev correspondait par coïncidence au chemin factice
    alors utilisé ici (avant le renommage en `fake-disk-test-*`, voir
    `conftest.py`), et a été monté pour de vrai avant que ce mock ne soit
    ajouté."""
    mock_find.side_effect = [
        PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", None),
        PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", None),
        PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", "/Volumes/BOOT"),
    ]

    partition = locate_mounted("/dev/fake-disk-test-4", "BOOT", timeout=10, poll_interval=0)

    assert partition.mountpoint == "/Volumes/BOOT"
    assert mock_sleep.call_count == 2


@patch("r36s_studio.partitions.locate._mount_macos", side_effect=lambda p: p)
@patch("r36s_studio.partitions.locate.time.sleep")
@patch("r36s_studio.partitions.locate.time.monotonic", side_effect=[0, 100])
@patch("r36s_studio.partitions.locate.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.locate.find_partition")
def test_locate_mounted_raises_after_timeout(
    mock_find, mock_platform, mock_monotonic, mock_sleep, mock_mount_macos
):
    mock_find.return_value = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", None)

    with pytest.raises(PartitionNotMounted):
        locate_mounted("/dev/fake-disk-test-4", "BOOT", timeout=1, poll_interval=0)


@patch("r36s_studio.partitions.locate._mount_linux")
@patch("r36s_studio.partitions.locate.platform.system", return_value="Linux")
@patch("r36s_studio.partitions.locate.find_partition")
def test_locate_mounted_actively_mounts_on_linux(mock_find, mock_platform, mock_mount_linux):
    unmounted = PartitionInfo("/dev/fake-disk-test-sdb1", "BOOT", "vfat", None)
    mounted = PartitionInfo("/dev/fake-disk-test-sdb1", "BOOT", "vfat", "/media/user/BOOT")
    mock_find.return_value = unmounted
    mock_mount_linux.return_value = mounted

    partition = locate_mounted("/dev/fake-disk-test-sdb", "BOOT")

    assert partition.mountpoint == "/media/user/BOOT"
    mock_mount_linux.assert_called_once_with(unmounted)


@patch("r36s_studio.partitions.locate._mount_macos")
@patch("r36s_studio.partitions.locate.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.locate.find_partition")
def test_locate_mounted_actively_mounts_on_macos(mock_find, mock_platform, mock_mount_macos):
    """Le bug corrigé : une partition démontée au préalable (flash
    précédent, `hdiutil detach`...) ne remonte jamais toute seule sur
    macOS -- `locate_mounted` doit monter activement via `diskutil mount`,
    pas seulement attendre, comme il le fait déjà sur Linux."""
    unmounted = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", None)
    mounted = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", "/Volumes/BOOT")
    mock_find.return_value = unmounted
    mock_mount_macos.return_value = mounted

    partition = locate_mounted("/dev/fake-disk-test-4", "BOOT")

    assert partition.mountpoint == "/Volumes/BOOT"
    mock_mount_macos.assert_called_once_with(unmounted)


# --- macOS : _mount_macos -------------------------------------------------


@patch("r36s_studio.partitions.locate._macos_info")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_invokes_diskutil_mount_with_partition_device_path(mock_run, mock_info):
    mock_run.return_value = _run_result(returncode=0)
    mock_info.return_value = {"MountPoint": "/Volumes/BOOT"}
    partition = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", None)

    _mount_macos(partition)

    mock_run.assert_called_once_with(
        ["diskutil", "mount", "/dev/fake-disk-test-4s1"], capture_output=True, text=True
    )


@patch("r36s_studio.partitions.locate._macos_info")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_returns_updated_mountpoint_on_success(mock_run, mock_info):
    mock_run.return_value = _run_result(returncode=0)
    mock_info.return_value = {"MountPoint": "/Volumes/BOOT"}
    partition = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", None)

    result = _mount_macos(partition)

    assert result.mountpoint == "/Volumes/BOOT"


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_leaves_partition_unchanged_on_failure(mock_run):
    mock_run.return_value = _run_result(returncode=1)
    partition = PartitionInfo("/dev/fake-disk-test-4s1", "BOOT", "msdos", None)

    result = _mount_macos(partition)

    assert result == partition
