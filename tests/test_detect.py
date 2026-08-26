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
    StepStatus,
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


def test_no_device_marks_every_step_not_relevant():
    status = detect_workflow_status(None)

    assert all(value == StepStatus.NOT_RELEVANT for value in status.values())
    assert set(status) == {EXTRACT_BOOT, EXTRACT_EASYROMS, FLASH, INJECT_BOOT, COPY_GAMES, EJECT}


# --- carte vierge (BLANK) : seul le flash est faisable ---------------------


@patch("r36s_studio.detect.archives.list_archives", return_value=[])
@patch("r36s_studio.detect.list_partitions", return_value=[])
def test_blank_card_only_flash_available_and_eject(mock_list, mock_archives):
    status = detect_workflow_status(_make_device())

    assert status[FLASH] == StepStatus.AVAILABLE
    assert status[EJECT] == StepStatus.AVAILABLE
    assert status[EXTRACT_BOOT] == StepStatus.NOT_RELEVANT
    assert status[EXTRACT_EASYROMS] == StepStatus.NOT_RELEVANT
    assert status[INJECT_BOOT] == StepStatus.NOT_RELEVANT
    assert status[COPY_GAMES] == StepStatus.NOT_RELEVANT


# --- carte déjà ArkOS (ancienne carte du workflow) -------------------------


@patch("r36s_studio.detect.archives.list_archives", return_value=[])
@patch("r36s_studio.detect.list_partitions")
def test_arkos_card_without_archives_extraction_available_injection_available(mock_list, mock_archives):
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


@patch("r36s_studio.detect.list_partitions")
def test_single_fat_partition_card_boot_extraction_available_easyroms_not(mock_list):
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


@patch("r36s_studio.detect.list_partitions", side_effect=OSError("carte débranchée"))
def test_read_error_falls_back_to_not_relevant_without_raising(mock_list):
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
