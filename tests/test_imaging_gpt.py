"""Tests de la lecture/reconstruction de table de partitions GPT
(imaging/gpt.py) — jeu de données factice, aucune carte réelle.

Le point critique de ce module : une image GPT tronquée doit garder une
table de partitions cohérente (table secondaire reconstruite en fin de
fichier, CRC32 corrects) sinon un outil de flashage la rejette comme
corrompue plutôt que de simplement l'accepter avec une partition en moins."""

from __future__ import annotations

import zlib

import pytest

from r36s_studio.imaging.gpt import (
    GPT_ENTRY_SIZE,
    GPT_HEADER_SIZE,
    GPT_SIGNATURE,
    GptHeader,
    GptPartitionEntry,
    build_gpt_entries,
    build_gpt_header,
    parse_gpt_entries,
    parse_gpt_header,
)

SECTOR_SIZE = 512


def _guid(byte: int) -> bytes:
    """GUID factice, reconnaissable dans les assertions -- un octet répété
    16 fois, jamais une vraie valeur GUID interprétée par ce module (traité
    comme un blob opaque, voir la docstring du module)."""
    return bytes([byte]) * 16


def _entry(start_lba: int, end_lba: int, type_byte: int = 1, name: bytes = b"") -> GptPartitionEntry:
    return GptPartitionEntry(
        type_guid=_guid(type_byte),
        unique_guid=_guid(0xAA),
        start_lba=start_lba,
        end_lba=end_lba,
        attributes=0,
        name=name.ljust(72, b"\x00")[:72],
    )


def _build_reference_header_sector(
    *,
    my_lba=1,
    alternate_lba=1234,
    first_usable_lba=34,
    last_usable_lba=1000,
    disk_guid=_guid(0x42),
    partition_entry_lba=2,
    num_entries=128,
    entry_size=128,
    entries_bytes=None,
) -> bytes:
    """Construit un secteur d'en-tête GPT « à la main », indépendamment de
    `build_gpt_header`, pour tester `parse_gpt_header` sans dépendre du
    code qu'il est censé vérifier."""
    if entries_bytes is None:
        entries_bytes = b"\x00" * (num_entries * entry_size)
    entry_array_crc32 = zlib.crc32(entries_bytes) & 0xFFFFFFFF

    header = bytearray(GPT_HEADER_SIZE)
    header[0:8] = GPT_SIGNATURE
    header[8:12] = b"\x00\x00\x01\x00"  # revision 1.0
    header[12:16] = GPT_HEADER_SIZE.to_bytes(4, "little")
    header[16:20] = b"\x00\x00\x00\x00"
    header[20:24] = b"\x00\x00\x00\x00"
    header[24:32] = my_lba.to_bytes(8, "little")
    header[32:40] = alternate_lba.to_bytes(8, "little")
    header[40:48] = first_usable_lba.to_bytes(8, "little")
    header[48:56] = last_usable_lba.to_bytes(8, "little")
    header[56:72] = disk_guid
    header[72:80] = partition_entry_lba.to_bytes(8, "little")
    header[80:84] = num_entries.to_bytes(4, "little")
    header[84:88] = entry_size.to_bytes(4, "little")
    header[88:92] = entry_array_crc32.to_bytes(4, "little")
    header_crc32 = zlib.crc32(bytes(header)) & 0xFFFFFFFF
    header[16:20] = header_crc32.to_bytes(4, "little")
    return bytes(header).ljust(SECTOR_SIZE, b"\x00")


# --- parse_gpt_header --------------------------------------------------


def test_parse_gpt_header_reads_all_fields():
    sector = _build_reference_header_sector(
        my_lba=1, alternate_lba=999999, first_usable_lba=34, last_usable_lba=999966, partition_entry_lba=2
    )

    header = parse_gpt_header(sector)

    assert header.my_lba == 1
    assert header.alternate_lba == 999999
    assert header.first_usable_lba == 34
    assert header.last_usable_lba == 999966
    assert header.partition_entry_lba == 2
    assert header.num_entries == 128
    assert header.entry_size == 128
    assert header.disk_guid == _guid(0x42)


def test_parse_gpt_header_rejects_missing_signature():
    sector = bytearray(SECTOR_SIZE)
    with pytest.raises(ValueError):
        parse_gpt_header(bytes(sector))


def test_parse_gpt_header_rejects_short_input():
    with pytest.raises(ValueError):
        parse_gpt_header(b"\x00" * 100)


# --- parse_gpt_entries ---------------------------------------------------


def test_parse_gpt_entries_returns_only_used_slots():
    header = parse_gpt_header(_build_reference_header_sector(num_entries=4, entry_size=GPT_ENTRY_SIZE))
    used = _entry(2048, 206847, type_byte=1, name="BOOT".encode("utf-16-le"))
    data = build_gpt_entries([used], num_entries=4, entry_size=GPT_ENTRY_SIZE)

    entries = parse_gpt_entries(data, header)

    assert len(entries) == 1
    assert entries[0].start_lba == 2048
    assert entries[0].end_lba == 206847


def test_parse_gpt_entries_empty_table_returns_no_entries():
    header = parse_gpt_header(_build_reference_header_sector(num_entries=4, entry_size=GPT_ENTRY_SIZE))
    data = build_gpt_entries([], num_entries=4, entry_size=GPT_ENTRY_SIZE)

    assert parse_gpt_entries(data, header) == []


# --- build_gpt_entries / build_gpt_header : round-trip -------------------


def test_build_gpt_entries_round_trips_through_parse():
    entries = [
        _entry(2048, 206847, type_byte=1, name="BOOT".encode("utf-16-le")),
        _entry(206848, 4401151, type_byte=2, name="root".encode("utf-16-le")),
    ]
    data = build_gpt_entries(entries, num_entries=128, entry_size=GPT_ENTRY_SIZE)
    header = parse_gpt_header(
        _build_reference_header_sector(num_entries=128, entry_size=GPT_ENTRY_SIZE, entries_bytes=data)
    )

    parsed = parse_gpt_entries(data, header)

    assert [(e.start_lba, e.end_lba) for e in parsed] == [(2048, 206847), (206848, 4401151)]
    assert parsed[0].type_guid == _guid(1)
    assert parsed[1].type_guid == _guid(2)


def test_build_gpt_entries_pads_unused_slots_with_zeros():
    data = build_gpt_entries([_entry(1, 2)], num_entries=4, entry_size=GPT_ENTRY_SIZE)

    assert len(data) == 4 * GPT_ENTRY_SIZE
    assert data[GPT_ENTRY_SIZE : 4 * GPT_ENTRY_SIZE] == b"\x00" * (3 * GPT_ENTRY_SIZE)


def test_build_gpt_entries_rejects_too_many_entries():
    entries = [_entry(i, i + 1) for i in range(5)]
    with pytest.raises(ValueError):
        build_gpt_entries(entries, num_entries=4, entry_size=GPT_ENTRY_SIZE)


def test_build_gpt_header_round_trips_through_parse():
    entries_bytes = build_gpt_entries([_entry(2048, 206847)], num_entries=128, entry_size=GPT_ENTRY_SIZE)

    sector = build_gpt_header(
        revision=b"\x00\x00\x01\x00",
        my_lba=1,
        alternate_lba=12345,
        first_usable_lba=34,
        last_usable_lba=12311,
        disk_guid=_guid(0x99),
        partition_entry_lba=2,
        num_entries=128,
        entry_size=GPT_ENTRY_SIZE,
        entries_bytes=entries_bytes,
    )

    header = parse_gpt_header(sector)

    assert header.my_lba == 1
    assert header.alternate_lba == 12345
    assert header.first_usable_lba == 34
    assert header.last_usable_lba == 12311
    assert header.disk_guid == _guid(0x99)
    assert header.partition_entry_lba == 2


def test_build_gpt_header_is_512_bytes_and_starts_with_signature():
    sector = build_gpt_header(
        revision=b"\x00\x00\x01\x00",
        my_lba=1,
        alternate_lba=2,
        first_usable_lba=34,
        last_usable_lba=100,
        disk_guid=_guid(1),
        partition_entry_lba=2,
        num_entries=128,
        entry_size=GPT_ENTRY_SIZE,
        entries_bytes=b"\x00" * (128 * GPT_ENTRY_SIZE),
    )

    assert len(sector) == SECTOR_SIZE
    assert sector[0:8] == GPT_SIGNATURE


def test_build_gpt_header_produces_a_correct_header_crc32():
    """Vérifié indépendamment de `parse_gpt_header` (qui ne relit même pas
    le CRC32) -- recalcule le CRC32 attendu à la main, comme le ferait un
    vrai lecteur GPT qui, lui, vérifie ce champ."""
    entries_bytes = b"\x00" * (128 * GPT_ENTRY_SIZE)
    sector = build_gpt_header(
        revision=b"\x00\x00\x01\x00",
        my_lba=1,
        alternate_lba=2,
        first_usable_lba=34,
        last_usable_lba=100,
        disk_guid=_guid(1),
        partition_entry_lba=2,
        num_entries=128,
        entry_size=GPT_ENTRY_SIZE,
        entries_bytes=entries_bytes,
    )

    header_bytes = bytearray(sector[0:GPT_HEADER_SIZE])
    stored_crc32 = int.from_bytes(header_bytes[16:20], "little")
    header_bytes[16:20] = b"\x00\x00\x00\x00"
    recomputed_crc32 = zlib.crc32(bytes(header_bytes)) & 0xFFFFFFFF

    assert stored_crc32 == recomputed_crc32


def test_build_gpt_header_produces_a_correct_entry_array_crc32():
    entries_bytes = build_gpt_entries([_entry(2048, 206847)], num_entries=128, entry_size=GPT_ENTRY_SIZE)
    sector = build_gpt_header(
        revision=b"\x00\x00\x01\x00",
        my_lba=1,
        alternate_lba=2,
        first_usable_lba=34,
        last_usable_lba=100,
        disk_guid=_guid(1),
        partition_entry_lba=2,
        num_entries=128,
        entry_size=GPT_ENTRY_SIZE,
        entries_bytes=entries_bytes,
    )

    stored_crc32 = int.from_bytes(sector[88:92], "little")
    assert stored_crc32 == (zlib.crc32(entries_bytes) & 0xFFFFFFFF)


def test_build_gpt_header_pads_beyond_header_size_with_zeros():
    sector = build_gpt_header(
        revision=b"\x00\x00\x01\x00",
        my_lba=1,
        alternate_lba=2,
        first_usable_lba=34,
        last_usable_lba=100,
        disk_guid=_guid(1),
        partition_entry_lba=2,
        num_entries=128,
        entry_size=GPT_ENTRY_SIZE,
        entries_bytes=b"\x00" * (128 * GPT_ENTRY_SIZE),
    )

    assert sector[GPT_HEADER_SIZE:] == b"\x00" * (SECTOR_SIZE - GPT_HEADER_SIZE)
