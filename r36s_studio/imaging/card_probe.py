# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Reconnaît, en lecture seule, une carte de console SF3000 (puce HiChip,
menu d'origine « cubegm » ou TreeFrogUI) : la première partition MBR
contient `cubegm/rkgame`, le lanceur de jeux du système de la console.

Sert à une seule décision (`__main__.py::cmd_flash`) : ne pas créer de
partition de jeux séparée après le flash. Le système de ces consoles ne lit
que `/mnt/sdcard` -- la première partition (scripts `cubegm/*.sh`,
`rootfs/etc/mdev/mount-helper.sh` de la carte d'origine : toute autre
partition finirait sous `/media/mmcblk0pN`, qu'aucun programme ne lit). Une
partition EASYROMS y serait donc de l'espace perdu, invisible pour la
console (constaté sur un clone de carte SF3000HD d'origine en 128 Go).

Lit directement le périphérique brut, comme `games_partition.py::
_peek_free_games_partition_bytes` : fonctionne sur les trois OS même
volume monté (seule l'écriture exige verrouillage/démontage, §4.3), sans
dépendre du remontage automatique après flash. Toutes les lectures sont
alignées sur 512 octets (exigé par `\\\\.\\PhysicalDriveN` sous Windows).

Systèmes de fichiers pris en charge : exFAT (carte d'origine) et FAT32
(carte TreeFrogUI). Tout le reste (ext4 d'ArkOS, GPT, table illisible…)
répond simplement « non » -- jamais une exception : ce test ne doit jamais
faire échouer un flash déjà réussi.
"""

from __future__ import annotations

from typing import Dict, Iterator, List, Optional, Tuple

from .mbr import SECTOR_SIZE, is_gpt_protective, parse_mbr

# Chemin cherché, comparé sans tenir compte de la casse (exFAT et FAT32 sont
# insensibles à la casse côté console comme côté PC).
SIGNATURE_PATH = ("cubegm", "rkgame")

# Garde-fous contre une table corrompue : une chaîne de clusters qui boucle
# ou un répertoire démesuré ne doivent jamais bloquer le worker.
_MAX_DIR_CLUSTERS = 256
_MAX_DIR_BYTES = 4 * 1024 * 1024

_EXFAT_END_OF_CHAIN = 0xFFFFFFF7
_FAT32_END_OF_CHAIN = 0x0FFFFFF8


class _Reader:
    """Lectures alignées sur le secteur, relatives au début de la partition."""

    def __init__(self, f, partition_start_bytes: int):
        self._f = f
        self._base = partition_start_bytes
        self._fat_cache: Dict[int, bytes] = {}

    def read(self, offset: int, length: int) -> bytes:
        start = (self._base + offset) // SECTOR_SIZE * SECTOR_SIZE
        end = -(-(self._base + offset + length) // SECTOR_SIZE) * SECTOR_SIZE
        self._f.seek(start)
        data = self._f.read(end - start)
        skip = self._base + offset - start
        chunk = data[skip : skip + length]
        if len(chunk) != length:
            raise EOFError("lecture tronquée")
        return chunk

    def fat_entry(self, fat_offset: int, cluster: int, mask: int = 0xFFFFFFFF) -> int:
        byte = fat_offset + cluster * 4
        sector = byte // SECTOR_SIZE
        if sector not in self._fat_cache:
            self._fat_cache[sector] = self.read(sector * SECTOR_SIZE, SECTOR_SIZE)
        pos = byte % SECTOR_SIZE
        return int.from_bytes(self._fat_cache[sector][pos : pos + 4], "little") & mask


def _chain(reader: _Reader, fat_offset: int, first: int, end_marker: int, mask: int = 0xFFFFFFFF) -> List[int]:
    clusters, cluster = [], first
    while 2 <= cluster < end_marker and len(clusters) < _MAX_DIR_CLUSTERS:
        if cluster in clusters:  # boucle
            break
        clusters.append(cluster)
        cluster = reader.fat_entry(fat_offset, cluster, mask)
    return clusters


# --- exFAT --------------------------------------------------------------------


class _ExFat:
    def __init__(self, reader: _Reader, boot: bytes):
        self.r = reader
        self.bytes_per_sector = 1 << boot[108]
        self.cluster_size = self.bytes_per_sector << boot[109]
        self.fat_offset = int.from_bytes(boot[80:84], "little") * self.bytes_per_sector
        self.heap_offset = int.from_bytes(boot[88:92], "little") * self.bytes_per_sector
        self.root_cluster = int.from_bytes(boot[96:100], "little")

    def _cluster_bytes(self, cluster: int) -> bytes:
        return self.r.read(self.heap_offset + (cluster - 2) * self.cluster_size, self.cluster_size)

    def _dir_bytes(self, first: int, no_fat_chain: bool, length: Optional[int]) -> bytes:
        if no_fat_chain and length:
            count = min(-(-length // self.cluster_size), _MAX_DIR_CLUSTERS)
            clusters = list(range(first, first + count))
        else:
            clusters = _chain(self.r, self.fat_offset, first, _EXFAT_END_OF_CHAIN)
        data = b"".join(self._cluster_bytes(c) for c in clusters)
        return data[: min(len(data), _MAX_DIR_BYTES)]

    def entries(self, first: int, no_fat_chain: bool = False, length: Optional[int] = None) -> Iterator[Tuple[str, bool, int, bool, int]]:
        """(nom, est_un_dossier, premier_cluster, sans_chaîne_FAT, taille)"""
        data = self._dir_bytes(first, no_fat_chain, length)
        i = 0
        while i + 32 <= len(data):
            kind = data[i]
            if kind == 0x00:
                return
            if kind == 0x85 and i + 64 <= len(data):
                secondary = data[i + 1]
                is_dir = bool(int.from_bytes(data[i + 4 : i + 6], "little") & 0x10)
                stream = data[i + 32 : i + 64]
                if stream[0] == 0xC0:
                    flags, name_len = stream[1], stream[3]
                    first_cluster = int.from_bytes(stream[20:24], "little")
                    size = int.from_bytes(stream[24:32], "little")
                    name = b""
                    for k in range(2, secondary + 1):
                        e = data[i + 32 * k : i + 32 * (k + 1)]
                        if len(e) == 32 and e[0] == 0xC1:
                            name += e[2:32]
                    yield (
                        name.decode("utf-16-le", "replace")[:name_len],
                        is_dir,
                        first_cluster,
                        bool(flags & 0x02),
                        size,
                    )
                i += 32 * (secondary + 1)
                continue
            i += 32

    def exists(self, path: Tuple[str, ...]) -> bool:
        first, no_chain, length, is_dir = self.root_cluster, False, None, True
        for depth, part in enumerate(path):
            if not is_dir:
                return False
            for name, entry_is_dir, cluster, entry_no_chain, size in self.entries(first, no_chain, length):
                if name.lower() == part.lower():
                    if depth == len(path) - 1:
                        return True
                    first, no_chain, length, is_dir = cluster, entry_no_chain, size, entry_is_dir
                    break
            else:
                return False
        return False


# --- FAT32 --------------------------------------------------------------------


class _Fat32:
    def __init__(self, reader: _Reader, boot: bytes):
        self.r = reader
        self.bytes_per_sector = int.from_bytes(boot[11:13], "little")
        self.cluster_size = self.bytes_per_sector * boot[13]
        reserved = int.from_bytes(boot[14:16], "little")
        fat_size = int.from_bytes(boot[36:40], "little")
        self.fat_offset = reserved * self.bytes_per_sector
        self.data_offset = (reserved + boot[16] * fat_size) * self.bytes_per_sector
        self.root_cluster = int.from_bytes(boot[44:48], "little")

    def entries(self, first: int) -> Iterator[Tuple[str, bool, int]]:
        clusters = _chain(self.r, self.fat_offset, first, _FAT32_END_OF_CHAIN, 0x0FFFFFFF)
        lfn: Dict[int, str] = {}
        for cluster in clusters:
            data = self.r.read(self.data_offset + (cluster - 2) * self.cluster_size, self.cluster_size)
            for i in range(0, len(data) - 31, 32):
                e = data[i : i + 32]
                if e[0] == 0x00:
                    return
                if e[0] == 0xE5:
                    lfn.clear()
                    continue
                if e[11] == 0x0F:  # morceau de nom long
                    chars = e[1:11] + e[14:26] + e[28:32]
                    lfn[e[0] & 0x3F] = chars.decode("utf-16-le", "replace").split("\x00")[0]
                    continue
                if e[11] & 0x08:  # étiquette de volume
                    lfn.clear()
                    continue
                if lfn:
                    name = "".join(lfn[k] for k in sorted(lfn))
                else:
                    base, ext = e[0:8].decode("ascii", "replace").rstrip(), e[8:11].decode("ascii", "replace").rstrip()
                    name = f"{base}.{ext}" if ext else base
                lfn.clear()
                cluster_hi = int.from_bytes(e[20:22], "little")
                cluster_lo = int.from_bytes(e[26:28], "little")
                yield name, bool(e[11] & 0x10), (cluster_hi << 16) | cluster_lo

    def exists(self, path: Tuple[str, ...]) -> bool:
        first, is_dir = self.root_cluster, True
        for depth, part in enumerate(path):
            if not is_dir:
                return False
            for name, entry_is_dir, cluster in self.entries(first):
                if name.lower() == part.lower():
                    if depth == len(path) - 1:
                        return True
                    first, is_dir = cluster, entry_is_dir
                    break
            else:
                return False
        return False


def first_partition_contains(device_path: str, path: Tuple[str, ...] = SIGNATURE_PATH) -> bool:
    """Vrai si la première partition MBR du périphérique (exFAT ou FAT32)
    contient `path`. Faux pour tout le reste, sans jamais lever."""
    try:
        with open(device_path, "rb") as f:
            first_sector = f.read(SECTOR_SIZE)
            partitions = parse_mbr(first_sector)
            if not partitions or is_gpt_protective(partitions):
                return False
            first = min(partitions, key=lambda p: p.index)
            reader = _Reader(f, first.start_bytes)
            boot = reader.read(0, SECTOR_SIZE)
            if boot[3:11] == b"EXFAT   ":
                return _ExFat(reader, boot).exists(path)
            if boot[82:90] == b"FAT32   ":
                return _Fat32(reader, boot).exists(path)
            return False
    except (OSError, ValueError, EOFError, IndexError, ZeroDivisionError):
        return False


def is_sf3000_card(device_path: str) -> bool:
    """Carte de console SF3000 (menu d'origine ou TreeFrogUI) : `cubegm/
    rkgame` présent sur la première partition."""
    return first_partition_contains(device_path, SIGNATURE_PATH)


__all__ = ["SIGNATURE_PATH", "first_partition_contains", "is_sf3000_card"]
