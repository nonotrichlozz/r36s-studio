"""Tests de la recréation de la partition de jeux après restauration d'une
sauvegarde « système sans les jeux » (imaging/games_partition.py) --
jeux de données factices (MBR et GPT), aucune carte réelle. Même style que
`test_imaging_system_backup.py` : la table primaire/secondaire produite est
reparsée indépendamment pour vérifier sa cohérence structurelle, pas
seulement que le code ne lève pas."""

from __future__ import annotations

import contextlib
import os
import struct
import zlib
from unittest.mock import patch

import pytest

from r36s_studio.devices import Device
from r36s_studio.imaging.gpt import (
    GPT_ENTRY_SIZE,
    GptPartitionEntry,
    build_gpt_entries,
    build_gpt_header,
    parse_gpt_entries,
    parse_gpt_header,
)
from r36s_studio.imaging.mbr import PARTITION_TABLE_OFFSET, MbrPartition, parse_mbr
from r36s_studio.imaging.games_partition import (
    ALIGNMENT_SECTORS,
    GAMES_PARTITION_LABEL,
    MICROSOFT_BASIC_DATA_TYPE_GUID,
    GamesPartitionNotFoundAfterCreation,
    NoFreeMbrSlot,
    NoFreeSpaceForGamesPartition,
    create_and_format_games_partition,
    create_games_partition,
    format_games_partition,
    plan_games_partition_gpt,
    plan_games_partition_mbr,
    rewrite_gpt_with_games_partition,
    rewrite_mbr_with_games_partition,
)
from r36s_studio.partitions.locate import PartitionInfo

from .sparse_file import create_sparse_file

SECTOR_SIZE = 512


@contextlib.contextmanager
def _no_prep(device):
    yield device.path


def _make_device(path: str, size_bytes: int) -> Device:
    return Device(
        path=path, display="Carte SD factice", size_bytes=size_bytes, removable=True, bus="USB",
        is_system=False, mountpoints=[],
    )


# --- planification MBR ------------------------------------------------------


def test_plan_games_partition_mbr_starts_aligned_after_last_partition():
    partitions = [
        MbrPartition(0, 0x0E, 2048, 2048),  # BOOT : 2048..4095
        MbrPartition(1, 0x83, 4096, 2048),  # root : 4096..6143
    ]
    plan = plan_games_partition_mbr(partitions, total_sectors=200_000)

    assert plan.start_lba % ALIGNMENT_SECTORS == 0
    assert plan.start_lba >= 6144
    assert plan.end_lba == 199_999
    assert plan.mbr_slot_index == 2  # premier créneau libre


def test_plan_games_partition_mbr_raises_when_no_space_left():
    partitions = [MbrPartition(0, 0x0E, 2048, 2048), MbrPartition(1, 0x83, 4096, 2048)]
    with pytest.raises(NoFreeSpaceForGamesPartition):
        plan_games_partition_mbr(partitions, total_sectors=6144)


def test_plan_games_partition_mbr_raises_when_remaining_space_too_small():
    partitions = [MbrPartition(0, 0x0E, 2048, 2048), MbrPartition(1, 0x83, 4096, 2048)]
    # Juste un peu d'espace, bien en dessous de MIN_GAMES_PARTITION_BYTES (64 Mio).
    with pytest.raises(NoFreeSpaceForGamesPartition):
        plan_games_partition_mbr(partitions, total_sectors=6144 + 100)


def test_plan_games_partition_mbr_raises_when_all_slots_used():
    partitions = [
        MbrPartition(0, 0x0E, 2048, 2048),
        MbrPartition(1, 0x83, 4096, 2048),
        MbrPartition(2, 0x0B, 6144, 2048),
        MbrPartition(3, 0x07, 8192, 2048),
    ]
    with pytest.raises(NoFreeMbrSlot):
        plan_games_partition_mbr(partitions, total_sectors=200_000)


# --- planification GPT ------------------------------------------------------


def _fake_gpt_header(last_usable_lba=233, alternate_lba=333):
    return parse_gpt_header(
        build_gpt_header(
            revision=b"\x00\x00\x01\x00",
            my_lba=1,
            alternate_lba=alternate_lba,
            first_usable_lba=34,
            last_usable_lba=last_usable_lba,
            disk_guid=b"\x99" * 16,
            partition_entry_lba=2,
            num_entries=128,
            entry_size=GPT_ENTRY_SIZE,
            entries_bytes=b"",
        )
    )


def _gpt_entry(bounds, name):
    start, end = bounds
    return GptPartitionEntry(
        type_guid=b"\x01" * 16, unique_guid=b"\xaa" * 16, start_lba=start, end_lba=end,
        attributes=0, name=name.encode("utf-16-le"),
    )


def test_plan_games_partition_gpt_starts_aligned_and_reserves_secondary_table():
    header = _fake_gpt_header()
    entries = [_gpt_entry((34, 133), "BOOT"), _gpt_entry((134, 233), "root")]

    plan = plan_games_partition_gpt(header, entries, total_sectors=1_000_000)

    assert plan.start_lba % ALIGNMENT_SECTORS == 0
    assert plan.start_lba >= 234
    # 128 entrées * 128 octets = 16 384 octets = 32 secteurs, + 1 secteur d'en-tête.
    assert plan.end_lba == 1_000_000 - 1 - 33


def test_plan_games_partition_gpt_raises_when_no_space_left():
    header = _fake_gpt_header()
    entries = [_gpt_entry((34, 133), "BOOT"), _gpt_entry((134, 233), "root")]
    with pytest.raises(NoFreeSpaceForGamesPartition):
        plan_games_partition_gpt(header, entries, total_sectors=300)


# --- réécriture MBR ----------------------------------------------------------


def test_rewrite_mbr_with_games_partition_adds_entry_in_free_slot():
    first_sector = bytearray(SECTOR_SIZE)
    for i, (ptype, start, count) in enumerate([(0x0E, 2048, 2048), (0x83, 4096, 2048)]):
        offset = PARTITION_TABLE_OFFSET + i * 16
        first_sector[offset + 4] = ptype
        first_sector[offset + 8 : offset + 12] = struct.pack("<I", start)
        first_sector[offset + 12 : offset + 16] = struct.pack("<I", count)
    first_sector[510:512] = b"\x55\xaa"

    partitions = parse_mbr(bytes(first_sector))
    plan = plan_games_partition_mbr(partitions, total_sectors=200_000)

    new_sector = rewrite_mbr_with_games_partition(bytes(first_sector), plan)
    reparsed = parse_mbr(new_sector)

    assert len(reparsed) == 3
    new_entry = reparsed[2]
    assert new_entry.start_lba == plan.start_lba
    assert new_entry.sector_count == plan.end_lba - plan.start_lba + 1
    # Les deux premières entrées ne doivent pas avoir bougé.
    assert reparsed[0].start_lba == 2048 and reparsed[0].sector_count == 2048
    assert reparsed[1].start_lba == 4096 and reparsed[1].sector_count == 2048


# --- réécriture GPT, vérification structurelle indépendante -----------------


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def test_rewrite_gpt_with_games_partition_produces_consistent_tables():
    boot = (34, 133)
    root = (134, 233)
    total_sectors = 1_000_000
    entries = [_gpt_entry(boot, "BOOT"), _gpt_entry(root, "root")]
    entries_bytes = build_gpt_entries(entries, num_entries=128, entry_size=GPT_ENTRY_SIZE)
    header_sector = build_gpt_header(
        revision=b"\x00\x00\x01\x00", my_lba=1, alternate_lba=333, first_usable_lba=34,
        last_usable_lba=233, disk_guid=b"\x99" * 16, partition_entry_lba=2, num_entries=128,
        entry_size=GPT_ENTRY_SIZE, entries_bytes=entries_bytes,
    )
    header = parse_gpt_header(header_sector)

    first_sector = bytearray(SECTOR_SIZE)
    first_sector[PARTITION_TABLE_OFFSET + 4] = 0xEE
    first_sector[PARTITION_TABLE_OFFSET + 8 : PARTITION_TABLE_OFFSET + 12] = struct.pack("<I", 1)
    first_sector[PARTITION_TABLE_OFFSET + 12 : PARTITION_TABLE_OFFSET + 16] = struct.pack(
        "<I", 333
    )  # taille de la petite image système d'origine, pas celle du disque de destination
    first_sector[510:512] = b"\x55\xaa"

    plan = plan_games_partition_gpt(header, entries, total_sectors)
    rewritten = rewrite_gpt_with_games_partition(bytes(first_sector), header, entries, plan, total_sectors)

    # MBR protecteur mis à jour pour refléter la taille réelle du disque de
    # destination (plus grand que l'image système restaurée), pas celle de
    # l'image d'origine.
    reparsed_mbr = parse_mbr(rewritten.protective_mbr_sector)
    assert len(reparsed_mbr) == 1
    assert reparsed_mbr[0].sector_count == total_sectors - 1

    # En-tête primaire : reparsé indépendamment, CRC32 valides.
    primary_header = parse_gpt_header(rewritten.primary_header)
    assert primary_header.alternate_lba == rewritten.secondary_header_lba
    assert primary_header.last_usable_lba == plan.end_lba
    header_for_crc = bytearray(rewritten.primary_header[:92])
    header_for_crc[16:20] = b"\x00\x00\x00\x00"
    assert _crc32(bytes(header_for_crc)) == int.from_bytes(rewritten.primary_header[16:20], "little")
    assert _crc32(rewritten.primary_entries) == primary_header.entry_array_crc32

    # En-tête secondaire, à la toute fin du disque de destination.
    assert rewritten.secondary_header_lba == total_sectors - 1
    secondary_header = parse_gpt_header(rewritten.secondary_header)
    assert secondary_header.my_lba == total_sectors - 1
    assert secondary_header.alternate_lba == 1
    assert secondary_header.last_usable_lba == plan.end_lba
    assert _crc32(rewritten.secondary_entries) == secondary_header.entry_array_crc32

    # Les deux tables (primaire et secondaire) contiennent les mêmes
    # entrées : BOOT, root, inchangées, plus la nouvelle partition de jeux.
    for entries_bytes_to_check in (rewritten.primary_entries, rewritten.secondary_entries):
        reparsed_entries = parse_gpt_entries(entries_bytes_to_check, header)
        assert len(reparsed_entries) == 3
        assert (reparsed_entries[0].start_lba, reparsed_entries[0].end_lba) == boot
        assert (reparsed_entries[1].start_lba, reparsed_entries[1].end_lba) == root
        new_entry = reparsed_entries[2]
        assert new_entry.start_lba == plan.start_lba
        assert new_entry.end_lba == plan.end_lba
        assert new_entry.type_guid == __import__("uuid").UUID(MICROSOFT_BASIC_DATA_TYPE_GUID).bytes_le
        name = new_entry.name.decode("utf-16-le").rstrip("\x00")
        assert name == GAMES_PARTITION_LABEL

    # Aucun chevauchement entre la nouvelle partition et la table secondaire.
    assert plan.end_lba < rewritten.secondary_entries_lba


# --- orchestration bout en bout, MBR ----------------------------------------


def _make_fake_mbr_device_file(tmp_path, *, boot=(2048, 4095), root=(4096, 6143), total_sectors=200_000):
    first_sector = bytearray(SECTOR_SIZE)
    for i, (ptype, (start, end)) in enumerate([(0x0E, boot), (0x83, root)]):
        offset = PARTITION_TABLE_OFFSET + i * 16
        first_sector[offset + 4] = ptype
        first_sector[offset + 8 : offset + 12] = struct.pack("<I", start)
        first_sector[offset + 12 : offset + 16] = struct.pack("<I", end - start + 1)
    first_sector[510:512] = b"\x55\xaa"

    path = tmp_path / "fake_target_mbr.img"
    create_sparse_file(path, total_sectors * SECTOR_SIZE, bytes(first_sector))
    return str(path), total_sectors


@patch("r36s_studio.imaging.games_partition.prepared_write_target", side_effect=_no_prep)
def test_create_games_partition_mbr_writes_new_entry_to_device(mock_prep, tmp_path):
    path, total_sectors = _make_fake_mbr_device_file(tmp_path)
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    result = create_games_partition(device)

    assert result.is_gpt is False
    with open(path, "rb") as f:
        reparsed = parse_mbr(f.read(SECTOR_SIZE))
    assert len(reparsed) == 3
    new_entry = reparsed[2]
    assert new_entry.start_lba * SECTOR_SIZE == result.start_bytes
    assert new_entry.sector_count * SECTOR_SIZE == result.size_bytes
    assert new_entry.start_lba % ALIGNMENT_SECTORS == 0
    assert new_entry.start_lba + new_entry.sector_count == total_sectors


# --- formatage natif, par OS -------------------------------------------------


@patch("r36s_studio.imaging.games_partition.subprocess.run")
@patch("r36s_studio.imaging.games_partition.list_partitions")
@patch("r36s_studio.imaging.games_partition.platform.system", return_value="Darwin")
def test_format_games_partition_macos_erases_new_partition_as_exfat(mock_system, mock_list, mock_run):
    mock_list.return_value = [
        PartitionInfo("/dev/fake-disk-test-1s1", "BOOT", "msdos", None),
        PartitionInfo("/dev/fake-disk-test-1s2", GAMES_PARTITION_LABEL, "", None),
    ]
    device = _make_device("/dev/fake-disk-test-1", 1_000_000)

    format_games_partition(device, known_partition_paths={"/dev/fake-disk-test-1s1"})

    # Deux appels : le formatage, puis un montage best-effort (§4.3 bis --
    # « à vérifier plutôt qu'à supposer » que diskutil laisse le volume
    # monté).
    assert mock_run.call_count == 2
    args = mock_run.call_args_list[0][0][0]
    assert args[:2] == ["diskutil", "eraseVolume"]
    assert args[2] == "ExFAT"
    assert args[3] == GAMES_PARTITION_LABEL
    assert args[4] == "/dev/fake-disk-test-1s2"
    mount_args = mock_run.call_args_list[1][0][0]
    assert mount_args == ["diskutil", "mount", "/dev/fake-disk-test-1s2"]


@patch("r36s_studio.imaging.games_partition.subprocess.run")
@patch("r36s_studio.imaging.games_partition.list_partitions")
@patch("r36s_studio.imaging.games_partition.platform.system", return_value="Linux")
def test_format_games_partition_linux_uses_mkfs_exfat(mock_system, mock_list, mock_run):
    mock_list.return_value = [PartitionInfo("/dev/fake-loop-test-1p2", GAMES_PARTITION_LABEL, "", None)]
    device = _make_device("/dev/fake-loop-test-1", 1_000_000)

    format_games_partition(device, known_partition_paths=set())

    # Deux appels : le formatage, puis un montage best-effort (§4.3 bis --
    # mkfs.exfat/mkfs.vfat ne montent jamais eux-mêmes, contrairement à
    # `diskutil eraseVolume` sur macOS).
    assert mock_run.call_count == 2
    args = mock_run.call_args_list[0][0][0]
    assert args[0] == "mkfs.exfat"
    assert "/dev/fake-loop-test-1p2" in args
    mount_args = mock_run.call_args_list[1][0][0]
    assert mount_args == ["udisksctl", "mount", "-b", "/dev/fake-loop-test-1p2"]


@patch("r36s_studio.imaging.games_partition.subprocess.run")
@patch("r36s_studio.imaging.games_partition.list_partitions")
@patch("r36s_studio.imaging.games_partition.platform.system", return_value="Windows")
def test_format_games_partition_windows_uses_powershell_format_volume(mock_system, mock_list, mock_run):
    device = _make_device("\\\\.\\PhysicalDrive9903", 1_000_000)
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "DRIVE_LETTER=K\n"

    letter = format_games_partition(device)

    assert letter == "K"

    mock_list.assert_not_called()  # retrouvée par position (dernière partition), pas via list_partitions
    args = mock_run.call_args[0][0]
    assert args[0] == "powershell"
    command = args[-1]
    assert "PhysicalDrive9903" not in command  # seul le numéro de disque est utilisé
    assert "9903" in command
    assert "Format-Volume" in command
    assert "exFAT" in command
    assert GAMES_PARTITION_LABEL in command
    assert "Get-Partition" in command
    # Réessaie plusieurs fois avant d'abandonner -- Windows peut ne pas
    # avoir encore repris en compte une table de partitions tout juste
    # écrite (bug corrigé, confirmé sur du vrai matériel -- « Remettre la
    # carte à zéro », §4.3 bis).
    assert "for (" in command
    # Bug corrigé, confirmé sur du vrai matériel : `Get-Volume` montrait
    # déjà un volume exFAT correctement formaté, mais sans lettre de
    # lecteur il n'apparaissait pas dans l'Explorateur.
    assert "Add-PartitionAccessPath" in command
    assert "AssignDriveLetter" in command


@patch("r36s_studio.imaging.games_partition.subprocess.run")
@patch("r36s_studio.imaging.games_partition.list_partitions")
@patch("r36s_studio.imaging.games_partition.platform.system", return_value="Windows")
def test_format_games_partition_windows_returns_none_when_no_letter_could_be_assigned(
    mock_system, mock_list, mock_run
):
    """Rare (les 26 lettres déjà toutes utilisées) -- ne doit jamais faire
    planter le formatage, qui a par ailleurs réussi : `None` plutôt qu'une
    levée, à l'appelant de décider s'il journalise ce cas."""
    device = _make_device("\\\\.\\PhysicalDrive9903", 1_000_000)
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = ""

    letter = format_games_partition(device)

    assert letter is None


@patch("r36s_studio.imaging.games_partition.subprocess.run")
@patch("r36s_studio.imaging.games_partition.list_partitions")
@patch("r36s_studio.imaging.games_partition.platform.system", return_value="Windows")
def test_format_games_partition_windows_raises_when_powershell_exits_non_zero(mock_system, mock_list, mock_run):
    """Bug corrigé, confirmé sur du vrai matériel : un pipeline PowerShell
    dont `Get-Partition` ne renvoie rien ne lève auparavant *aucune*
    erreur (rien à formater, mais rien qui échoue non plus) -- `subprocess
    .run(check=True)` voyait un code de sortie 0 malgré tout, et l'appelant
    croyait le formatage réussi alors qu'aucune partition exFAT n'avait
    été créée. Un code de sortie non nul doit désormais toujours lever,
    avec le détail (stderr) inclus dans le message."""
    device = _make_device("\\\\.\\PhysicalDrive9903", 1_000_000)
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Aucune partition trouvee sur le disque 9903."
    mock_run.return_value.stdout = ""

    with pytest.raises(OSError, match="Aucune partition trouvee"):
        format_games_partition(device)


@patch("r36s_studio.imaging.games_partition.list_partitions")
def test_wait_for_new_partition_raises_when_it_never_appears(mock_list):
    from r36s_studio.imaging.games_partition import _wait_for_new_partition

    mock_list.return_value = [PartitionInfo("/dev/fake-loop-test-2p1", "root", "ext4", None)]

    with pytest.raises(GamesPartitionNotFoundAfterCreation):
        _wait_for_new_partition(
            "/dev/fake-loop-test-2", {"/dev/fake-loop-test-2p1"}, timeout=0, poll_interval=0
        )


# --- orchestration combinée --------------------------------------------------


@patch("r36s_studio.imaging.games_partition.format_games_partition")
@patch("r36s_studio.imaging.games_partition.create_games_partition")
@patch("r36s_studio.imaging.games_partition.list_partitions")
def test_create_and_format_games_partition_passes_known_paths_before_creation(mock_list, mock_create, mock_format):
    from r36s_studio.imaging.games_partition import GamesPartitionResult

    mock_list.return_value = [PartitionInfo("/dev/fake-loop-test-3p1", "root", "ext4", None)]
    mock_create.return_value = GamesPartitionResult(start_bytes=0, size_bytes=0, is_gpt=False)
    device = _make_device("/dev/fake-loop-test-3", 1_000_000)

    create_and_format_games_partition(device)

    mock_create.assert_called_once()
    mock_format.assert_called_once()
    _, kwargs = mock_format.call_args
    assert kwargs["known_partition_paths"] == {"/dev/fake-loop-test-3p1"}


# --- décision automatique post-écriture (§4.3) ------------------------------
# Retire la case à cocher/comparaison de chemin côté GUI (retour d'usage réel :
# l'utilisateur ne peut pas savoir à l'avance si une image laissera de
# l'espace libre) -- l'app décide seule, après l'écriture, à partir de la
# taille réelle de la carte.


def test_peek_free_games_partition_bytes_reads_without_locking_or_writing(tmp_path):
    """N'utilise jamais `prepared_write_target` (contrairement à
    `create_games_partition`) -- une lecture directe du chemin du
    périphérique suffit, sans le moindre patch de verrouillage."""
    from r36s_studio.imaging.games_partition import _peek_free_games_partition_bytes

    path, total_sectors = _make_fake_mbr_device_file(tmp_path)
    before = open(path, "rb").read()
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    free_bytes = _peek_free_games_partition_bytes(device)

    # Espace entre la fin de root (6143) et la fin du disque (199 999),
    # aligné -- techniquement viable (> MIN_GAMES_PARTITION_BYTES) mais
    # bien en dessous du seuil "ça vaut la peine" (1 Go).
    assert 0 < free_bytes < 1024 * 1024 * 1024
    assert open(path, "rb").read() == before  # rien écrit par la simple lecture


def test_peek_free_games_partition_bytes_returns_zero_when_device_unreadable():
    from r36s_studio.imaging.games_partition import _peek_free_games_partition_bytes

    device = _make_device("/dev/fake-disk-test-does-not-exist", 32_000_000_000)

    assert _peek_free_games_partition_bytes(device) == 0


def test_peek_free_games_partition_bytes_returns_zero_when_no_space_left(tmp_path):
    from r36s_studio.imaging.games_partition import _peek_free_games_partition_bytes

    # Disque qui s'arrête exactement à la fin de root -- aucun espace
    # libre, `plan_games_partition_mbr` lève `NoFreeSpaceForGamesPartition`
    # en interne.
    path, total_sectors = _make_fake_mbr_device_file(tmp_path, total_sectors=6144)
    device = _make_device(path, total_sectors * SECTOR_SIZE)

    assert _peek_free_games_partition_bytes(device) == 0


@patch("r36s_studio.imaging.games_partition.create_and_format_games_partition")
@patch("r36s_studio.imaging.games_partition._peek_free_games_partition_bytes")
def test_create_and_format_games_partition_if_worthwhile_skips_below_threshold(mock_peek, mock_create):
    from r36s_studio.imaging.games_partition import (
        GAMES_PARTITION_WORTHWHILE_BYTES,
        create_and_format_games_partition_if_worthwhile,
    )

    mock_peek.return_value = GAMES_PARTITION_WORTHWHILE_BYTES - 1
    device = _make_device("/dev/fake-disk-test-3", 32_000_000_000)

    result = create_and_format_games_partition_if_worthwhile(device)

    assert result is None
    mock_create.assert_not_called()  # jamais de verrouillage/écriture pour rien


@patch("r36s_studio.imaging.games_partition.create_and_format_games_partition")
@patch("r36s_studio.imaging.games_partition._peek_free_games_partition_bytes")
def test_create_and_format_games_partition_if_worthwhile_creates_above_threshold(mock_peek, mock_create):
    from r36s_studio.imaging.games_partition import (
        GAMES_PARTITION_WORTHWHILE_BYTES,
        GamesPartitionResult,
        create_and_format_games_partition_if_worthwhile,
    )

    mock_peek.return_value = GAMES_PARTITION_WORTHWHILE_BYTES
    mock_create.return_value = GamesPartitionResult(start_bytes=0, size_bytes=GAMES_PARTITION_WORTHWHILE_BYTES, is_gpt=True)
    device = _make_device("/dev/fake-disk-test-3", 32_000_000_000)

    result = create_and_format_games_partition_if_worthwhile(device)

    assert result is mock_create.return_value
    mock_create.assert_called_once_with(device, GAMES_PARTITION_LABEL, "exfat")


@patch(
    "r36s_studio.imaging.games_partition.create_and_format_games_partition",
    side_effect=NoFreeSpaceForGamesPartition("l'espace a changé entre-temps"),
)
@patch("r36s_studio.imaging.games_partition._peek_free_games_partition_bytes")
def test_create_and_format_games_partition_if_worthwhile_tolerates_race_with_real_attempt(
    mock_peek, mock_create
):
    """Rare : l'estimation en lecture seule jugeait l'espace suffisant,
    mais la tentative réelle (verrouillage + écriture) échoue quand même --
    ne doit jamais lever, seulement retourner `None` (§4.3 : « sinon ne
    rien faire », jamais un échec pour ce motif)."""
    from r36s_studio.imaging.games_partition import (
        GAMES_PARTITION_WORTHWHILE_BYTES,
        create_and_format_games_partition_if_worthwhile,
    )

    mock_peek.return_value = GAMES_PARTITION_WORTHWHILE_BYTES
    device = _make_device("/dev/fake-disk-test-3", 32_000_000_000)

    assert create_and_format_games_partition_if_worthwhile(device) is None
