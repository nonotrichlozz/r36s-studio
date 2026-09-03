"""Tests du module detect (§4.5) : statut des six étapes du workflow à
deux cartes pour la carte actuellement branchée. `list_partitions` et
`archives.list_archives` sont mockés — aucune carte réelle n'est touchée,
aucune commande système réelle n'est appelée."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from r36s_studio.detect import (
    COPY_GAMES,
    EJECT,
    EXTRACT_BOOT,
    EXTRACT_EASYROMS,
    FLASH,
    INJECT_BOOT,
    CardSystem,
    StepStatus,
    detect_card_system,
    detect_workflow_status,
)
from r36s_studio.devices import Device
from r36s_studio.partitions.locate import PartitionInfo


def _make_device(path="/dev/fake-disk-test-3") -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


# --- aucune carte : tout non pertinent, sauf rien -------------------------


@patch("r36s_studio.detect.platform.system", return_value="Linux")
def test_no_device_marks_every_step_not_relevant(mock_platform):
    status = detect_workflow_status(None)

    assert all(value == StepStatus.NOT_RELEVANT for value in status.values())
    assert set(status) == {EXTRACT_BOOT, EXTRACT_EASYROMS, FLASH, INJECT_BOOT, COPY_GAMES, EJECT}


# --- carte vierge (BLANK) : seul le flash est faisable ---------------------


@patch("r36s_studio.detect.platform.system", return_value="Linux")
@patch("r36s_studio.detect.archives.list_archives", return_value=[])
@patch("r36s_studio.detect.list_partitions", return_value=[])
def test_blank_card_only_flash_available_and_eject(mock_list, mock_archives, mock_platform):
    status = detect_workflow_status(_make_device())

    assert status[FLASH] == StepStatus.AVAILABLE
    assert status[EJECT] == StepStatus.AVAILABLE
    assert status[EXTRACT_BOOT] == StepStatus.NOT_RELEVANT
    assert status[EXTRACT_EASYROMS] == StepStatus.NOT_RELEVANT
    assert status[INJECT_BOOT] == StepStatus.NOT_RELEVANT
    assert status[COPY_GAMES] == StepStatus.NOT_RELEVANT


# --- carte déjà ArkOS (ancienne carte du workflow) -------------------------


@patch("r36s_studio.detect.platform.system", return_value="Linux")
@patch("r36s_studio.detect.archives.list_archives", return_value=[])
@patch("r36s_studio.detect.list_partitions")
def test_arkos_card_without_archives_extraction_available_injection_available(
    mock_list, mock_archives, mock_platform
):
    """La carte source du workflow (déjà flashée) : on peut en extraire le
    BOOT/EASYROMS (aucune archive encore) ; comme elle est déjà ArkOS,
    l'injection y a aussi un sens (on pourrait réinjecter directement
    dessus) et le flash est marqué comme déjà fait."""
    mock_list.return_value = [
        PartitionInfo("/dev/fake-disk-test-3s1", "", "fat16", "/Volumes/NO NAME"),
        PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-3s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
    ]

    status = detect_workflow_status(_make_device())

    assert status[EXTRACT_BOOT] == StepStatus.AVAILABLE
    assert status[EXTRACT_EASYROMS] == StepStatus.AVAILABLE
    assert status[FLASH] == StepStatus.DONE
    assert status[INJECT_BOOT] == StepStatus.AVAILABLE
    assert status[COPY_GAMES] == StepStatus.AVAILABLE
    assert status[EJECT] == StepStatus.AVAILABLE


@patch("r36s_studio.detect.list_partitions")
def test_arkos_card_with_existing_archives_marks_extraction_done(mock_list):
    mock_list.return_value = [
        PartitionInfo("/dev/fake-disk-test-3s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-3s3", "EASYROMS", "ntfs", None),
    ]

    def _fake_archives(label, base_dir=None):
        return ["une_archive"] if label == "BOOT" else []

    with patch("r36s_studio.detect.archives.list_archives", side_effect=_fake_archives):
        status = detect_workflow_status(_make_device())

    assert status[EXTRACT_BOOT] == StepStatus.DONE
    assert status[EXTRACT_EASYROMS] == StepStatus.AVAILABLE


# --- carte d'origine (une seule partition FAT, sans BOOT/EASYROMS) ---------


@patch("r36s_studio.detect.platform.system", return_value="Linux")
@patch("r36s_studio.detect.list_partitions")
def test_single_fat_partition_card_boot_extraction_available_easyroms_not(mock_list, mock_platform):
    """Carte d'origine à une seule partition : elle passe pour BOOT
    (première partition FAT) mais pas pour EASYROMS (pas de troisième
    partition) -- reflet honnête des capacités du module `partitions/`."""
    mock_list.return_value = [PartitionInfo("/dev/fake-disk-test-3s1", "", "fat32", "/Volumes/NO NAME")]

    with patch("r36s_studio.detect.archives.list_archives", return_value=[]):
        status = detect_workflow_status(_make_device())

    assert status[EXTRACT_BOOT] == StepStatus.AVAILABLE
    assert status[EXTRACT_EASYROMS] == StepStatus.NOT_RELEVANT
    assert status[FLASH] == StepStatus.AVAILABLE  # pas encore ArkOS
    assert status[INJECT_BOOT] == StepStatus.NOT_RELEVANT  # pas encore de partition BOOT à injecter
    assert status[COPY_GAMES] == StepStatus.NOT_RELEVANT


# --- pas de partition du tout (table illisible / OS non supporté) --------


@patch("r36s_studio.detect.list_partitions", side_effect=NotImplementedError("OS non supporté"))
def test_unsupported_os_falls_back_to_not_relevant_without_raising(mock_list):
    status = detect_workflow_status(_make_device())

    assert status[EXTRACT_BOOT] == StepStatus.NOT_RELEVANT
    assert status[INJECT_BOOT] == StepStatus.NOT_RELEVANT
    # Le flash reste "faisable" par défaut : contrairement à
    # l'extraction/l'injection, il ne dépend pas de partitions existantes
    # -- une lecture ratée ne doit pas empêcher de proposer de flasher.
    assert status[FLASH] == StepStatus.AVAILABLE


@patch("r36s_studio.detect.platform.system", return_value="Linux")
@patch("r36s_studio.detect.list_partitions", side_effect=OSError("carte débranchée"))
def test_read_error_falls_back_to_not_relevant_without_raising(mock_list, mock_platform):
    status = detect_workflow_status(_make_device())

    assert all(status[step] in (StepStatus.NOT_RELEVANT, StepStatus.AVAILABLE) for step in status)
    assert status[EJECT] == StepStatus.AVAILABLE  # une carte est bien branchée, malgré l'échec de lecture


@patch(
    "r36s_studio.detect.list_partitions",
    side_effect=subprocess.CalledProcessError(1, ["diskutil"]),
)
def test_failed_system_command_falls_back_to_not_relevant_without_raising(mock_list):
    status = detect_workflow_status(_make_device())

    assert status[EXTRACT_BOOT] == StepStatus.NOT_RELEVANT
    assert status[FLASH] == StepStatus.AVAILABLE


# --- copy_games (étape E) limité par la plateforme sur macOS (§4.4) -------
#
# EASYROMS est en NTFS sur une vraie carte R36S ; macOS ne monte le NTFS
# qu'en lecture seule, donc cette étape échoue toujours sur cet OS, quelle
# que soit la carte branchée -- une limite de la plateforme, pas de la
# carte (badge « PC ou Linux » sur l'accueil).


@patch("r36s_studio.detect.platform.system", return_value="Darwin")
def test_copy_games_platform_limited_on_macos_without_any_card(mock_platform):
    status = detect_workflow_status(None)

    assert status[COPY_GAMES] == StepStatus.PLATFORM_LIMITED


@patch("r36s_studio.detect.platform.system", return_value="Darwin")
@patch("r36s_studio.detect.archives.list_archives", return_value=[])
@patch("r36s_studio.detect.list_partitions")
def test_copy_games_platform_limited_on_macos_even_with_arkos_card(mock_list, mock_archives, mock_platform):
    """Sur macOS, même une carte déjà ArkOS (où l'injection aurait
    normalement un sens) ne rend pas l'étape faisable -- la limite est
    celle du système d'exploitation, pas de la carte."""
    mock_list.return_value = [
        PartitionInfo("/dev/fake-disk-test-3s1", "", "fat16", "/Volumes/NO NAME"),
        PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-3s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
    ]

    status = detect_workflow_status(_make_device())

    assert status[COPY_GAMES] == StepStatus.PLATFORM_LIMITED
    # Les autres étapes ne sont pas concernées par cette limite.
    assert status[INJECT_BOOT] == StepStatus.AVAILABLE


@patch("r36s_studio.detect.platform.system", return_value="Darwin")
@patch("r36s_studio.detect.archives.list_archives", return_value=[])
@patch("r36s_studio.detect.list_partitions")
def test_copy_games_not_platform_limited_on_macos_when_easyroms_is_exfat(mock_list, mock_archives, mock_platform):
    """Confirmé sur du vrai matériel : EASYROMS peut être en exFAT selon le
    vendeur -- macOS écrit l'exFAT nativement (contrairement au NTFS), donc
    l'étape ne doit plus être marquée limitée par la plateforme une fois
    cette carte positivement identifiée comme telle."""
    mock_list.return_value = [
        PartitionInfo("/dev/fake-disk-test-3s1", "", "fat16", "/Volumes/NO NAME"),
        PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-3s3", "EASYROMS", "exfat", "/Volumes/EASYROMS"),
    ]

    status = detect_workflow_status(_make_device())

    assert status[COPY_GAMES] == StepStatus.AVAILABLE


@patch("r36s_studio.detect.platform.system", return_value="Windows")
@patch("r36s_studio.detect.archives.list_archives", return_value=[])
@patch("r36s_studio.detect.list_partitions")
def test_copy_games_not_platform_limited_outside_macos(mock_list, mock_archives, mock_platform):
    mock_list.return_value = [
        PartitionInfo("/dev/fake-disk-test-3s1", "", "fat16", None),
        PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
        PartitionInfo("/dev/fake-disk-test-3s3", "EASYROMS", "ntfs", None),
    ]

    status = detect_workflow_status(_make_device())

    assert status[COPY_GAMES] == StepStatus.AVAILABLE


# --- CardSystem / detect_card_system : ArkOS vs ROCKNIX vs inconnu --------
#
# Structure ROCKNIX relevée sur du vrai matériel (§4.5) : schéma MBR, deux
# partitions seulement -- première étiquetée ROCKNIX en FAT32 (~2,1 Go),
# seconde Linux (~29,8 Go, opaque depuis macOS/Windows). Aucune partition
# de jeux séparée.

_ROCKNIX_PARTITIONS = [
    PartitionInfo("/dev/fake-disk-test-3s1", "ROCKNIX", "fat32", "/Volumes/ROCKNIX"),
    PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
]

_ARKOS_PARTITIONS = [
    PartitionInfo("/dev/fake-disk-test-3s1", "", "fat16", "/Volumes/NO NAME"),
    PartitionInfo("/dev/fake-disk-test-3s2", "", "ext4", None),
    PartitionInfo("/dev/fake-disk-test-3s3", "EASYROMS", "ntfs", "/Volumes/EASYROMS"),
]


def test_detect_card_system_recognizes_rocknix_by_boot_label():
    assert detect_card_system(_ROCKNIX_PARTITIONS) == CardSystem.ROCKNIX


def test_detect_card_system_label_check_is_case_insensitive():
    partitions = [PartitionInfo("/dev/x1", "rocknix", "fat32", None)]

    assert detect_card_system(partitions) == CardSystem.ROCKNIX


def test_detect_card_system_recognizes_arkos():
    assert detect_card_system(_ARKOS_PARTITIONS) == CardSystem.ARKOS


def test_detect_card_system_unknown_for_blank_card():
    assert detect_card_system([]) == CardSystem.UNKNOWN


def test_detect_card_system_unknown_when_partitions_unreadable():
    assert detect_card_system(None) == CardSystem.UNKNOWN


def test_detect_card_system_unknown_for_unrecognized_structure():
    partitions = [PartitionInfo("/dev/x1", "", "exfat", None)]

    assert detect_card_system(partitions) == CardSystem.UNKNOWN


# --- detect_workflow_status : carte ROCKNIX -- A/B/D/E incompatibles ------
#
# Sur une carte ROCKNIX, seuls le flash et l'éjection ont du sens (le
# module `detect` ne connaît pas la sauvegarde complète, hors des six
# étapes lettrées, §4.6) -- les quatre autres étapes affichent un badge
# visible expliquant pourquoi, plutôt qu'un `NOT_RELEVANT` sans badge.


@patch("r36s_studio.detect.platform.system", return_value="Linux")
@patch("r36s_studio.detect.list_partitions", return_value=_ROCKNIX_PARTITIONS)
def test_rocknix_card_marks_boot_easyroms_inject_copy_as_system_incompatible(mock_list, mock_platform):
    status = detect_workflow_status(_make_device())

    assert status[EXTRACT_BOOT] == StepStatus.SYSTEM_INCOMPATIBLE
    assert status[EXTRACT_EASYROMS] == StepStatus.SYSTEM_INCOMPATIBLE
    assert status[INJECT_BOOT] == StepStatus.SYSTEM_INCOMPATIBLE
    assert status[COPY_GAMES] == StepStatus.SYSTEM_INCOMPATIBLE


@patch("r36s_studio.detect.platform.system", return_value="Linux")
@patch("r36s_studio.detect.list_partitions", return_value=_ROCKNIX_PARTITIONS)
def test_rocknix_card_flash_and_eject_remain_available(mock_list, mock_platform):
    status = detect_workflow_status(_make_device())

    assert status[FLASH] == StepStatus.AVAILABLE
    assert status[EJECT] == StepStatus.AVAILABLE


@patch("r36s_studio.detect.platform.system", return_value="Darwin")
@patch("r36s_studio.detect.list_partitions", return_value=_ROCKNIX_PARTITIONS)
def test_rocknix_card_copy_games_is_system_incompatible_even_on_macos(mock_list, mock_platform):
    """La vraie raison est le système de la carte (pas de partition de
    jeux séparée du tout), pas la limitation NTFS de macOS -- ne doit pas
    régresser vers PLATFORM_LIMITED, moins précis ici."""
    status = detect_workflow_status(_make_device())

    assert status[COPY_GAMES] == StepStatus.SYSTEM_INCOMPATIBLE
