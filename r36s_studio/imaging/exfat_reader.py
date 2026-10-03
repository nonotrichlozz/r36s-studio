# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Lecteur exFAT en lecture seule, pour copier fichier par fichier le
contenu d'une image de carte SF3000 (`imaging/sf3000_clone.py`).

Contrairement à `card_probe.py` (qui répond « non » à tout problème et
tronque les répertoires trop grands), ce lecteur **lève** `ExFatError` sur
toute incohérence : une copie qui sauterait silencieusement des fichiers
produirait une carte incomplète présentée comme réussie.

Couvre ce qu'il faut pour recopier une carte : arborescence, taille, date
de modification, attributs (lecture seule, caché, système), contenu (chaîne
FAT ou clusters contigus), étiquette du volume et espace occupé (bitmap
d'allocation). Spécification : Microsoft « exFAT File System
Specification »."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import BinaryIO, Iterator, List, Optional, Tuple

from .card_probe import _Reader
from .mbr import SECTOR_SIZE, is_gpt_protective, parse_mbr

ATTR_READ_ONLY = 0x01
ATTR_HIDDEN = 0x02
ATTR_SYSTEM = 0x04
ATTR_DIRECTORY = 0x10

_END_OF_CHAIN = 0xFFFFFFF7
# Taille maximale d'un répertoire selon la spécification (256 Mio).
_MAX_DIR_BYTES = 256 * 1024 * 1024


class ExFatError(ValueError):
    """Image illisible ou incohérente (pas d'exFAT, chaîne qui boucle,
    entrée tronquée...)."""


@dataclass
class ExFatEntry:
    parts: Tuple[str, ...]  # chemin relatif à la racine, un élément par niveau
    is_dir: bool
    size: int
    valid_size: int
    first_cluster: int
    no_fat_chain: bool
    attributes: int
    mtime: Optional[float]  # secondes depuis l'epoch (UTC), None si date invalide


def _decode_timestamp(stamp: int, increment_10ms: int, utc_offset: int) -> Optional[float]:
    """Horodatage exFAT (format DOS étendu) -> epoch. Avec un décalage UTC
    valide (bit 7), la date est exacte ; sans, elle est lue comme heure
    locale de l'ordinateur, comme le fait Windows."""
    try:
        moment = datetime(
            1980 + (stamp >> 25),
            (stamp >> 21) & 0x0F,
            (stamp >> 16) & 0x1F,
            (stamp >> 11) & 0x1F,
            (stamp >> 5) & 0x3F,
            (stamp & 0x1F) * 2,
        ) + timedelta(milliseconds=10 * min(increment_10ms, 199))
    except ValueError:
        return None
    if utc_offset & 0x80:
        quarters = utc_offset & 0x7F
        if quarters >= 64:
            quarters -= 128
        return (moment - timedelta(minutes=15 * quarters)).replace(tzinfo=timezone.utc).timestamp()
    return time.mktime(moment.timetuple()) + moment.microsecond / 1_000_000


class ExFatVolume:
    def __init__(self, f: BinaryIO, partition_start_bytes: int):
        self._r = _Reader(f, partition_start_bytes)
        boot = self._r.read(0, SECTOR_SIZE)
        if boot[3:11] != b"EXFAT   ":
            raise ExFatError("la partition n'est pas en exFAT")
        bytes_per_sector = 1 << boot[108]
        self.cluster_size = bytes_per_sector << boot[109]
        self.volume_bytes = int.from_bytes(boot[72:80], "little") * bytes_per_sector
        self._fat_offset = int.from_bytes(boot[80:84], "little") * bytes_per_sector
        self._heap_offset = int.from_bytes(boot[88:92], "little") * bytes_per_sector
        self.cluster_count = int.from_bytes(boot[92:96], "little")
        self._root_cluster = int.from_bytes(boot[96:100], "little")
        self.label = ""
        self._bitmap: Optional[Tuple[int, int]] = None  # (premier cluster, taille)
        for kind, data in self._raw_entries(self._root_cluster, False, None):
            if kind == 0x83:
                self.label = data[2 : 2 + 2 * min(data[1], 11)].decode("utf-16-le", "replace")
            elif kind == 0x81 and self._bitmap is None:
                self._bitmap = (int.from_bytes(data[20:24], "little"), int.from_bytes(data[24:32], "little"))

    # --- clusters -----------------------------------------------------------

    def _clusters(self, first: int, no_fat_chain: bool, size: int) -> List[int]:
        count = -(-size // self.cluster_size)
        if count == 0:
            return []
        if not 2 <= first or first + (count if no_fat_chain else 1) - 2 > self.cluster_count:
            raise ExFatError(f"cluster hors du volume ({first})")
        if no_fat_chain:
            return list(range(first, first + count))
        clusters, cluster = [], first
        while len(clusters) < count:
            if not 2 <= cluster < _END_OF_CHAIN or cluster - 2 >= self.cluster_count:
                raise ExFatError(f"chaîne de clusters interrompue (cluster {cluster})")
            clusters.append(cluster)
            cluster = self._r.fat_entry(self._fat_offset, cluster)
        return clusters

    def _chain_until_end(self, first: int) -> List[int]:
        """Répertoire sans taille connue (la racine) : suit la chaîne FAT
        jusqu'à sa fin, en refusant toute boucle."""
        clusters, seen, cluster = [], set(), first
        while 2 <= cluster < _END_OF_CHAIN:
            if cluster in seen or cluster - 2 >= self.cluster_count:
                raise ExFatError(f"chaîne de clusters invalide (cluster {cluster})")
            if len(clusters) * self.cluster_size >= _MAX_DIR_BYTES:
                raise ExFatError("répertoire démesuré")
            seen.add(cluster)
            clusters.append(cluster)
            cluster = self._r.fat_entry(self._fat_offset, cluster)
        return clusters

    def _read_runs(self, clusters: List[int], length: int, chunk_size: int) -> Iterator[bytes]:
        """Lit `length` octets le long de `clusters`, par blocs contigus
        d'au plus `chunk_size` (au moins un cluster)."""
        chunk_clusters = max(1, chunk_size // self.cluster_size)
        i = 0
        while i < len(clusters) and length > 0:
            j = i + 1
            while j < len(clusters) and j - i < chunk_clusters and clusters[j] == clusters[j - 1] + 1:
                j += 1
            n = min(length, (j - i) * self.cluster_size)
            yield self._r.read(self._heap_offset + (clusters[i] - 2) * self.cluster_size, n)
            length -= n
            i = j

    # --- répertoires --------------------------------------------------------

    def _raw_entries(self, first: int, no_fat_chain: bool, size: Optional[int]) -> Iterator[Tuple[int, bytes]]:
        """(type, entrée de 32 octets suivie de ses secondaires) pour chaque
        entrée en service du répertoire."""
        if size is None:
            clusters = self._chain_until_end(first)
            size = len(clusters) * self.cluster_size
        else:
            if size > _MAX_DIR_BYTES:
                raise ExFatError("répertoire démesuré")
            clusters = self._clusters(first, no_fat_chain, size)
        data = b"".join(self._read_runs(clusters, size, 4 * 1024 * 1024))
        i = 0
        while i + 32 <= len(data):
            kind = data[i]
            if kind == 0x00:
                return
            if kind == 0x85:
                end = i + 32 * (data[i + 1] + 1)
                if end > len(data):
                    raise ExFatError("entrée de fichier tronquée")
                yield kind, data[i:end]
                i = end
                continue
            if kind & 0x80:
                yield kind, data[i : i + 32]
            i += 32

    def _entries(self, parent: Tuple[str, ...], first: int, no_fat_chain: bool, size: Optional[int]) -> Iterator[ExFatEntry]:
        for kind, data in self._raw_entries(first, no_fat_chain, size):
            if kind != 0x85:
                continue
            stream = data[32:64]
            if len(stream) < 32 or stream[0] != 0xC0:
                raise ExFatError("entrée de fichier sans extension de flux")
            name_units = stream[3]
            name = b"".join(data[k : k + 32][2:32] for k in range(64, len(data), 32) if data[k] == 0xC1)
            name = name.decode("utf-16-le", "replace")[:name_units]
            if len(name) != name_units or not name:
                raise ExFatError("nom de fichier tronqué")
            attributes = int.from_bytes(data[4:6], "little")
            yield ExFatEntry(
                parts=parent + (name,),
                is_dir=bool(attributes & ATTR_DIRECTORY),
                size=int.from_bytes(stream[24:32], "little"),
                valid_size=int.from_bytes(stream[8:16], "little"),
                first_cluster=int.from_bytes(stream[20:24], "little"),
                no_fat_chain=bool(stream[1] & 0x02),
                attributes=attributes,
                mtime=_decode_timestamp(int.from_bytes(data[12:16], "little"), data[21], data[23]),
            )

    def walk(self) -> Iterator[ExFatEntry]:
        """Toute l'arborescence, chaque dossier avant son contenu."""
        stack: List[Tuple[Tuple[str, ...], int, bool, Optional[int]]] = [((), self._root_cluster, False, None)]
        while stack:
            parent, first, no_chain, size = stack.pop()
            children = list(self._entries(parent, first, no_chain, size))
            for entry in children:
                yield entry
            for entry in reversed(children):
                if entry.is_dir:
                    stack.append((entry.parts, entry.first_cluster, entry.no_fat_chain, entry.size))

    def read_file(self, entry: ExFatEntry, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
        """Contenu du fichier ; au-delà de `valid_size`, des zéros (ce que
        renvoie aussi le pilote exFAT)."""
        clusters = self._clusters(entry.first_cluster, entry.no_fat_chain, entry.size)
        valid = min(entry.valid_size, entry.size)
        yield from self._read_runs(clusters, valid, chunk_size)
        remaining = entry.size - valid
        while remaining > 0:
            n = min(remaining, chunk_size)
            yield b"\x00" * n
            remaining -= n

    def used_bytes(self) -> int:
        """Espace occupé d'après le bitmap d'allocation (fichiers, dossiers
        et métadonnées du volume)."""
        if self._bitmap is None:
            raise ExFatError("bitmap d'allocation introuvable")
        first, size = self._bitmap
        bitmap = b"".join(self._read_runs(self._clusters(first, False, size), size, 4 * 1024 * 1024))
        full_bytes, extra_bits = divmod(self.cluster_count, 8)
        used = sum(bin(b).count("1") for b in bitmap[:full_bytes])
        if extra_bits:
            used += bin(bitmap[full_bytes] & ((1 << extra_bits) - 1)).count("1")
        return used * self.cluster_size


def first_partition_start(f: BinaryIO) -> int:
    """Octet de début de la première partition MBR ; lève `ExFatError` si
    la table est absente ou GPT."""
    f.seek(0)
    try:
        partitions = parse_mbr(f.read(SECTOR_SIZE))
    except ValueError as exc:
        raise ExFatError(str(exc)) from exc
    if not partitions or is_gpt_protective(partitions):
        raise ExFatError("aucune partition MBR")
    return min(partitions, key=lambda p: p.index).start_bytes


__all__ = [
    "ATTR_HIDDEN",
    "ATTR_READ_ONLY",
    "ATTR_SYSTEM",
    "ExFatEntry",
    "ExFatError",
    "ExFatVolume",
    "first_partition_start",
]
