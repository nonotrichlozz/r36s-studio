"""Tests de la lecture de table de partitions MBR (imaging/mbr.py) — jeu de
données factice, aucune carte réelle."""

from __future__ import annotations

import struct

import pytest

from r36s_studio.imaging.mbr import last_used_byte, parse_mbr

SECTOR_SIZE = 512
PARTITION_TABLE_OFFSET = 446
PARTITION_ENTRY_SIZE = 16


def build_mbr_sector(partitions) -> bytes:
    """`partitions` : liste de tuples (type, start_lba, sector_count), 4
    au maximum."""
    sector = bytearray(SECTOR_SIZE)
    for i, (ptype, start_lba, count) in enumerate(partitions):
        offset = PARTITION_TABLE_OFFSET + i * PARTITION_ENTRY_SIZE
        entry = bytearray(PARTITION_ENTRY_SIZE)
        entry[4] = ptype
        entry[8:12] = struct.pack("<I", start_lba)
        entry[12:16] = struct.pack("<I", count)
        sector[offset : offset + PARTITION_ENTRY_SIZE] = entry
    sector[510:512] = b"\x55\xaa"
    return bytes(sector)


# Table à trois partitions inspirée d'une carte ArkOS : BOOT, root, EASYROMS.
ARKOS_LIKE_PARTITIONS = [
    (0x0E, 2048, 204800),        # BOOT (FAT16), depuis le secteur 2048
    (0x83, 206848, 4194304),     # root (Linux)
    (0x0B, 4401152, 6250000),    # EASYROMS (FAT32)
]


def test_parse_mbr_returns_all_nonempty_partitions():
    sector = build_mbr_sector(ARKOS_LIKE_PARTITIONS)
    partitions = parse_mbr(sector)

    assert len(partitions) == 3
    assert partitions[0].partition_type == 0x0E
    assert partitions[0].start_lba == 2048
    assert partitions[2].sector_count == 6250000


def test_parse_mbr_skips_empty_entries():
    sector = build_mbr_sector([(0x0E, 2048, 204800)])  # une seule partition
    partitions = parse_mbr(sector)
    assert len(partitions) == 1


def test_parse_mbr_rejects_missing_signature():
    sector = bytearray(SECTOR_SIZE)  # pas de 0x55AA
    with pytest.raises(ValueError):
        parse_mbr(bytes(sector))


def test_parse_mbr_rejects_short_input():
    with pytest.raises(ValueError):
        parse_mbr(b"\x00" * 100)


def test_last_used_byte_stops_at_end_of_last_partition_not_full_device():
    sector = build_mbr_sector(ARKOS_LIKE_PARTITIONS)
    last_type, last_start, last_count = ARKOS_LIKE_PARTITIONS[-1]
    expected_end = (last_start + last_count) * SECTOR_SIZE

    device_size = 128_000_000_000  # carte de 128 Go
    result = last_used_byte(sector, device_size_bytes=device_size)

    assert result == expected_end
    assert result < device_size  # la sauvegarde intelligente ne copie pas tout


def test_last_used_byte_falls_back_to_device_size_on_gpt_protective():
    sector = build_mbr_sector([(0xEE, 1, 0xFFFFFFFF)])  # MBR protecteur GPT
    assert last_used_byte(sector, device_size_bytes=64_000_000_000) == 64_000_000_000


def test_last_used_byte_falls_back_to_device_size_when_table_empty():
    sector = build_mbr_sector([])
    assert last_used_byte(sector, device_size_bytes=32_000_000_000) == 32_000_000_000


def test_last_used_byte_raises_without_fallback_size_when_unusable():
    sector = build_mbr_sector([])
    with pytest.raises(ValueError):
        last_used_byte(sector)
