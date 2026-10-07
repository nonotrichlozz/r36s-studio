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

from r36s_studio.partitions import locate
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
    _macos_partition_type,
    _mount_macos,
    _select_boot,
    _select_easyroms,
    find_partition,
    has_boot_partition,
    locate_mounted,
    looks_like_arkos,
    selected_easyroms_partition,
    unmount_forced,
)


def _run_result(stdout=b"", returncode=0):
    result = MagicMock()
    result.stdout = stdout
    result.returncode = returncode
    return result


@pytest.fixture(autouse=True)
def _clear_forced_mountpoints():
    """`_FORCED_MOUNTPOINTS` (locate.py) est un registre au niveau module --
    évite qu'un montage forcé enregistré par un test fuite vers le
    suivant."""
    locate._FORCED_MOUNTPOINTS.clear()
    yield
    locate._FORCED_MOUNTPOINTS.clear()


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


def test_select_boot_accepts_efi_type_first_partition_when_filesystem_unknown():
    """Cas confirmé sur du vrai matériel : certaines cartes R36S d'origine
    ont un schéma GPT avec une première partition de type EFI contenant
    malgré tout un FAT16 valide -- macOS ne rapporte pas toujours un
    système de fichiers exploitable pour ce type précis (note de module),
    ce que `_select_boot` doit accepter quand même via `partition_type`."""
    partitions = [
        PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi"),
        PartitionInfo("/dev/fake-disk-test-2s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-2s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
    ]

    boot = _select_boot(partitions, "/dev/fake-disk-test-2")

    assert boot.device_path == "/dev/fake-disk-test-2s1"


def test_select_boot_accepts_efi_type_first_partition_with_known_fat_filesystem():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-2s1", "", "fat16", None, partition_type="efi"),
    ]

    boot = _select_boot(partitions, "/dev/fake-disk-test-2")

    assert boot.device_path == "/dev/fake-disk-test-2s1"


def test_select_boot_rejects_efi_type_first_partition_with_non_fat_filesystem():
    """Le type EFI seul ne suffit pas -- s'il est certain (et non pas
    juste inconnu) que le système de fichiers n'est pas un FAT, ce n'est
    pas le cas confirmé sur du vrai matériel qui justifie ce repli."""
    partitions = [PartitionInfo("/dev/fake-disk-test-2s1", "", "hfs", None, partition_type="efi")]

    with pytest.raises(PartitionNotFound):
        _select_boot(partitions, "/dev/fake-disk-test-2")


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


def test_select_easyroms_position_fallback_accepts_exfat_too():
    # Confirmé sur du vrai matériel : le système de fichiers d'EASYROMS
    # varie selon le vendeur (NTFS constaté ailleurs, exFAT ici) -- une
    # info, jamais un critère d'exclusion.
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat32", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "", "exfat", None),
    ]

    easyroms = _select_easyroms(partitions, "/dev/fake-disk-test-4")

    assert easyroms.device_path == "/dev/fake-disk-test-4s3"


def test_select_easyroms_labeled_exfat_found_regardless_of_filesystem():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat32", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "EASYROMS", "exfat", "D:\\"),
    ]

    easyroms = _select_easyroms(partitions, "/dev/fake-disk-test-4")

    assert easyroms.device_path == "/dev/fake-disk-test-4s3"
    assert easyroms.filesystem == "exfat"


def test_selected_easyroms_partition_returns_it_when_found():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat32", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "EASYROMS", "exfat", "D:\\"),
    ]

    easyroms = selected_easyroms_partition(partitions)

    assert easyroms is not None
    assert easyroms.filesystem == "exfat"


def test_selected_easyroms_partition_returns_none_when_not_found():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ntfs", None),
    ]

    assert selected_easyroms_partition(partitions) is None


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


# --- looks_like_arkos (utilisé par detect.detect_workflow_status, §4.5) ---


def test_looks_like_arkos_true_for_unlabeled_boot_and_labeled_easyroms():
    partitions = [
        PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", "/Volumes/NO NAME"),
        PartitionInfo("/dev/fake-disk-test-4s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-4s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
    ]

    assert looks_like_arkos(partitions) is True


def test_looks_like_arkos_false_when_easyroms_missing():
    partitions = [PartitionInfo("/dev/fake-disk-test-4s1", "", "fat16", None)]

    assert looks_like_arkos(partitions) is False


def test_looks_like_arkos_false_for_empty_partition_list():
    assert looks_like_arkos([]) is False


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


@patch("r36s_studio.partitions.locate.platform.system", return_value="Darwin")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_find_partition_easyroms_detected_as_ntfs_despite_windows_ntfs_field(mock_run, mock_system):
    """Bout en bout, via `_list_macos`/`find_partition` : la valeur de
    champ suspectée par le rapport de bug ne doit plus faire échapper la
    partition à la détection NTFS.

    `platform.system` mocké explicitement (diagnostic CI Windows) :
    `find_partition`/`list_partitions` dispatchent sur le vrai
    `platform.system()`, jamais mocké ici avant -- sur un runner Linux/
    Windows, ça appelait pour de vrai `_list_linux`/`_list_windows` sur des
    données mockées au format plist macOS (`JSONDecodeError`/`TypeError`
    selon l'OS), plutôt que `_list_macos` comme le nom et le docstring du
    test l'annoncent."""
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


# --- macOS : BOOT en GPT/EFI -- cas confirmé sur du vrai matériel ----------
#
# Structure relevée : disk2s1 type EFI « NO NAME » FAT16 (Image, uInitrd,
# extlinux/, .bmp de batterie, deux .dtb), disk2s2 Linux, disk2s3
# Microsoft Basic Data « EASYROMS ». macOS refuse `diskutil mount` sur
# disk2s1 à cause de son type EFI, alors qu'un `mount -t msdos` forcé y
# donne accès sans problème.


def test_macos_partition_type_normalizes_content_to_lowercase():
    assert _macos_partition_type({"Content": "EFI"}) == "efi"


def test_macos_partition_type_empty_when_content_absent():
    assert _macos_partition_type({}) == ""


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_macos_populates_partition_type_from_content(mock_run):
    list_plist = plistlib.dumps(
        {
            "AllDisksAndPartitions": [
                {
                    "DeviceIdentifier": "fake-disk-test-2",
                    "Partitions": [{"DeviceIdentifier": "fake-disk-test-2s1"}],
                }
            ]
        }
    )
    info = plistlib.dumps({"VolumeName": "", "FilesystemType": "", "Content": "EFI"})
    mock_run.side_effect = [_run_result(list_plist), _run_result(info)]

    partitions = _list_macos("/dev/fake-disk-test-2")

    assert partitions[0].partition_type == "efi"
    assert partitions[0].filesystem == ""  # non fiable pour ce type précis (note de module)


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_find_partition_boot_on_real_gpt_efi_boot_card(mock_run):
    """Reproduction bout en bout de la structure relevée sur du vrai
    matériel : disk2s1 EFI/FAT16 sans étiquette et sans FilesystemType
    exploitable, disk2s2 Linux, disk2s3 EASYROMS."""
    list_plist = plistlib.dumps(
        {
            "AllDisksAndPartitions": [
                {
                    "DeviceIdentifier": "fake-disk-test-2",
                    "Partitions": [
                        {"DeviceIdentifier": "fake-disk-test-2s1"},
                        {"DeviceIdentifier": "fake-disk-test-2s2"},
                        {"DeviceIdentifier": "fake-disk-test-2s3"},
                    ],
                }
            ]
        }
    )
    info_boot = plistlib.dumps(
        {"VolumeName": "", "FilesystemType": "", "Content": "EFI"}
    )
    info_linux = plistlib.dumps(
        {"VolumeName": "", "FilesystemType": "", "Content": "Linux Filesystem"}
    )
    info_easyroms = plistlib.dumps(
        {
            "VolumeName": "EASYROMS",
            "FilesystemType": "ntfs",
            "Content": "Microsoft Basic Data",
        }
    )
    mock_run.side_effect = [
        _run_result(list_plist),
        _run_result(info_boot),
        _run_result(info_linux),
        _run_result(info_easyroms),
    ]

    partitions = _list_macos("/dev/fake-disk-test-2")
    boot = _select_boot(partitions, "/dev/fake-disk-test-2")
    easyroms = _select_easyroms(partitions, "/dev/fake-disk-test-2")

    assert boot.device_path == "/dev/fake-disk-test-2s1"
    assert easyroms.device_path == "/dev/fake-disk-test-2s3"
    assert easyroms.filesystem == "ntfs"
    assert easyroms.partition_type == "microsoft basic data"


def test_macos_filesystem_identifies_ntfs_for_microsoft_basic_data_gpt_content():
    """`Content` vaut « Microsoft Basic Data » pour EASYROMS sur le schéma
    GPT (confirmé sur du vrai matériel), pas « Windows_NTFS » comme sur les
    cartes MBR -- `FilesystemType` (« ntfs », probé normalement par
    diskutil pour ce type ordinaire, contrairement au cas EFI ci-dessus)
    reste la source fiable de détection, indépendamment de `Content`."""
    assert _macos_filesystem({"FilesystemType": "ntfs", "Content": "Microsoft Basic Data"}) == "ntfs"


def test_select_easyroms_recognized_by_label_in_gpt_scheme_with_microsoft_basic_data_type():
    """La reconnaissance d'EASYROMS ne dépend pas de `partition_type` --
    elle reste retrouvée par étiquette, quel que soit le type de partition
    GPT/MBR sous-jacent."""
    partitions = [
        PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi"),
        PartitionInfo("/dev/fake-disk-test-2s2", "", "", None, partition_type="linux filesystem"),
        PartitionInfo(
            "/dev/fake-disk-test-2s3", "EASYROMS", "ntfs", None, partition_type="microsoft basic data"
        ),
    ]

    easyroms = _select_easyroms(partitions, "/dev/fake-disk-test-2")

    assert easyroms.device_path == "/dev/fake-disk-test-2s3"


@patch("r36s_studio.partitions.locate.tempfile.mkdtemp", return_value="/tmp/r36s-studio-test")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_falls_back_to_forced_mount_when_diskutil_mount_fails(mock_run, mock_mkdtemp):
    """`diskutil mount` échoue sur ce type de partition -- confirmé sur du
    vrai matériel -- alors qu'un `mount -t msdos` forcé sur un point de
    montage temporaire y donne accès."""
    mock_run.side_effect = [
        _run_result(returncode=1),  # diskutil mount : échec
        _run_result(returncode=0),  # mount -t msdos : réussit
    ]
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi")

    result = _mount_macos(partition)

    assert result.mountpoint == "/tmp/r36s-studio-test"
    assert mock_run.call_args_list[1].args[0] == [
        "mount",
        "-t",
        "msdos",
        "/dev/fake-disk-test-2s1",
        "/tmp/r36s-studio-test",
    ]


@patch("r36s_studio.partitions.locate.os.rmdir")
@patch("r36s_studio.partitions.locate.tempfile.mkdtemp", return_value="/tmp/r36s-studio-test")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_forced_mount_failure_removes_temp_mountpoint_and_leaves_partition_unchanged(
    mock_run, mock_mkdtemp, mock_rmdir
):
    mock_run.side_effect = [_run_result(returncode=1), _run_result(returncode=1)]
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi")

    result = _mount_macos(partition)

    assert result == partition
    mock_rmdir.assert_called_once_with("/tmp/r36s-studio-test")


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_does_not_attempt_forced_mount_for_a_known_non_fat_filesystem(mock_run):
    """Pas de tentative `mount -t msdos` pour une partition dont le
    système de fichiers connu n'est de toute façon pas un FAT (ex. NTFS)
    -- ça échouerait pour rien."""
    mock_run.return_value = _run_result(returncode=1)
    partition = PartitionInfo("/dev/fake-disk-test-2s3", "EASYROMS", "ntfs", None)

    result = _mount_macos(partition)

    assert result == partition
    mock_run.assert_called_once()  # seulement diskutil mount, jamais mount -t msdos


# --- repli élevé (§4.4, confirmé nécessaire sur du vrai matériel) : la ------
# --- GUI installe `set_privileged_mount_hook` (gui/main_window.py) quand ---
# --- le montage forcé non élevé a aussi échoué. Sans hook installé (CLI, --
# --- tests, autres OS), comportement inchangé -- déjà couvert ci-dessus. ---


@patch("r36s_studio.partitions.locate.tempfile.mkdtemp", return_value="/tmp/r36s-studio-test")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_uses_privileged_hook_when_forced_mount_also_fails(mock_run, mock_mkdtemp):
    mock_run.side_effect = [
        _run_result(returncode=1),  # diskutil mount : échec
        _run_result(returncode=1),  # mount -t msdos non élevé : échec aussi
    ]
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi")
    hook = MagicMock(return_value=True)
    locate.set_privileged_mount_hook(hook)

    result = _mount_macos(partition)

    hook.assert_called_once_with("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")
    assert result.mountpoint == "/tmp/r36s-studio-test"
    assert "/tmp/r36s-studio-test" in locate._FORCED_MOUNTPOINTS


@patch("r36s_studio.partitions.locate.os.rmdir")
@patch("r36s_studio.partitions.locate.tempfile.mkdtemp", return_value="/tmp/r36s-studio-test")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_hook_failure_removes_temp_mountpoint_and_leaves_partition_unchanged(
    mock_run, mock_mkdtemp, mock_rmdir
):
    """Une invite refusée/annulée (le hook renvoie `False`) doit se
    comporter exactement comme un hook absent -- jamais planter, jamais
    laisser un point de montage temporaire orphelin."""
    mock_run.side_effect = [_run_result(returncode=1), _run_result(returncode=1)]
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi")
    locate.set_privileged_mount_hook(MagicMock(return_value=False))

    result = _mount_macos(partition)

    assert result == partition
    mock_rmdir.assert_called_once_with("/tmp/r36s-studio-test")


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_mount_macos_does_not_invoke_hook_when_forced_mount_succeeds_unprivileged(mock_run):
    """Le repli élevé n'est tenté qu'en tout dernier recours -- si le
    montage forcé non élevé suffit déjà, jamais d'invite inutile."""
    mock_run.side_effect = [_run_result(returncode=1), _run_result(returncode=0)]
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi")
    hook = MagicMock(return_value=True)
    locate.set_privileged_mount_hook(hook)

    with patch("r36s_studio.partitions.locate.tempfile.mkdtemp", return_value="/tmp/r36s-studio-test"):
        _mount_macos(partition)

    hook.assert_not_called()


def test_set_privileged_mount_hook_none_removes_a_previously_installed_hook():
    locate.set_privileged_mount_hook(lambda device, mountpoint: True)

    locate.set_privileged_mount_hook(None)

    assert locate._privileged_mount_hook is None


@patch("r36s_studio.partitions.locate.os.rmdir")
@patch("r36s_studio.partitions.locate.subprocess.run")
def test_unmount_forced_unmounts_and_removes_temp_directory(mock_run, mock_rmdir):
    partition = PartitionInfo(
        "/dev/fake-disk-test-2s1", "", "", "/tmp/r36s-studio-test", partition_type="efi"
    )
    locate._FORCED_MOUNTPOINTS.add("/tmp/r36s-studio-test")

    unmount_forced(partition)

    mock_run.assert_called_once_with(["umount", "/tmp/r36s-studio-test"], capture_output=True)
    mock_rmdir.assert_called_once_with("/tmp/r36s-studio-test")
    assert "/tmp/r36s-studio-test" not in locate._FORCED_MOUNTPOINTS


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_unmount_forced_does_nothing_for_a_normal_diskutil_mount(mock_run):
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "BOOT", "msdos", "/Volumes/BOOT")

    unmount_forced(partition)

    mock_run.assert_not_called()


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_unmount_forced_does_nothing_when_not_mounted(mock_run):
    partition = PartitionInfo("/dev/fake-disk-test-2s1", "", "", None, partition_type="efi")

    unmount_forced(partition)

    mock_run.assert_not_called()


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


# --- taille de chaque partition, sans accès brut (§4.3, estimation de la --
# --- sauvegarde système sans les jeux -- confirmé sur du vrai matériel : --
# --- `/dev/diskN` exige les droits administrateur, contrairement à -------
# --- `diskutil info -plist`/`lsblk`/`Get-Volume`, qui donnent déjà la ----
# --- taille sans élévation). --------------------------------------------


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_macos_populates_size_bytes_from_diskutil(mock_run):
    list_plist = plistlib.dumps(
        {
            "AllDisksAndPartitions": [
                {
                    "DeviceIdentifier": "fake-disk-test-4",
                    "Partitions": [{"DeviceIdentifier": "fake-disk-test-4s1"}],
                }
            ]
        }
    )
    info = plistlib.dumps({"VolumeName": "EASYROMS", "FilesystemType": "ntfs", "Size": 9_000_000_000})
    mock_run.side_effect = [_run_result(list_plist), _run_result(info)]

    partitions = _list_macos("/dev/fake-disk-test-4")

    assert partitions[0].size_bytes == 9_000_000_000


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_macos_size_bytes_none_when_absent_from_diskutil(mock_run):
    list_plist = plistlib.dumps(
        {
            "AllDisksAndPartitions": [
                {
                    "DeviceIdentifier": "fake-disk-test-4",
                    "Partitions": [{"DeviceIdentifier": "fake-disk-test-4s1"}],
                }
            ]
        }
    )
    info = plistlib.dumps({"VolumeName": "EASYROMS", "FilesystemType": "ntfs"})
    mock_run.side_effect = [_run_result(list_plist), _run_result(info)]

    partitions = _list_macos("/dev/fake-disk-test-4")

    assert partitions[0].size_bytes is None


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


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_linux_populates_size_bytes_from_lsblk(mock_run):
    lsblk_output = json.dumps(
        {
            "blockdevices": [
                {
                    "path": "/dev/fake-disk-test-sdb",
                    "children": [
                        {
                            "path": "/dev/fake-disk-test-sdb1",
                            "label": "EASYROMS",
                            "fstype": "ntfs",
                            "mountpoints": [None],
                            "size": 9_000_000_000,
                        }
                    ],
                }
            ]
        }
    )
    mock_run.return_value = _run_result(lsblk_output)

    partitions = _list_linux("/dev/fake-disk-test-sdb")

    assert partitions[0].size_bytes == 9_000_000_000


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
def test_list_windows_populates_size_bytes_from_get_volume(mock_run):
    volumes = json.dumps([{"FileSystemLabel": "EASYROMS", "FileSystem": "NTFS", "DriveLetter": "F", "Size": 9_000_000_000}])
    mock_run.return_value = _run_result(volumes)

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert partitions[0].size_bytes == 9_000_000_000


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_reorders_by_partition_number_even_if_get_volume_returns_them_out_of_order(mock_run):
    """Confirmé sur du vrai matériel : `Get-Volume` ne préserve pas l'ordre
    de son entrée pipeline -- observé en répétant l'appel sur une carte
    réelle, l'ordre BOOT/EASYROMS alternait d'un appel à l'autre sans rien
    changer côté matériel. `_list_windows` doit donc trier lui-même sur
    `PartitionNumber` plutôt que de faire confiance à l'ordre JSON reçu."""
    volumes = json.dumps(
        [
            {"FileSystemLabel": "EASYROMS", "FileSystem": "exFAT", "DriveLetter": "F", "PartitionNumber": 3},
            {"FileSystemLabel": "", "FileSystem": "FAT32", "DriveLetter": "E", "PartitionNumber": 1},
        ]
    )
    mock_run.return_value = _run_result(volumes)

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert [p.label for p in partitions] == ["", "EASYROMS"]


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_falls_back_to_volume_guid_path_without_drive_letter(mock_run):
    """Confirmé sur du vrai matériel (ThinkPad, lecteur SD Realtek) :
    Windows n'attribue pas toujours une lettre de lecteur à une partition
    par ailleurs saine et lisible (BOOT, notamment) -- son chemin GUID de
    volume (`AccessPaths`, exposé par `Get-Partition`) reste lisible sans
    élévation et sert de repli plutôt que d'attendre en vain une lettre
    qui n'arrivera jamais."""
    guid_path = "\\\\?\\Volume{e3bd7e11-49fd-11f1-b992-f859711d251c}\\"
    volumes = json.dumps(
        [
            {
                "FileSystemLabel": "BOOT",
                "FileSystem": "FAT32",
                "DriveLetter": None,
                "PartitionNumber": 1,
                "VolumeGuidPath": guid_path,
            }
        ]
    )
    mock_run.return_value = _run_result(volumes)

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert partitions[0].mountpoint == guid_path


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_prefers_drive_letter_over_volume_guid_path_when_both_present(mock_run):
    volumes = json.dumps(
        [
            {
                "FileSystemLabel": "EASYROMS",
                "FileSystem": "exFAT",
                "DriveLetter": "D",
                "PartitionNumber": 3,
                "VolumeGuidPath": "\\\\?\\Volume{38185839-a70c-11f1-b997-f859711d251c}\\",
            }
        ]
    )
    mock_run.return_value = _run_result(volumes)

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert partitions[0].mountpoint == "D:\\"


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_no_drive_letter_and_no_guid_path_leaves_unmounted(mock_run):
    """Repli absent (cas résiduel, jamais observé en pratique mais pas
    supposé impossible) -- `mountpoint` reste `None`, pour que
    `locate_mounted` retombe sur son comportement d'origine (attente puis
    `PartitionNotMounted`) plutôt que de planter sur un chemin manquant."""
    volumes = json.dumps(
        [{"FileSystemLabel": "BOOT", "FileSystem": "FAT32", "DriveLetter": None, "PartitionNumber": 1}]
    )
    mock_run.return_value = _run_result(volumes)

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert partitions[0].mountpoint is None


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_treats_zero_size_as_unknown(mock_run):
    """Confirmé sur du vrai matériel : `Get-Volume` renvoie `Size: 0` (pas
    absent) pour une partition dont Windows ne reconnaît pas le système de
    fichiers (ext4, la partition root d'une carte ArkOS) -- traité comme
    `None` (taille inconnue), jamais comme une vraie partition de 0 octet,
    pour que l'estimation non élevée (§4.3) retombe sur son repli élevé au
    lieu de sous-compter silencieusement."""
    volumes = json.dumps([{"FileSystemLabel": "", "FileSystem": "", "DriveLetter": None, "Size": 0}])
    mock_run.return_value = _run_result(volumes)

    partitions = _list_windows(r"\\.\PhysicalDrive9903")

    assert partitions[0].size_bytes is None


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


# Relevé réel (carte ArkOS 256 Go, GPT, 2026-10-07) : Windows ne rapporte
# aucun volume pour la partition EFI (BOOT) -- seule la partition elle-même.
_EFI = "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}"
_ARKOS_GPT_WINDOWS = [
    {"PartitionNumber": 1, "GptType": _EFI, "DriveLetter": "I", "FileSystem": None, "FileSystemLabel": "", "Size": 536870912},
    {"PartitionNumber": 2, "GptType": "{0fc63daf-8483-4772-8e79-3d69d8477de4}", "DriveLetter": "D", "FileSystem": "", "FileSystemLabel": "", "Size": 0},
    {"PartitionNumber": 3, "GptType": "{ebd0a0a2-b9e5-4433-87c0-68b6b72699c7}", "DriveLetter": "E", "FileSystem": "exFAT", "FileSystemLabel": "EASYROMS", "Size": 246716170240},
]


@patch("r36s_studio.partitions.locate.subprocess.run")
def test_list_windows_keeps_the_efi_boot_partition_and_marks_it_efi(mock_run):
    """Bug corrigé : la BOOT EFI disparaissait (aucun volume côté Windows),
    la carte n'était plus reconnue comme ArkOS."""
    mock_run.return_value = _run_result(json.dumps(_ARKOS_GPT_WINDOWS))

    partitions = _list_windows(r"\\.\PhysicalDrive9902")

    assert [(p.mountpoint, p.partition_type) for p in partitions] == [("I:\\", "efi"), ("D:\\", ""), ("E:\\", "")]
    assert has_boot_partition(partitions) and looks_like_arkos(partitions)


def test_list_windows_asks_powershell_to_keep_only_efi_partitions_without_volume():
    """Une partition réservée Microsoft (MSR) n'a pas de volume non plus :
    la garder décalerait la détection par position. Seul le type EFI passe."""
    with patch("r36s_studio.partitions.locate.subprocess.run", return_value=_run_result("")) as mock_run:
        _list_windows(r"\\.\PhysicalDrive9902")

    command = mock_run.call_args.args[0][-1]
    assert "elseif ($p.GptType -eq '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}')" in command
    assert "e3c9e316" not in command  # jamais la partition MSR


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
