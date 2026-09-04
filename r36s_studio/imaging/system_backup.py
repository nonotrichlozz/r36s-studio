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

**Estimation sans accès brut** (`estimate_system_backup_size_unprivileged`,
§4.3) : confirmé sur du vrai matériel, lire la table de partitions brute
exige les droits administrateur sur macOS (`[Errno 13] Permission denied:
'/dev/diskN'`) -- inutile pour une simple estimation avant de lancer
l'opération, qui n'a pas besoin d'être exacte à l'octet près.
`list_partitions` expose déjà la taille de chaque partition sans
élévation ; sommer les partitions gardées suffit. Ne remplace pas
`compute_system_boundary` (toujours utilisé par l'opération réelle,
précise, élevée via le worker) — seulement l'affichage préalable.

**Point critique, table GPT** : contrairement à MBR (une table unique en
tête de disque, sans référence à la fin du disque), GPT porte une table
secondaire en toute fin de disque, et l'en-tête primaire y pointe
(`AlternateLBA`). Une simple troncature laisserait cette table secondaire
manquante et l'en-tête primaire pointant vers une position hors du
fichier -- un outil de flashage la rejette alors comme incohérente/
corrompue plutôt que de simplement ignorer l'absence. `backup_system_only`
reconstruit donc une table secondaire cohérente à la nouvelle fin de
fichier (partition de jeux retirée), et met à jour l'en-tête primaire en
conséquence (`imaging/gpt.py`). Confirmé sur du vrai matériel : sans cette
réparation, `gdisk` signale « Disk size is smaller than the main header
indicates » et « Backup header: ERROR », Linux ne voit aucune partition,
et la console ne démarre pas.

**Point critique, table MBR aussi** : moins visible que le cas GPT
ci-dessus (pas de table secondaire à reconstruire), mais tout aussi
nécessaire -- une simple troncature laisserait, dans l'image produite,
l'entrée de la partition de jeux décrivant un espace qui s'étend bien
au-delà de la fin réelle du fichier. `backup_system_only` retire donc
cette entrée (et toute entrée après elle) du premier secteur de l'image
produite -- une simple mise à zéro des 16 octets du créneau concerné,
MBR n'ayant ni CRC ni table secondaire à recalculer.

**Identification de la partition de jeux** : par étiquette d'abord
(EASYROMS ou STORAGE, comme le reste du projet, via `partitions/
locate.py::list_partitions`) ; à défaut d'étiquette reconnue, repli sur
la dernière partition du disque si son système de fichiers est FAT, NTFS
ou exFAT et si elle dépasse `_LARGE_PARTITION_THRESHOLD_BYTES` -- une
carte dont la partition de jeux ne porte aucune des deux étiquettes
connues reste ainsi couverte, sans risquer de prendre une petite
partition FAT (BOOT, par exemple) pour la partition de jeux. Le système
de fichiers d'EASYROMS varie selon le vendeur (NTFS constaté sur
certaines cartes, exFAT sur d'autres, confirmé sur du vrai matériel) --
une info à consigner, jamais un critère d'exclusion."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

from r36s_studio.devices import Device
from r36s_studio.partitions.locate import PartitionInfo, list_partitions

from .copy import BLOCK_SIZE, CancelCheck, ProgressCallback, copy_range
from .gpt import GptHeader, GptPartitionEntry, build_gpt_entries, build_gpt_header, parse_gpt_entries, parse_gpt_header
from .mbr import GPT_PROTECTIVE_TYPE, PARTITION_ENTRY_SIZE, PARTITION_TABLE_OFFSET, SECTOR_SIZE, is_gpt_protective, parse_mbr
from .source import prepared_source

# Étiquettes reconnues pour la partition de jeux (§4.4) -- EASYROMS sur
# ArkOS/dArkOS/ROCKNIX-avec-jeux-séparés, STORAGE sur EmuELEC.
GAMES_PARTITION_LABELS = {"EASYROMS", "STORAGE"}

# Repli quand aucune étiquette ne correspond (§ note de module) -- systèmes
# de fichiers plausibles pour une partition de jeux, et seuil de taille
# (1 Go) en dessous duquel une dernière partition FAT/NTFS/exFAT a plus de
# chances d'être une partition système méconnue qu'une partition de jeux.
# Le système de fichiers d'EASYROMS varie selon le vendeur (NTFS constaté
# sur certaines cartes, exFAT sur d'autres, confirmé sur du vrai matériel)
# -- une info à consigner, jamais un critère d'exclusion.
GAMES_PARTITION_FALLBACK_FILESYSTEMS = {"ntfs", "exfat", "msdos", "vfat", "fat", "fat16", "fat32"}
_LARGE_PARTITION_THRESHOLD_BYTES = 1_000_000_000


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
    # Renseigné seulement si `not is_gpt` -- créneaux (0-3) de la table MBR
    # à mettre à zéro dans l'image produite (§ point critique de module).
    removed_mbr_slot_indices: List[int] = field(default_factory=list)


def _labeled_games_partition_index(partitions: List[PartitionInfo]) -> Optional[int]:
    for index, partition in enumerate(partitions):
        if partition.label.upper() in GAMES_PARTITION_LABELS:
            return index
    return None


def _fallback_games_partition_index(partitions: List[PartitionInfo], raw_sizes_bytes: List[int]) -> Optional[int]:
    """Repli sans étiquette reconnue (§ note de module) : dernière
    partition, système de fichiers FAT/NTFS/exFAT, de grande taille. `raw_sizes_
    bytes` doit être dans le même ordre (position sur le disque) que
    `partitions` -- la taille vient de la table brute, `list_partitions`
    n'exposant aucune taille."""
    if not partitions or len(raw_sizes_bytes) != len(partitions):
        return None
    last_index = len(partitions) - 1
    last = partitions[last_index]
    if last.filesystem.lower() not in GAMES_PARTITION_FALLBACK_FILESYSTEMS:
        return None
    if raw_sizes_bytes[last_index] < _LARGE_PARTITION_THRESHOLD_BYTES:
        return None
    return last_index


def _resolve_games_partition_index(partitions: List[PartitionInfo], raw_sizes_bytes: List[int]) -> Optional[int]:
    index = _labeled_games_partition_index(partitions)
    if index is not None:
        return index
    return _fallback_games_partition_index(partitions, raw_sizes_bytes)


def estimate_system_backup_size_unprivileged(device_path: str) -> Optional[int]:
    """Estime la taille sans jamais lire la table de partitions brute --
    confirmé sur du vrai matériel : `/dev/diskN` exige les droits
    administrateur sur macOS (`[Errno 13] Permission denied`), alors que
    `partitions/locate.py::list_partitions` (déjà utilisé pour identifier
    la partition de jeux) expose la taille de chaque partition sans
    élévation (`diskutil info -plist`/`lsblk`/`Get-Volume`). Une
    estimation n'a pas besoin d'être exacte à l'octet près, contrairement
    à `compute_system_boundary` (utilisé par l'opération réelle,
    `backup_system_only`, qui passe de toute façon par le worker élevé,
    §3) -- ignore volontairement le supplément de la table secondaire GPT
    (~16 Ko, négligeable face à des tailles de plusieurs Go) plutôt que
    de lire la table brute juste pour distinguer MBR de GPT.

    Retourne `None` quand cette estimation légère n'est pas possible
    (taille manquante pour au moins une partition à sommer, ou pour la
    dernière partition quand le repli sans étiquette doit être tenté) --
    l'appelant retombe alors sur un calcul élevé plutôt que d'afficher un
    chiffre inventé. Lève `GamesPartitionNotFound` (même exception, même
    message) quand aucune partition de jeux n'est identifiable du tout :
    ça resterait vrai après élévation aussi, pas la peine d'y retomber
    pour rien."""
    partitions = list_partitions(device_path)
    sizes = [p.size_bytes for p in partitions]

    games_index = _labeled_games_partition_index(partitions)
    if games_index is None:
        if any(size is None for size in sizes):
            return None
        games_index = _fallback_games_partition_index(partitions, sizes)

    if games_index is None or games_index == 0:
        raise GamesPartitionNotFound(
            "Aucune partition de jeux reconnue (EASYROMS, STORAGE, ou dernière "
            "partition FAT/NTFS/exFAT de grande taille) sur cette carte."
        )

    kept_sizes = sizes[:games_index]
    if any(size is None for size in kept_sizes):
        return None
    return sum(kept_sizes)


def compute_system_boundary(device_path: str) -> SystemBoundary:
    """Détermine jusqu'où copier pour une sauvegarde système sans les jeux
    -- schéma MBR ou GPT détecté automatiquement (même critère que `mbr.
    is_gpt_protective`, déjà utilisé par `imaging/backup.py`). Lève
    `GamesPartitionNotFound` si aucune partition de jeux n'est
    identifiable sur cette carte, ou si elle est la toute première
    partition (rien à garder avant elle)."""
    partitions = list_partitions(device_path)

    with open(device_path, "rb") as f:
        first_sector = f.read(SECTOR_SIZE)
        mbr_partitions = parse_mbr(first_sector)

        if not is_gpt_protective(mbr_partitions):
            mbr_sorted = sorted(mbr_partitions, key=lambda p: p.start_lba)
            raw_sizes = [p.sector_count * SECTOR_SIZE for p in mbr_sorted]
            games_index = _resolve_games_partition_index(partitions, raw_sizes)
            if games_index is None or games_index == 0 or games_index >= len(mbr_sorted):
                raise GamesPartitionNotFound(
                    "Aucune partition de jeux reconnue (EASYROMS, STORAGE, ou dernière "
                    "partition FAT/NTFS/exFAT de grande taille) sur cette carte."
                )
            boundary = mbr_sorted[games_index - 1]
            removed_slots = [p.index for p in mbr_sorted[games_index:]]
            return SystemBoundary(end_bytes=boundary.end_bytes, is_gpt=False, removed_mbr_slot_indices=removed_slots)

        header_sector = f.read(SECTOR_SIZE)  # LBA1, juste après LBA0 déjà lu
        header = parse_gpt_header(header_sector)
        f.seek(header.partition_entry_lba * SECTOR_SIZE)
        entries_bytes = f.read(header.num_entries * header.entry_size)
        entries = parse_gpt_entries(entries_bytes, header)

    entries_sorted = sorted(entries, key=lambda e: e.start_lba)
    raw_sizes = [(e.end_lba - e.start_lba + 1) * SECTOR_SIZE for e in entries_sorted]
    games_index = _resolve_games_partition_index(partitions, raw_sizes)
    if games_index is None or games_index == 0 or games_index >= len(entries_sorted):
        raise GamesPartitionNotFound(
            "Aucune partition de jeux reconnue (EASYROMS, STORAGE, ou dernière "
            "partition FAT/NTFS/exFAT de grande taille) sur cette carte."
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


def _repair_protective_mbr_after_truncation(source, destination, boundary: SystemBoundary) -> None:
    """Bug corrigé, confirmé sur du vrai matériel : le même symptôme
    (image inbootable) apparaissait sur macOS *et* Windows, quelle que
    soit la carte cible -- pas un défaut du chemin Windows, mais un trou
    dans cette réparation elle-même. `_rewrite_gpt_tables_after_
    truncation` corrige bien l'en-tête GPT (primaire et secondaire) et ses
    tableaux d'entrées, mais ne touche jamais LBA0 : le MBR protecteur qui
    y vit continue de décrire la taille du disque *d'origine* (ex. 128 Go)
    alors que le fichier produit n'en fait plus que quelques-uns -- une
    incohérence que des outils comme `gdisk` détectent et signalent
    (§4.3 : « Disk size is smaller than the main header indicates »),
    même une fois l'en-tête GPT lui-même parfaitement cohérent. Cette
    incohérence existe dans le *fichier image* produit, indépendamment de
    toute carte cible -- rien à voir avec la taille de la carte sur
    laquelle l'image est ensuite restaurée.

    Reconstruit LBA0 à partir de `source` (lisible) plutôt que
    `destination` (ouvert en écriture seule), même principe que
    `_repair_mbr_table_after_truncation` pour le cas MBR pur : le créneau
    portant le type `0xEE` (MBR protecteur GPT, retrouvé via `parse_mbr`
    plutôt que supposé au créneau 0, bien qu'il n'y ait jamais été observé
    ailleurs) voit son compte de secteurs recalculé à partir de la taille
    réelle du fichier produit (fin de la copie tronquée + table
    secondaire, même formule que `estimate_system_backup_size`)."""
    header = boundary.gpt_header
    new_total_sectors = (boundary.end_bytes + _gpt_secondary_table_size(header)) // SECTOR_SIZE
    new_sector_count = min(new_total_sectors - 1, 0xFFFFFFFF)

    source.seek(0)
    first_sector = bytearray(source.read(SECTOR_SIZE))
    mbr_partitions = parse_mbr(bytes(first_sector))
    protective = next((p for p in mbr_partitions if p.partition_type == GPT_PROTECTIVE_TYPE), None)
    if protective is not None:
        offset = PARTITION_TABLE_OFFSET + protective.index * PARTITION_ENTRY_SIZE + 12
        first_sector[offset : offset + 4] = new_sector_count.to_bytes(4, "little")

    end_of_file = destination.tell()
    destination.seek(0)
    destination.write(bytes(first_sector))
    destination.seek(end_of_file)


def _repair_mbr_table_after_truncation(source, destination, boundary: SystemBoundary) -> None:
    """Appelé juste après avoir tronqué la copie MBR à `boundary.
    end_bytes` -- met à zéro, dans le premier secteur de l'image produite,
    les créneaux de la partition de jeux (et de toute partition après
    elle) retirés de l'image (§ point critique de module). Reconstruit le
    secteur à partir de `source` (lisible) plutôt que de relire
    `destination` (ouvert en écriture seule) : les deux ont le même
    premier secteur à ce stade, `copy_range` venant de le copier tel
    quel. Repositionne `destination` là où `copy_range` l'avait laissé."""
    if not boundary.removed_mbr_slot_indices:
        return
    source.seek(0)
    first_sector = bytearray(source.read(SECTOR_SIZE))
    for slot_index in boundary.removed_mbr_slot_indices:
        offset = PARTITION_TABLE_OFFSET + slot_index * 16
        first_sector[offset : offset + 16] = bytes(16)

    end_of_file = destination.tell()
    destination.seek(0)
    destination.write(bytes(first_sector))
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
                _repair_protective_mbr_after_truncation(source, destination, boundary)
            else:
                _repair_mbr_table_after_truncation(source, destination, boundary)
            destination.flush()
            os.fsync(destination.fileno())

    if boundary.is_gpt:
        return boundary.end_bytes + _gpt_secondary_table_size(boundary.gpt_header)
    return boundary.end_bytes
