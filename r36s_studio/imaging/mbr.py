# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Lecture de la table de partitions MBR (Master Boot Record).

Seul le MBR est couvert en phase 2 (pas GPT — voir §4.3 : « À vérifier sur
une carte réelle »). Sert à calculer où s'arrête la dernière partition
utilisée, pour ne pas sauvegarder 128 Go quand les données s'arrêtent à
8 Go (« sauvegarde intelligente »)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SECTOR_SIZE = 512
MBR_SIGNATURE = b"\x55\xaa"
PARTITION_TABLE_OFFSET = 446
PARTITION_ENTRY_SIZE = 16
PARTITION_COUNT = 4
GPT_PROTECTIVE_TYPE = 0xEE


@dataclass
class MbrPartition:
    index: int
    partition_type: int
    start_lba: int
    sector_count: int

    @property
    def start_bytes(self) -> int:
        return self.start_lba * SECTOR_SIZE

    @property
    def end_bytes(self) -> int:
        return (self.start_lba + self.sector_count) * SECTOR_SIZE


def parse_mbr(first_sector: bytes) -> list[MbrPartition]:
    """`first_sector` doit contenir au moins les 512 premiers octets du
    périphérique. Retourne les partitions non vides des 4 entrées de la
    table MBR (les partitions étendues ne sont pas suivies)."""
    if len(first_sector) < SECTOR_SIZE:
        raise ValueError("secteur MBR incomplet (512 octets attendus)")

    if first_sector[510:512] != MBR_SIGNATURE:
        raise ValueError("signature MBR absente (0x55AA)")

    partitions = []
    for i in range(PARTITION_COUNT):
        offset = PARTITION_TABLE_OFFSET + i * PARTITION_ENTRY_SIZE
        entry = first_sector[offset : offset + PARTITION_ENTRY_SIZE]
        partition_type = entry[4]
        start_lba = int.from_bytes(entry[8:12], "little")
        sector_count = int.from_bytes(entry[12:16], "little")
        if partition_type == 0 or sector_count == 0:
            continue
        partitions.append(MbrPartition(i, partition_type, start_lba, sector_count))
    return partitions


def is_gpt_protective(partitions: list) -> bool:
    return any(p.partition_type == GPT_PROTECTIVE_TYPE for p in partitions)


def last_used_byte(first_sector: bytes, device_size_bytes: Optional[int] = None) -> int:
    """Calcule la fin (en octets) de la dernière partition MBR utilisée.

    Si la table est un MBR protecteur GPT, ou si aucune partition n'y est
    trouvée, la lecture GPT n'est pas implémentée en phase 2 : on se replie
    sur `device_size_bytes` (copie complète du périphérique). Lève
    `ValueError` si ce repli est nécessaire mais qu'aucune taille n'a été
    fournie."""
    partitions = parse_mbr(first_sector)
    if not partitions or is_gpt_protective(partitions):
        if device_size_bytes is None:
            raise ValueError(
                "impossible de déterminer la fin utile de la table de partitions "
                "(GPT ou table vide) sans taille totale de repli"
            )
        return device_size_bytes
    return max(p.end_bytes for p in partitions)
