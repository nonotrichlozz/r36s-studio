# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

"""Lecture et reconstruction de la table de partitions GPT (GUID Partition
Table) — utilisé par `imaging/system_backup.py` pour tronquer une image de
sauvegarde à la fin de la dernière partition système (avant la partition de
jeux) tout en gardant une table de partitions cohérente. Un outil de
flashage qui lit une image GPT tronquée sans corriger sa table secondaire
(qui pointerait alors au-delà de la fin réelle du fichier) la rejette
généralement comme corrompue plutôt que de simplement ignorer l'absence.

Format binaire (spec UEFI, Table 5.6) : en-tête 512 octets (LBA1, dont
seuls les 92 premiers sont significatifs), suivi du tableau d'entrées de
partitions (LBA2 par défaut, 128 entrées de 128 octets = 32 secteurs). Une
seconde copie identique (« table secondaire ») vit en toute fin de disque :
tableau d'entrées puis en-tête, dans cet ordre, l'en-tête primaire y
pointant (`AlternateLBA`). Les GUID (type et identifiant de partition) sont
traités comme des blobs opaques de 16 octets — jamais interprétés ni
reconstruits, seulement recopiés tels quels ; même chose pour le nom de
partition (72 octets UTF-16LE), jamais décodé.

CRC32 : l'algorithme demandé par la spec UEFI (Annex D, ISO/IEC 13239:2002)
est le CRC-32 IEEE 802.3 standard — le même que `zlib.crc32`/PNG, sans
inversion de bits ni table personnalisée à gérer."""

from __future__ import annotations

import zlib
from dataclasses import dataclass
from typing import List

SECTOR_SIZE = 512
GPT_SIGNATURE = b"EFI PART"
GPT_HEADER_SIZE = 92
GPT_DEFAULT_ENTRY_COUNT = 128
GPT_ENTRY_SIZE = 128
GPT_HEADER_LBA = 1
GPT_PARTITION_ENTRIES_LBA = 2  # emplacement standard de la table primaire


@dataclass
class GptHeader:
    revision: bytes
    my_lba: int
    alternate_lba: int
    first_usable_lba: int
    last_usable_lba: int
    disk_guid: bytes
    partition_entry_lba: int
    num_entries: int
    entry_size: int
    entry_array_crc32: int


@dataclass
class GptPartitionEntry:
    type_guid: bytes
    unique_guid: bytes
    start_lba: int
    end_lba: int  # inclusif
    attributes: int
    name: bytes  # 72 octets bruts, UTF-16LE avec remplissage nul


def parse_gpt_header(sector: bytes) -> GptHeader:
    """`sector` doit contenir les 512 octets de LBA1. Ne vérifie pas les
    CRC32 (lecture tolérante, comme `mbr.parse_mbr`) : seules les valeurs
    de champs comptent pour déterminer la disposition des partitions --
    reconstruire des CRC32 corrects est la responsabilité de `build_gpt_
    header` en écriture, pas une exigence à la lecture d'une carte réelle
    dont on ne contrôle pas la provenance."""
    if len(sector) < SECTOR_SIZE:
        raise ValueError("secteur d'en-tête GPT incomplet (512 octets attendus)")
    if sector[0:8] != GPT_SIGNATURE:
        raise ValueError('signature GPT absente (« EFI PART » attendue)')
    return GptHeader(
        revision=sector[8:12],
        my_lba=int.from_bytes(sector[24:32], "little"),
        alternate_lba=int.from_bytes(sector[32:40], "little"),
        first_usable_lba=int.from_bytes(sector[40:48], "little"),
        last_usable_lba=int.from_bytes(sector[48:56], "little"),
        disk_guid=sector[56:72],
        partition_entry_lba=int.from_bytes(sector[72:80], "little"),
        num_entries=int.from_bytes(sector[80:84], "little"),
        entry_size=int.from_bytes(sector[84:88], "little"),
        entry_array_crc32=int.from_bytes(sector[88:92], "little"),
    )


def parse_gpt_entries(data: bytes, header: GptHeader) -> List[GptPartitionEntry]:
    """`data` doit contenir au moins `header.num_entries * header.entry_size`
    octets, à partir du début du tableau d'entrées. Les créneaux inutilisés
    (GUID de type nul) sont ignorés."""
    entries = []
    for i in range(header.num_entries):
        offset = i * header.entry_size
        raw = data[offset : offset + header.entry_size]
        if len(raw) < 128 or raw[0:16] == b"\x00" * 16:
            continue
        entries.append(
            GptPartitionEntry(
                type_guid=raw[0:16],
                unique_guid=raw[16:32],
                start_lba=int.from_bytes(raw[32:40], "little"),
                end_lba=int.from_bytes(raw[40:48], "little"),
                attributes=int.from_bytes(raw[48:56], "little"),
                name=raw[56:128],
            )
        )
    return entries


def _crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def build_gpt_entries(
    entries: List[GptPartitionEntry],
    num_entries: int = GPT_DEFAULT_ENTRY_COUNT,
    entry_size: int = GPT_ENTRY_SIZE,
) -> bytes:
    """Sérialise `entries` dans les premiers créneaux du tableau, complété
    de créneaux vides (zéros) jusqu'à `num_entries` -- l'ordre des créneaux
    n'a pas d'importance pour un lecteur GPT conforme (qui doit balayer
    tout le tableau et se fier à `StartingLBA`, pas à la position dans le
    tableau), donc jamais besoin de préserver les créneaux d'origine."""
    if len(entries) > num_entries:
        raise ValueError(f"trop d'entrées ({len(entries)}) pour un tableau de {num_entries} créneaux")
    chunks = []
    for entry in entries:
        raw = (
            entry.type_guid
            + entry.unique_guid
            + entry.start_lba.to_bytes(8, "little")
            + entry.end_lba.to_bytes(8, "little")
            + entry.attributes.to_bytes(8, "little")
            + entry.name.ljust(72, b"\x00")[:72]
        )
        chunks.append(raw.ljust(entry_size, b"\x00")[:entry_size])
    empty_slot = b"\x00" * entry_size
    chunks.extend([empty_slot] * (num_entries - len(entries)))
    return b"".join(chunks)


def build_gpt_header(
    *,
    revision: bytes,
    my_lba: int,
    alternate_lba: int,
    first_usable_lba: int,
    last_usable_lba: int,
    disk_guid: bytes,
    partition_entry_lba: int,
    num_entries: int,
    entry_size: int,
    entries_bytes: bytes,
) -> bytes:
    """Construit un secteur d'en-tête GPT complet (512 octets, complété de
    zéros au-delà des 92 octets significatifs). CRC32 calculés dans le bon
    ordre imposé par la spec UEFI : `entry_array_crc32` d'après
    `entries_bytes` d'abord (il fait partie des champs protégés par
    `header_crc32`), puis `header_crc32` sur l'en-tête entier avec ce
    champ lui-même mis à zéro pendant son propre calcul."""
    entry_array_crc32 = _crc32(entries_bytes)
    header = bytearray(GPT_HEADER_SIZE)
    header[0:8] = GPT_SIGNATURE
    header[8:12] = revision
    header[12:16] = GPT_HEADER_SIZE.to_bytes(4, "little")
    header[16:20] = b"\x00\x00\x00\x00"  # header_crc32, calculé plus bas
    header[20:24] = b"\x00\x00\x00\x00"  # reserved
    header[24:32] = my_lba.to_bytes(8, "little")
    header[32:40] = alternate_lba.to_bytes(8, "little")
    header[40:48] = first_usable_lba.to_bytes(8, "little")
    header[48:56] = last_usable_lba.to_bytes(8, "little")
    header[56:72] = disk_guid
    header[72:80] = partition_entry_lba.to_bytes(8, "little")
    header[80:84] = num_entries.to_bytes(4, "little")
    header[84:88] = entry_size.to_bytes(4, "little")
    header[88:92] = entry_array_crc32.to_bytes(4, "little")

    header_crc32 = _crc32(bytes(header))
    header[16:20] = header_crc32.to_bytes(4, "little")

    return bytes(header).ljust(SECTOR_SIZE, b"\x00")
