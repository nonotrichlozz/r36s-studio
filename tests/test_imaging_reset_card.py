"""Tests de « Remettre la carte à zéro » (imaging/reset_card.py) -- efface
toute la table de partitions et recrée une seule partition exFAT occupant
toute la carte, en deux étapes distinctes (`erase_partition_table`/
`create_single_partition`). Même style que `test_imaging_games_
partition.py` : jeux de données factices, reparsing indépendant du
secteur produit, aucune carte réelle. `format_games_partition` (appels OS
natifs) est mockée -- déjà couverte séparément dans `test_imaging_games_
partition.py`."""

from __future__ import annotations

import contextlib
from unittest.mock import patch

import pytest

from r36s_studio.devices import Device
from r36s_studio.imaging.fat32 import Fat32VolumeTooSmall
from r36s_studio.imaging.games_partition import ALIGNMENT_SECTORS, MBR_NTFS_EXFAT_PARTITION_TYPE
from r36s_studio.imaging.mbr import parse_mbr
from r36s_studio.imaging.reset_card import (
    MBR_FAT32_LBA_PARTITION_TYPE,
    CardTooSmallForReset,
    ResetCardPlan,
    build_full_disk_mbr_sector,
    check_fat32_feasible,
    create_single_partition,
    erase_partition_table,
    format_reset_partition,
    plan_full_disk_partition,
)

SECTOR_SIZE = 512


@contextlib.contextmanager
def _no_prep(device):
    yield device.path


def _make_device(path: str, size_bytes: int) -> Device:
    return Device(
        path=path, display="Carte SD factice", size_bytes=size_bytes, removable=True, bus="USB",
        is_system=False, mountpoints=[],
    )


def _make_fake_device_file(tmp_path, name, total_sectors=200_000, first_sector=None):
    path = tmp_path / name
    with open(path, "wb") as f:
        f.write(first_sector or bytes(SECTOR_SIZE))
        f.seek(total_sectors * SECTOR_SIZE - 1)
        f.write(b"\x00")
    return str(path)


# --- planification -----------------------------------------------------------


def test_plan_full_disk_partition_starts_aligned_and_covers_almost_the_whole_disk():
    plan = plan_full_disk_partition(total_sectors=200_000)

    assert plan.start_lba == ALIGNMENT_SECTORS
    assert plan.start_lba % ALIGNMENT_SECTORS == 0
    assert plan.end_lba == 200_000 - 1 - ALIGNMENT_SECTORS
    assert plan.size_bytes == (plan.end_lba - plan.start_lba + 1) * SECTOR_SIZE


def test_plan_full_disk_partition_raises_on_a_too_small_disk():
    with pytest.raises(CardTooSmallForReset):
        plan_full_disk_partition(total_sectors=ALIGNMENT_SECTORS)


# --- vérification préalable FAT32 (avant toute écriture) ---------------------


def test_check_fat32_feasible_does_not_raise_on_a_realistic_sd_card_size():
    """Cas réel qui motive le choix FAT32 : une carte de 128 Go -- doit
    passer sans lever, quelle que soit la taille, puisque le formateur à
    la main (`imaging/fat32.py`) n'a pas la limite de 32 Go de l'outil
    Windows standard."""
    device = _make_device("/dev/fake-disk-test-1", 128 * 1024 * 1024 * 1024)

    check_fat32_feasible(device)  # ne lève pas


def test_check_fat32_feasible_raises_before_any_write_when_volume_is_too_small():
    """Demande explicite : « si le FAT32 s'avère impossible sur une taille
    donnée, le dire clairement avant de lancer l'opération, jamais après »
    -- cette fonction ne touche jamais le périphérique (pas de
    `prepared_write_target`), donc aucune écriture n'a pu avoir lieu avant
    qu'elle ne lève."""
    device = _make_device("/dev/fake-disk-test-1", 20 * 1024 * 1024)  # bien en dessous du minimum FAT32

    with pytest.raises(Fat32VolumeTooSmall):
        check_fat32_feasible(device)


# --- construction du secteur MBR neuf ----------------------------------------


def test_build_full_disk_mbr_sector_reparses_to_a_single_partition():
    plan = plan_full_disk_partition(total_sectors=200_000)

    sector = build_full_disk_mbr_sector(plan)

    assert len(sector) == SECTOR_SIZE
    assert sector[510:512] == b"\x55\xaa"
    reparsed = parse_mbr(sector)
    assert len(reparsed) == 1
    entry = reparsed[0]
    assert entry.partition_type == MBR_NTFS_EXFAT_PARTITION_TYPE
    assert entry.start_lba == plan.start_lba
    assert entry.sector_count == plan.end_lba - plan.start_lba + 1


def test_build_full_disk_mbr_sector_only_ever_carries_one_entry_and_the_signature():
    """Contrairement à `rewrite_mbr_with_games_partition` (`games_
    partition.py`), qui préserve les entrées déjà présentes dans un
    secteur existant, cette fonction ne lit jamais de secteur d'origine --
    tout le reste du secteur (code de démarrage, trois créneaux de
    partition restants) doit donc rester à zéro, quelle que soit la table
    précédente sur la vraie carte."""
    from r36s_studio.imaging.mbr import PARTITION_ENTRY_SIZE, PARTITION_TABLE_OFFSET

    plan = plan_full_disk_partition(total_sectors=200_000)

    sector = build_full_disk_mbr_sector(plan)

    assert sector[:PARTITION_TABLE_OFFSET] == b"\x00" * PARTITION_TABLE_OFFSET  # code de démarrage
    for slot in range(1, 4):
        offset = PARTITION_TABLE_OFFSET + slot * PARTITION_ENTRY_SIZE
        assert sector[offset : offset + PARTITION_ENTRY_SIZE] == b"\x00" * PARTITION_ENTRY_SIZE


# --- étape 1/4 : effacement ---------------------------------------------------


@patch("r36s_studio.imaging.reset_card.prepared_write_target", side_effect=_no_prep)
def test_erase_partition_table_zeroes_leading_and_trailing_edges(mock_prep, tmp_path):
    total_sectors = 200_000
    dirty = bytearray(SECTOR_SIZE)
    dirty[446] = 0x0E  # entrée MBR d'origine, doit disparaître
    dirty[510:512] = b"\x55\xaa"
    path = _make_fake_device_file(tmp_path, "fake_card.img", total_sectors, bytes(dirty))
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    erase_partition_table(device)

    with open(path, "rb") as f:
        assert f.read(SECTOR_SIZE) == b"\x00" * SECTOR_SIZE  # plus de signature de démarrage ni d'entrée
        f.seek((total_sectors - ALIGNMENT_SECTORS) * SECTOR_SIZE)
        assert f.read(SECTOR_SIZE) == b"\x00" * SECTOR_SIZE


@patch("r36s_studio.imaging.reset_card.prepared_write_target", side_effect=_no_prep)
def test_erase_partition_table_erases_a_gpt_signature(mock_prep, tmp_path):
    """Une signature GPT ("EFI PART") en LBA1 ne doit plus être présente
    après l'effacement -- sans quoi un outil qui la retrouverait malgré un
    MBR neuf écrit ensuite en LBA0 continuerait de rapporter l'ancien
    schéma GPT."""
    total_sectors = 200_000
    path = tmp_path / "fake_gpt_card.img"
    with open(path, "wb") as f:
        f.write(b"\x00" * SECTOR_SIZE)
        f.write(b"EFI PART" + b"\x00" * (SECTOR_SIZE - 8))
        f.seek(total_sectors * SECTOR_SIZE - 1)
        f.write(b"\x00")
    device = _make_device(str(path), total_sectors * SECTOR_SIZE)

    erase_partition_table(device)

    with open(path, "rb") as f:
        f.seek(SECTOR_SIZE)
        assert f.read(8) != b"EFI PART"


# --- étape 2/4 : création ------------------------------------------------------


@patch("r36s_studio.imaging.reset_card.platform.system", return_value="Linux")
@patch("r36s_studio.imaging.reset_card.prepared_write_target", side_effect=_no_prep)
def test_create_single_partition_writes_a_fresh_mbr(mock_prep, mock_platform, tmp_path):
    total_sectors = 200_000
    path = _make_fake_device_file(tmp_path, "fake_card.img", total_sectors)
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    plan = create_single_partition(device)

    with open(path, "rb") as f:
        reparsed = parse_mbr(f.read(SECTOR_SIZE))
    assert len(reparsed) == 1
    assert reparsed[0].partition_type == MBR_NTFS_EXFAT_PARTITION_TYPE
    assert reparsed[0].start_lba == ALIGNMENT_SECTORS
    assert plan.start_lba == ALIGNMENT_SECTORS


@patch("r36s_studio.imaging.reset_card.time.sleep")
@patch("r36s_studio.imaging.reset_card.platform.system", return_value="Windows")
@patch("r36s_studio.imaging.reset_card.prepared_write_target", side_effect=_no_prep)
def test_create_single_partition_waits_after_writing_on_windows_only(
    mock_prep, mock_platform, mock_sleep, tmp_path
):
    """Bug corrigé, confirmé sur du vrai matériel : le formatage échouait
    silencieusement car Windows n'avait pas encore repris en compte la
    nouvelle table -- ce délai laisse le temps à `IOCTL_DISK_UPDATE_
    PROPERTIES` (déjà déclenché par `prepared_write_target` en quittant
    son bloc `with`) de produire son effet avant l'étape suivante."""
    total_sectors = 200_000
    path = _make_fake_device_file(tmp_path, "fake_card.img", total_sectors)
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    create_single_partition(device)

    mock_sleep.assert_called_once()


@patch("r36s_studio.imaging.reset_card.time.sleep")
@patch("r36s_studio.imaging.reset_card.platform.system", return_value="Darwin")
@patch("r36s_studio.imaging.reset_card.prepared_write_target", side_effect=_no_prep)
def test_create_single_partition_never_waits_outside_windows(mock_prep, mock_platform, mock_sleep, tmp_path):
    total_sectors = 200_000
    path = _make_fake_device_file(tmp_path, "fake_card.img", total_sectors)
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    create_single_partition(device)

    mock_sleep.assert_not_called()


def test_create_single_partition_uses_the_fat32_partition_type_when_requested(tmp_path):
    total_sectors = 200_000
    path = _make_fake_device_file(tmp_path, "fake_card.img", total_sectors)
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    with patch("r36s_studio.imaging.reset_card.prepared_write_target", side_effect=_no_prep), patch(
        "r36s_studio.imaging.reset_card.platform.system", return_value="Linux"
    ):
        create_single_partition(device, filesystem="fat32")

    with open(path, "rb") as f:
        reparsed = parse_mbr(f.read(SECTOR_SIZE))
    assert reparsed[0].partition_type == MBR_FAT32_LBA_PARTITION_TYPE


# --- étape 3/4 : formatage ------------------------------------------------------


def _make_plan() -> ResetCardPlan:
    return ResetCardPlan(start_lba=ALIGNMENT_SECTORS, end_lba=200_000 - 1 - ALIGNMENT_SECTORS)


@patch("r36s_studio.imaging.reset_card.format_games_partition")
@patch("r36s_studio.imaging.reset_card.platform.system", return_value="Darwin")
def test_format_reset_partition_delegates_to_native_formatter_outside_windows(mock_system, mock_format):
    device = _make_device("/dev/fake-disk-test-1", 200_000 * SECTOR_SIZE)
    plan = _make_plan()
    mock_format.return_value = None

    format_reset_partition(device, plan, "SDCARD", "fat32")

    mock_format.assert_called_once_with(device, "SDCARD", "fat32", known_partition_paths=set())


@patch("r36s_studio.imaging.reset_card.format_games_partition")
@patch("r36s_studio.imaging.reset_card.platform.system", return_value="Windows")
def test_format_reset_partition_uses_native_formatter_for_exfat_on_windows(mock_system, mock_format):
    """Seul le cas Windows+FAT32 contourne `Format-Volume` (§ docstring de
    module) -- exFAT n'a pas cette limite de 32 Go, rien à contourner."""
    device = _make_device("\\\\.\\PhysicalDrive9903", 200_000 * SECTOR_SIZE)
    plan = _make_plan()
    mock_format.return_value = "K"

    letter = format_reset_partition(device, plan, "SDCARD", "exfat")

    assert letter == "K"
    mock_format.assert_called_once_with(device, "SDCARD", "exfat", known_partition_paths=set())


@patch("r36s_studio.imaging.reset_card._windows_assign_drive_letter_after_raw_format")
@patch("r36s_studio.imaging.reset_card.format_fat32")
@patch("r36s_studio.imaging.reset_card.prepared_write_target", side_effect=_no_prep)
@patch("r36s_studio.imaging.reset_card.platform.system", return_value="Windows")
def test_format_reset_partition_writes_fat32_by_hand_on_windows(
    mock_system, mock_prep, mock_format_fat32, mock_assign_letter, tmp_path
):
    """Bug corrigé, signalé par un utilisateur (carte SF3000HD, 128 Go) :
    `Format-Volume` refuse le FAT32 au-delà de 32 Go -- contourné en
    écrivant nous-mêmes la structure (`imaging/fat32.py`), jamais via
    PowerShell pour ce cas précis (aucun appel à `Format-Volume`)."""
    path = _make_fake_device_file(tmp_path, "fake_card.img", 200_000)
    device = _make_device(path, 200_000 * SECTOR_SIZE)
    plan = _make_plan()
    mock_assign_letter.return_value = "K"

    letter = format_reset_partition(device, plan, "SDCARD", "fat32")

    assert letter == "K"
    mock_format_fat32.assert_called_once_with(path, plan.start_lba * SECTOR_SIZE, plan.size_bytes, "SDCARD")
    mock_assign_letter.assert_called_once_with(device.path)


# --- attribution de la lettre de lecteur (Windows, après formatage FAT32) ------


@patch("r36s_studio.imaging.reset_card.subprocess.run")
def test_windows_assign_drive_letter_never_calls_format_volume(mock_run):
    from r36s_studio.imaging.reset_card import _windows_assign_drive_letter_after_raw_format

    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "DRIVE_LETTER=K\n"

    letter = _windows_assign_drive_letter_after_raw_format("\\\\.\\PhysicalDrive9903")

    assert letter == "K"
    command = mock_run.call_args[0][0][-1]
    assert "Format-Volume" not in command
    assert "Add-PartitionAccessPath" in command
    assert "AssignDriveLetter" in command
    assert "9903" in command


@patch("r36s_studio.imaging.reset_card.subprocess.run")
def test_windows_assign_drive_letter_raises_when_powershell_fails(mock_run):
    from r36s_studio.imaging.reset_card import _windows_assign_drive_letter_after_raw_format

    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Aucune partition trouvee."
    mock_run.return_value.stdout = ""

    with pytest.raises(OSError):
        _windows_assign_drive_letter_after_raw_format("\\\\.\\PhysicalDrive9903")
