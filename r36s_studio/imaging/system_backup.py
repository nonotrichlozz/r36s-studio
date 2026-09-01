"""Sauvegarde « système sans les jeux » (§4.3) : comme `imaging/backup.py`,
mais s'arrête à la fin de la dernière partition système -- juste avant la
partition de jeux (EASYROMS ou STORAGE) -- plutôt qu'à la fin de la
dernière partition utilisée toutes catégories confondues. Typiquement
8-9 Go au lieu de 100 Go sur une carte R36S d'origine, la partition de
jeux représentant l'essentiel de l'espace utilisé.

Identifie la partition de jeux via `partitions/locate.py::list_partitions`
(étiquette, comme le reste du projet) plutôt qu'en lisant la table de
partitions brute pour ça : une table MBR brute n'a aucun concept
d'étiquette de partition (contrairement à GPT, où le nom pourrait en
théorie être lu directement -- mais rester sur `list_partitions` pour les
deux schémas garde un seul chemin d'identification, cohérent avec le reste
du projet, plutôt que deux logiques différentes selon MBR/GPT). La table
brute (MBR ou GPT, lue séparément ici) ne sert qu'à trouver l'octet exact
où s'arrête la partition précédente, une fois l'index de la partition de
jeux connu -- `list_partitions` et la table brute sont supposées lister
les partitions dans le même ordre (position sur le disque), même
hypothèse déjà faite ailleurs dans ce projet (`partitions/locate.py::
BOOT_PARTITION_INDEX`/`EASYROMS_PARTITION_INDEX`).

**Point critique, table GPT** : contrairement à MBR (une table unique en
tête de disque, sans référence à la fin du disque), GPT porte une table
secondaire en toute fin de disque, et l'en-tête primaire y pointe
(`AlternateLBA`). Une simple troncature laisserait cette table secondaire
manquante et l'en-tête primaire pointant vers une position hors du
fichier -- un outil de flashage la rejette alors comme incohérente/
corrompue plutôt que de simplement ignorer l'absence. `backup_system_only`
reconstruit donc une table secondaire cohérente à la nouvelle fin de
fichier (partition de jeux retirée), et met à jour l'en-tête primaire en
conséquence (`imaging/gpt.py`)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from r36s_studio.devices import Device
from r36s_studio.partitions.locate import PartitionInfo, list_partitions

from .copy import BLOCK_SIZE, CancelCheck, ProgressCallback, copy_range
from .gpt import GptHeader, GptPartitionEntry, build_gpt_entries, build_gpt_header, parse_gpt_entries, parse_gpt_header
from .mbr import SECTOR_SIZE, is_gpt_protective, parse_mbr
from .source import prepared_source

# Étiquettes reconnues pour la partition de jeux (§4.4) -- EASYROMS sur
# ArkOS/dArkOS/ROCKNIX-avec-jeux-séparés, STORAGE sur EmuELEC.
GAMES_PARTITION_LABELS = {"EASYROMS", "STORAGE"}


class GamesPartitionNotFound(Exception):
    """Aucune partition de jeux reconnue (§ note de module) -- courant sur
    une carte ROCKNIX (les jeux vivent dans la partition Linux, pas une
    partition séparée) ou une carte au système non reconnu. La sauvegarde
    système sans les jeux n'a alors pas de frontière évidente où
    s'arrêter."""


@dataclass
class SystemBoundary:
    end_bytes: int
    is_gpt: bool
    # Renseignés seulement si `is_gpt` -- nécessaires pour reconstruire la
    # table secondaire une fois la copie tronquée effectuée.
    gpt_header: Optional[GptHeader] = None
    kept_gpt_entries: Optional[List[GptPartitionEntry]] = None


def _games_partition_index(partitions: List[PartitionInfo]) -> Optional[int]:
    for index, partition in enumerate(partitions):
        if partition.label.upper() in GAMES_PARTITION_LABELS:
            return index
    return None


def compute_system_boundary(device_path: str) -> SystemBoundary:
    """Détermine jusqu'où copier pour une sauvegarde système sans les jeux
    -- schéma MBR ou GPT détecté automatiquement (même critère que `mbr.
    is_gpt_protective`, déjà utilisé par `imaging/backup.py`). Lève
    `GamesPartitionNotFound` si aucune partition de jeux n'est
    identifiable sur cette carte, ou si elle est la toute première
    partition (rien à garder avant elle)."""
    partitions = list_partitions(device_path)
    games_index = _games_partition_index(partitions)
    if games_index is None or games_index == 0:
        raise GamesPartitionNotFound(
            "Aucune partition de jeux reconnue (EASYROMS ou STORAGE) sur cette carte."
        )

    with open(device_path, "rb") as f:
        first_sector = f.read(SECTOR_SIZE)
        mbr_partitions = parse_mbr(first_sector)

        if not is_gpt_protective(mbr_partitions):
            mbr_sorted = sorted(mbr_partitions, key=lambda p: p.start_lba)
            if games_index >= len(mbr_sorted):
                raise GamesPartitionNotFound(
                    "La partition de jeux détectée ne correspond à aucune entrée de la table MBR."
                )
            boundary = mbr_sorted[games_index - 1]
            return SystemBoundary(end_bytes=boundary.end_bytes, is_gpt=False)

        header_sector = f.read(SECTOR_SIZE)  # LBA1, juste après LBA0 déjà lu
        header = parse_gpt_header(header_sector)
        f.seek(header.partition_entry_lba * SECTOR_SIZE)
        entries_bytes = f.read(header.num_entries * header.entry_size)
        entries = parse_gpt_entries(entries_bytes, header)

    entries_sorted = sorted(entries, key=lambda e: e.start_lba)
    if games_index >= len(entries_sorted):
        raise GamesPartitionNotFound(
            "La partition de jeux détectée ne correspond à aucune entrée de la table GPT."
        )
    boundary_entry = entries_sorted[games_index - 1]
    kept_entries = entries_sorted[:games_index]
    end_bytes = (boundary_entry.end_lba + 1) * SECTOR_SIZE
    return SystemBoundary(end_bytes=end_bytes, is_gpt=True, gpt_header=header, kept_gpt_entries=kept_entries)


def _gpt_secondary_table_size(header: GptHeader) -> int:
    entries_size = header.num_entries * header.entry_size
    entries_size_sectors = -(-entries_size // SECTOR_SIZE)  # arrondi au secteur supérieur
    return entries_size_sectors * SECTOR_SIZE + SECTOR_SIZE  # + en-tête secondaire


def _rewrite_gpt_tables_after_truncation(destination, boundary: SystemBoundary) -> None:
    """Appelé juste après avoir tronqué la copie à `boundary.end_bytes` --
    reconstruit la table secondaire à la nouvelle fin de fichier et met à
    jour la table primaire en conséquence (§ point critique de module).
    `destination` doit être positionné à `boundary.end_bytes` (fin de la
    copie tronquée) à l'appel ; repositionné là à la fin, prêt pour tout
    ajout ultérieur (aucun aujourd'hui)."""
    header = boundary.gpt_header
    entries_bytes = build_gpt_entries(
        boundary.kept_gpt_entries, num_entries=header.num_entries, entry_size=header.entry_size
    )
    entries_size_sectors = -(-len(entries_bytes) // SECTOR_SIZE)
    entries_bytes_padded = entries_bytes.ljust(entries_size_sectors * SECTOR_SIZE, b"\x00")

    secondary_entries_lba = boundary.end_bytes // SECTOR_SIZE
    secondary_header_lba = secondary_entries_lba + entries_size_sectors
    new_last_usable_lba = secondary_entries_lba - 1

    secondary_header_bytes = build_gpt_header(
        revision=header.revision,
        my_lba=secondary_header_lba,
        alternate_lba=1,  # en-tête primaire, toujours à LBA1
        first_usable_lba=header.first_usable_lba,
        last_usable_lba=new_last_usable_lba,
        disk_guid=header.disk_guid,
        partition_entry_lba=secondary_entries_lba,
        num_entries=header.num_entries,
        entry_size=header.entry_size,
        entries_bytes=entries_bytes,
    )

    destination.write(entries_bytes_padded)
    destination.write(secondary_header_bytes)

    primary_header_bytes = build_gpt_header(
        revision=header.revision,
        my_lba=1,
        alternate_lba=secondary_header_lba,
        first_usable_lba=header.first_usable_lba,
        last_usable_lba=new_last_usable_lba,
        disk_guid=header.disk_guid,
        partition_entry_lba=header.partition_entry_lba,
        num_entries=header.num_entries,
        entry_size=header.entry_size,
        entries_bytes=entries_bytes,
    )
    end_of_file = destination.tell()
    destination.seek(1 * SECTOR_SIZE)
    destination.write(primary_header_bytes)
    destination.seek(header.partition_entry_lba * SECTOR_SIZE)
    destination.write(entries_bytes_padded)
    destination.seek(end_of_file)


def estimate_system_backup_size(device_path: str) -> int:
    """Taille (en octets) qu'occupera la sauvegarde -- copie tronquée plus,
    pour une carte GPT, la table secondaire reconstruite (§ point critique
    de module). Utilisé pour afficher une estimation avant de lancer
    l'opération, sans avoir besoin d'élévation (lecture de quelques
    secteurs seulement, comme `partitions/locate.py`)."""
    boundary = compute_system_boundary(device_path)
    if boundary.is_gpt:
        return boundary.end_bytes + _gpt_secondary_table_size(boundary.gpt_header)
    return boundary.end_bytes


def backup_system_only(
    device: Device,
    output_path: str,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
    should_cancel: Optional[CancelCheck] = None,
) -> int:
    """Sauvegarde `device` (lecture seule) dans `output_path`, jusqu'à la
    fin de la dernière partition système -- sans la partition de jeux
    (§ note de module). Reconstruit une table GPT secondaire cohérente en
    fin de fichier si nécessaire. Retourne la taille finale du fichier
    écrit (copie tronquée + table secondaire éventuelle -- contrairement à
    `copy_range`, qui ne compte que les octets lus depuis la source).
    Lève `GamesPartitionNotFound` si cette carte n'a pas de partition de
    jeux identifiable ; `OperationCancelled` si `should_cancel` répond
    True en cours de copie (même comportement que `backup_device`)."""
    boundary = compute_system_boundary(device.path)
    with prepared_source(device.path) as raw_path:
        with open(raw_path, "rb") as source, open(output_path, "wb") as destination:
            copy_range(
                source,
                destination,
                boundary.end_bytes,
                on_progress=on_progress,
                block_size=block_size,
                should_cancel=should_cancel,
            )
            if boundary.is_gpt:
                _rewrite_gpt_tables_after_truncation(destination, boundary)
            destination.flush()
            os.fsync(destination.fileno())

    if boundary.is_gpt:
        return boundary.end_bytes + _gpt_secondary_table_size(boundary.gpt_header)
    return boundary.end_bytes
