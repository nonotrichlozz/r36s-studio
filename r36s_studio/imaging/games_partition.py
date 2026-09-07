"""Recrée la partition de jeux après restauration d'une sauvegarde
« système sans les jeux » (§4.3, §5 mode assisté).

**Cause trouvée, confirmée sur du vrai matériel** : `imaging/system_
backup.py::backup_system_only` retire délibérément la partition de jeux de
la table (primaire *et* secondaire pour GPT) pour ne pas sauvegarder les
jeux -- correct pour la sauvegarde elle-même. Mais côté restauration
(`flash.py::flash_device`), rien ne recrée cette partition : l'image
restaurée occupe le début du disque (ex. 11,5 Go), le reste de la carte
(ex. une vingtaine de Go sur une carte de 32 Go) reste non partitionné.
L'hypothèse « la console recrée la partition de jeux au premier démarrage »
est infirmée par un test réel -- pas fiable selon les firmwares. Ce module
comble ce trou : après un flash réussi d'une image système-seule, il ajoute
une nouvelle entrée de partition occupant tout l'espace libre restant et la
formate (exFAT par défaut -- l'EASYROMS de la carte source était en exFAT
sur le matériel de test, §4.4).

Opération symétrique de la réparation de table après troncature
(`system_backup.py::_rewrite_gpt_tables_after_truncation`/`_repair_mbr_
table_after_truncation`), mais dans l'autre sens : au lieu de rétrécir la
table pour retirer une partition, on l'étend pour en ajouter une qui
occupe tout l'espace restant jusqu'à la fin réelle du périphérique de
destination (généralement plus grand que l'image source, §5 pré-vol n°2 --
sinon rien à ajouter). Comme pour la réparation de table, GPT et MBR
suivent une logique différente :

- **GPT** : contrairement à la réparation après troncature (qui déplace la
  table secondaire vers une position plus proche du début), ici la table
  secondaire doit être déplacée vers la toute fin du périphérique réel
  (plus grand que l'image restaurée) -- la primaire (en-tête + entrées)
  reste à sa position d'origine (LBA1/LBA2), seuls `LastUsableLBA` et
  `AlternateLBA` de l'en-tête primaire changent. Le MBR protecteur (LBA0)
  est également corrigé pour refléter la taille réelle du périphérique de
  destination, comme `_repair_protective_mbr_after_truncation` le fait déjà
  pour le fichier image produit par la sauvegarde -- sans quoi le même
  symptôme (« Disk size is smaller than the main header indicates ») se
  reproduirait après restauration.
- **MBR** : ajoute une entrée dans le premier créneau libre (0-3) plutôt que
  d'en retirer une -- pas de table secondaire ni de CRC à recalculer.

**Non confirmé sur du vrai matériel au moment d'écrire ce module** (aucune
carte physique disponible ici) : la logique de calcul et de réécriture de
table est testée bout en bout (reparsing indépendant, comme `test_imaging_
system_backup.py`), mais le comportement réel du système d'exploitation
après cette écriture -- reconnaissance de la nouvelle partition sans
éjection/réinsertion physique, délai de reprobe -- reste à vérifier au
premier test en conditions réelles. `create_games_partition` (raw, testée)
et `format_games_partition` (appels OS natifs, non exécutables ici) sont
donc volontairement séparées : la première est solide, la seconde est la
plus susceptible de demander un ajustement une fois testée."""

from __future__ import annotations

import os
import platform
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from r36s_studio.devices import Device
from r36s_studio.partitions.locate import PartitionInfo, list_partitions

from .gpt import (
    GptHeader,
    GptPartitionEntry,
    build_gpt_entries,
    build_gpt_header,
    parse_gpt_entries,
    parse_gpt_header,
)
from .mbr import (
    GPT_PROTECTIVE_TYPE,
    PARTITION_ENTRY_SIZE,
    PARTITION_TABLE_OFFSET,
    SECTOR_SIZE,
    MbrPartition,
    is_gpt_protective,
    parse_mbr,
)
from .write_target import prepared_write_target

GAMES_PARTITION_LABEL = "EASYROMS"

# GUID de type "Microsoft Basic Data" -- celui déjà relevé sur une vraie
# carte R36S pour la partition EASYROMS, y compris sur un schéma GPT/EFI
# (§4.4 : « son type de partition est « Microsoft Basic Data » »).
MICROSOFT_BASIC_DATA_TYPE_GUID = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"

# Type de partition MBR historiquement utilisé par Windows pour NTFS/exFAT
# (partagé entre les deux, contrairement à FAT qui a ses propres types
# 0x0B/0x0C/0x0E) -- cohérent avec le choix exFAT ci-dessous.
MBR_NTFS_EXFAT_PARTITION_TYPE = 0x07

# Alignement standard (1 Mio, 2048 secteurs de 512 octets) -- celui déjà
# utilisé par tous les outils de partitionnement modernes (parted, diskutil,
# Windows), pour de meilleures performances sur carte SD (alignement sur la
# taille d'effacement de la flash sous-jacente).
ALIGNMENT_SECTORS = 2048

# En dessous de cette taille, créer une partition de jeux n'a pas de sens
# (ne resterait de la place pour quasiment aucun jeu) -- traité comme
# "pas d'espace disponible" plutôt que de créer une partition inutilisable.
MIN_GAMES_PARTITION_BYTES = 64 * 1024 * 1024

# Seuil métier (§4.3), distinct du minimum technique ci-dessus : en dessous
# de 1 Go, la décision automatique post-flash (`create_and_format_games_
# partition_if_worthwhile`) ne tente même pas de créer une partition --
# techniquement viable (au-dessus de `MIN_GAMES_PARTITION_BYTES`) ne veut
# pas dire que ça vaille la peine d'en proposer une à l'utilisateur.
GAMES_PARTITION_WORTHWHILE_BYTES = 1 * 1024 * 1024 * 1024

PARTITION_WAIT_SECONDS = 15.0
PARTITION_POLL_INTERVAL = 0.5


class NoFreeSpaceForGamesPartition(Exception):
    """La carte de destination n'a pas (ou plus assez de) place libre après
    la dernière partition système -- typiquement une carte de taille trop
    proche de celle de l'image restaurée (§5 pré-vol n°2 : la destination
    doit déjà être au moins aussi grande que l'image, mais « au moins aussi
    grande » n'implique pas qu'il reste de la place utile pour des jeux)."""


class NoFreeMbrSlot(Exception):
    """Les 4 créneaux de la table MBR primaire sont déjà occupés -- aucune
    partition étendue n'est gérée par ce projet (§4.3), donc rien où ajouter
    la partition de jeux. Jamais rencontré sur une carte R36S réelle (3
    partitions au plus), gardé comme garde-fou plutôt que supposé
    impossible."""


class GamesPartitionNotFoundAfterCreation(Exception):
    """La nouvelle partition n'est pas apparue dans `list_partitions` avant
    `PARTITION_WAIT_SECONDS` -- l'OS n'a probablement pas encore repéré le
    changement de table de partitions (§ docstring de module, point non
    confirmé sur du vrai matériel)."""


@dataclass
class GamesPartitionPlan:
    start_lba: int
    end_lba: int  # inclusif
    is_gpt: bool
    mbr_slot_index: Optional[int] = None  # renseigné seulement si `not is_gpt`

    @property
    def size_bytes(self) -> int:
        return (self.end_lba - self.start_lba + 1) * SECTOR_SIZE


@dataclass
class GamesPartitionResult:
    start_bytes: int
    size_bytes: int
    is_gpt: bool


def _align_up(lba: int, alignment: int) -> int:
    return -(-lba // alignment) * alignment


def _guid_bytes(guid_str: str) -> bytes:
    """Représentation sur disque (mixte little/big-endian, spec UEFI) d'un
    GUID -- `uuid.UUID.bytes_le` applique déjà exactement cette disposition
    (inverse l'ordre des trois premiers groupes, garde les deux derniers
    tels quels), pas besoin de la reconstruire à la main."""
    return uuid.UUID(guid_str).bytes_le


def _random_guid_bytes() -> bytes:
    return uuid.uuid4().bytes_le


def _gpt_secondary_reserved_sectors(header: GptHeader) -> int:
    entries_size = header.num_entries * header.entry_size
    entries_size_sectors = -(-entries_size // SECTOR_SIZE)
    return entries_size_sectors + 1  # + en-tête secondaire


def plan_games_partition_gpt(header: GptHeader, entries: List[GptPartitionEntry], total_sectors: int) -> GamesPartitionPlan:
    """Calcule l'étendue de la nouvelle partition sur un disque GPT --
    depuis la fin de la dernière partition existante (alignée) jusqu'à la
    fin réelle du disque, table secondaire réservée (§ docstring de
    module). Lève `NoFreeSpaceForGamesPartition` si l'espace restant est
    absent ou trop petit (`MIN_GAMES_PARTITION_BYTES`)."""
    last_end_lba = max((e.end_lba for e in entries), default=header.first_usable_lba - 1)
    start_lba = _align_up(last_end_lba + 1, ALIGNMENT_SECTORS)
    reserved = _gpt_secondary_reserved_sectors(header)
    end_lba = total_sectors - 1 - reserved
    if end_lba <= start_lba:
        raise NoFreeSpaceForGamesPartition(
            "Aucun espace libre après la dernière partition système sur cette carte."
        )
    plan = GamesPartitionPlan(start_lba=start_lba, end_lba=end_lba, is_gpt=True)
    if plan.size_bytes < MIN_GAMES_PARTITION_BYTES:
        raise NoFreeSpaceForGamesPartition(
            f"Espace libre trop petit pour une partition de jeux ({plan.size_bytes} octets)."
        )
    return plan


def plan_games_partition_mbr(partitions: List[MbrPartition], total_sectors: int) -> GamesPartitionPlan:
    """Symétrique de `plan_games_partition_gpt` pour un schéma MBR pur --
    pas de table secondaire à réserver, mais un créneau libre (0-3) à
    trouver dans la table primaire. Lève `NoFreeMbrSlot` si les 4 créneaux
    sont déjà occupés, `NoFreeSpaceForGamesPartition` si l'espace restant
    est absent ou trop petit."""
    last_end_lba = max((p.start_lba + p.sector_count for p in partitions), default=ALIGNMENT_SECTORS)
    start_lba = _align_up(last_end_lba, ALIGNMENT_SECTORS)
    end_lba = total_sectors - 1
    if end_lba <= start_lba:
        raise NoFreeSpaceForGamesPartition(
            "Aucun espace libre après la dernière partition système sur cette carte."
        )
    used_slots = {p.index for p in partitions}
    free_slot = next((i for i in range(4) if i not in used_slots), None)
    if free_slot is None:
        raise NoFreeMbrSlot("Les 4 créneaux de la table MBR sont déjà occupés.")
    plan = GamesPartitionPlan(start_lba=start_lba, end_lba=end_lba, is_gpt=False, mbr_slot_index=free_slot)
    if plan.size_bytes < MIN_GAMES_PARTITION_BYTES:
        raise NoFreeSpaceForGamesPartition(
            f"Espace libre trop petit pour une partition de jeux ({plan.size_bytes} octets)."
        )
    return plan


def _build_new_gpt_entry(plan: GamesPartitionPlan, label: str) -> GptPartitionEntry:
    return GptPartitionEntry(
        type_guid=_guid_bytes(MICROSOFT_BASIC_DATA_TYPE_GUID),
        unique_guid=_random_guid_bytes(),
        start_lba=plan.start_lba,
        end_lba=plan.end_lba,
        attributes=0,
        name=label.encode("utf-16-le"),
    )


@dataclass
class GptRewrite:
    protective_mbr_sector: bytes
    primary_header: bytes
    primary_entries: bytes
    secondary_entries_lba: int
    secondary_entries: bytes
    secondary_header_lba: int
    secondary_header: bytes


def rewrite_gpt_with_games_partition(
    first_sector: bytes,
    header: GptHeader,
    entries: List[GptPartitionEntry],
    plan: GamesPartitionPlan,
    total_sectors: int,
    label: str = GAMES_PARTITION_LABEL,
) -> GptRewrite:
    """Construit tout ce qu'il faut réécrire sur le périphérique de
    destination pour ajouter la partition de jeux à une table GPT existante
    -- `first_sector` (LBA0, MBR protecteur) tel que lu sur le périphérique
    *avant* modification, réparé ici pour refléter `total_sectors` (§
    docstring de module, même raison que `_repair_protective_mbr_after_
    truncation` côté sauvegarde -- sauf que la taille change ici dans
    l'autre sens, plus grande, pas plus petite)."""
    new_entry = _build_new_gpt_entry(plan, label)
    kept_entries = list(entries) + [new_entry]
    entries_bytes = build_gpt_entries(kept_entries, num_entries=header.num_entries, entry_size=header.entry_size)
    entries_size_sectors = -(-len(entries_bytes) // SECTOR_SIZE)
    entries_bytes_padded = entries_bytes.ljust(entries_size_sectors * SECTOR_SIZE, b"\x00")

    secondary_header_lba = total_sectors - 1
    secondary_entries_lba = secondary_header_lba - entries_size_sectors

    secondary_header_bytes = build_gpt_header(
        revision=header.revision,
        my_lba=secondary_header_lba,
        alternate_lba=1,
        first_usable_lba=header.first_usable_lba,
        last_usable_lba=plan.end_lba,
        disk_guid=header.disk_guid,
        partition_entry_lba=secondary_entries_lba,
        num_entries=header.num_entries,
        entry_size=header.entry_size,
        entries_bytes=entries_bytes,
    )
    primary_header_bytes = build_gpt_header(
        revision=header.revision,
        my_lba=1,
        alternate_lba=secondary_header_lba,
        first_usable_lba=header.first_usable_lba,
        last_usable_lba=plan.end_lba,
        disk_guid=header.disk_guid,
        partition_entry_lba=header.partition_entry_lba,
        num_entries=header.num_entries,
        entry_size=header.entry_size,
        entries_bytes=entries_bytes,
    )

    protective_mbr = bytearray(first_sector)
    mbr_partitions = parse_mbr(bytes(protective_mbr))
    protective = next((p for p in mbr_partitions if p.partition_type == GPT_PROTECTIVE_TYPE), None)
    if protective is not None:
        new_sector_count = min(total_sectors - 1, 0xFFFFFFFF)
        offset = PARTITION_TABLE_OFFSET + protective.index * PARTITION_ENTRY_SIZE + 12
        protective_mbr[offset : offset + 4] = new_sector_count.to_bytes(4, "little")

    return GptRewrite(
        protective_mbr_sector=bytes(protective_mbr),
        primary_header=primary_header_bytes,
        primary_entries=entries_bytes_padded,
        secondary_entries_lba=secondary_entries_lba,
        secondary_entries=entries_bytes_padded,
        secondary_header_lba=secondary_header_lba,
        secondary_header=secondary_header_bytes,
    )


def rewrite_mbr_with_games_partition(first_sector: bytes, plan: GamesPartitionPlan) -> bytes:
    """Ajoute l'entrée de la partition de jeux dans le créneau libre
    (`plan.mbr_slot_index`) du premier secteur -- pas de CRC ni de table
    secondaire à recalculer côté MBR."""
    sector = bytearray(first_sector)
    entry = bytearray(PARTITION_ENTRY_SIZE)
    entry[4] = MBR_NTFS_EXFAT_PARTITION_TYPE
    entry[8:12] = plan.start_lba.to_bytes(4, "little")
    sector_count = plan.end_lba - plan.start_lba + 1
    entry[12:16] = sector_count.to_bytes(4, "little")
    offset = PARTITION_TABLE_OFFSET + plan.mbr_slot_index * PARTITION_ENTRY_SIZE
    sector[offset : offset + PARTITION_ENTRY_SIZE] = bytes(entry)
    return bytes(sector)


def create_games_partition(device: Device, label: str = GAMES_PARTITION_LABEL) -> GamesPartitionResult:
    """Ajoute une partition de jeux occupant tout l'espace libre restant sur
    `device`, quel que soit son schéma (MBR ou GPT, détecté comme dans
    `system_backup.py`). Écrit directement sur le périphérique brut (§4.3,
    même précaution de démontage/verrouillage que `flash_device` via
    `prepared_write_target`). Lève `NoFreeSpaceForGamesPartition`/
    `NoFreeMbrSlot` si aucune partition ne peut être créée."""
    total_sectors = device.size_bytes // SECTOR_SIZE
    with prepared_write_target(device) as raw_path:
        with open(raw_path, "r+b") as f:
            first_sector = f.read(SECTOR_SIZE)
            mbr_partitions = parse_mbr(first_sector)

            if not is_gpt_protective(mbr_partitions):
                plan = plan_games_partition_mbr(mbr_partitions, total_sectors)
                new_sector = rewrite_mbr_with_games_partition(first_sector, plan)
                f.seek(0)
                f.write(new_sector)
                f.flush()
                os.fsync(f.fileno())
                return GamesPartitionResult(
                    start_bytes=plan.start_lba * SECTOR_SIZE, size_bytes=plan.size_bytes, is_gpt=False
                )

            header_sector = f.read(SECTOR_SIZE)
            header = parse_gpt_header(header_sector)
            f.seek(header.partition_entry_lba * SECTOR_SIZE)
            entries_bytes = f.read(header.num_entries * header.entry_size)
            entries = parse_gpt_entries(entries_bytes, header)

            plan = plan_games_partition_gpt(header, entries, total_sectors)
            rewritten = rewrite_gpt_with_games_partition(first_sector, header, entries, plan, total_sectors, label)

            f.seek(0)
            f.write(rewritten.protective_mbr_sector)
            f.seek(1 * SECTOR_SIZE)
            f.write(rewritten.primary_header)
            f.seek(header.partition_entry_lba * SECTOR_SIZE)
            f.write(rewritten.primary_entries)
            f.seek(rewritten.secondary_entries_lba * SECTOR_SIZE)
            f.write(rewritten.secondary_entries)
            f.seek(rewritten.secondary_header_lba * SECTOR_SIZE)
            f.write(rewritten.secondary_header)
            f.flush()
            os.fsync(f.fileno())
            return GamesPartitionResult(start_bytes=plan.start_lba * SECTOR_SIZE, size_bytes=plan.size_bytes, is_gpt=True)


def _wait_for_new_partition(
    device_path: str,
    known_paths: set,
    timeout: float = PARTITION_WAIT_SECONDS,
    poll_interval: float = PARTITION_POLL_INTERVAL,
) -> PartitionInfo:
    """Attend qu'une partition absente de `known_paths` (relevées juste
    avant l'écriture de la nouvelle table) apparaisse dans `list_partitions`
    -- non confirmé sur du vrai matériel (§ docstring de module) : le délai
    exact que met chaque OS à reprendre en compte une table de partitions
    modifiée sous lui n'a pas pu être mesuré ici."""
    deadline = time.monotonic() + timeout
    while True:
        partitions = list_partitions(device_path)
        for partition in partitions:
            if partition.device_path and partition.device_path not in known_paths:
                return partition
        if time.monotonic() >= deadline:
            raise GamesPartitionNotFoundAfterCreation(
                f"La nouvelle partition n'est jamais apparue sur {device_path}."
            )
        time.sleep(poll_interval)


def _format_macos(partition_path: str, label: str, filesystem: str) -> None:
    fs_name = "ExFAT" if filesystem == "exfat" else "MS-DOS FAT32"
    subprocess.run(["diskutil", "eraseVolume", fs_name, label, partition_path], check=True, capture_output=True)


def _format_linux(partition_path: str, label: str, filesystem: str) -> None:
    if filesystem == "exfat":
        subprocess.run(["mkfs.exfat", "-n", label, partition_path], check=True, capture_output=True)
    else:
        subprocess.run(["mkfs.vfat", "-F", "32", "-n", label, partition_path], check=True, capture_output=True)


def _format_windows(device_path: str, label: str, filesystem: str) -> None:
    """`partition_path` est ici le disque (`\\\\.\\PhysicalDriveN`), pas la
    partition elle-même -- contrairement à macOS/Linux, la partition
    nouvellement créée n'a pas forcément de lettre de lecteur ni de volume
    reconnu par un chemin stable avant ce formatage ; `Get-Partition |
    Get-Volume | Format-Volume` la retrouve par position (dernière
    partition du disque, celle qu'on vient de créer) plutôt que par un
    chemin qu'il faudrait d'abord obtenir séparément. `Get-Volume` reconnaît
    déjà un volume "RAW" sur une partition fraîchement créée, non formatée
    (confirmé ailleurs dans ce projet pour une partition ext4 non reconnue,
    §4.4) -- pas besoin qu'un système de fichiers existe déjà pour la
    trouver."""
    import re

    match = re.search(r"PhysicalDrive(\d+)", device_path)
    if not match:
        raise ValueError(f"chemin de périphérique Windows invalide : {device_path}")
    disk_number = match.group(1)
    fs_name = "exFAT" if filesystem == "exfat" else "FAT32"
    command = (
        f"Get-Partition -DiskNumber {disk_number} | Sort-Object PartitionNumber | "
        "Select-Object -Last 1 | Get-Volume | "
        f"Format-Volume -FileSystem {fs_name} -NewFileSystemLabel '{label}' -Confirm:$false"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", command], check=True, capture_output=True)


def format_games_partition(
    device: Device,
    label: str = GAMES_PARTITION_LABEL,
    filesystem: str = "exfat",
    known_partition_paths: Optional[set] = None,
) -> None:
    """Formate nativement la partition de jeux fraîchement créée par
    `create_games_partition` -- `filesystem` : `"exfat"` par défaut (système
    de fichiers observé sur la carte source, §4.4) ou `"fat32"` si
    explicitement demandé par l'appelant. ⚠️ Contrairement à ce qu'une
    version antérieure de cette docstring affirmait, il n'existe **aucun
    repli automatique** vers `"fat32"` quand `mkfs.exfat` est absent
    (Linux) -- `_format_linux` ne fait que choisir l'outil selon la valeur
    déjà reçue, rien ne détecte sa disponibilité ni ne change `filesystem`
    en conséquence. Sur une machine sans `mkfs.exfat` (ex. une distribution
    Linux minimale), le formatage échoue avec `FileNotFoundError`/
    `CalledProcessError` -- rattrapé en best-effort par l'appelant
    (`create_and_format_games_partition_if_worthwhile`/`__main__.py::
    cmd_flash`, §4.3 : jamais un échec du flash déjà réussi), pas par un
    changement silencieux de système de fichiers. `known_partition_paths` : les
    chemins de partitions déjà connus *avant* `create_games_partition`
    (relevés par l'appelant) -- sert à distinguer la nouvelle partition des
    partitions système sur macOS/Linux ; ignoré sous Windows, qui la
    retrouve par position (`_format_windows`)."""
    system = platform.system()
    if system == "Windows":
        _format_windows(device.path, label, filesystem)
        return

    known = known_partition_paths or set()
    partition = _wait_for_new_partition(device.path, known)
    if system == "Darwin":
        _format_macos(partition.device_path, label, filesystem)
    elif system == "Linux":
        _format_linux(partition.device_path, label, filesystem)
    else:
        raise NotImplementedError(f"OS non supporté pour le formatage : {system}")


def create_and_format_games_partition(
    device: Device, label: str = GAMES_PARTITION_LABEL, filesystem: str = "exfat"
) -> GamesPartitionResult:
    """Combine `create_games_partition` et `format_games_partition` -- lève
    `NoFreeSpaceForGamesPartition`/`NoFreeMbrSlot` si aucune partition ne
    peut être créée (voir plutôt `create_and_format_games_partition_if_
    worthwhile` pour la décision automatique post-flash, §4.3, qui tolère
    ces deux cas sans jamais lever)."""
    known_paths = {p.device_path for p in list_partitions(device.path) if p.device_path}
    result = create_games_partition(device, label)
    format_games_partition(device, label, filesystem, known_partition_paths=known_paths)
    return result


def _peek_free_games_partition_bytes(device: Device) -> int:
    """Calcule l'espace qui serait disponible pour une nouvelle partition
    de jeux, en lecture seule -- sert uniquement à décider si ça vaut la
    peine de tenter la création réelle (verrouillage + écriture, plus
    coûteuse et plus risquée, §4.3), jamais à la création elle-même.

    Contrairement à `create_games_partition`, n'utilise pas `prepared_
    write_target` : lire quelques secteurs d'un périphérique brut déjà
    monté fonctionne nativement sur les trois OS (même principe que
    `imaging/source.py::prepared_source`, qui ne démonte que sur macOS et
    seulement pour la lecture d'une source de sauvegarde) -- c'est
    uniquement *l'écriture* qui exige le verrouillage/démontage complet
    (§4.3). Repose ce même calcul deux fois (ici puis dans `create_games_
    partition`) plutôt que de le partager sur une seule ouverture : cette
    fonction ne doit jamais retarder ni risquer le verrouillage réel, qui
    reste par ailleurs sujet à des refus transitoires sur Windows (§4.3,
    `FSCTL_LOCK_VOLUME`).

    Retourne 0 pour toute condition qui empêcherait la création (table
    illisible, aucun espace, créneau MBR plein, périphérique inaccessible)
    plutôt que de lever -- ce calcul ne doit jamais faire échouer un appelant
    qui ne fait que décider s'il vaut la peine d'essayer."""
    try:
        total_sectors = device.size_bytes // SECTOR_SIZE
        with open(device.path, "rb") as f:
            first_sector = f.read(SECTOR_SIZE)
            mbr_partitions = parse_mbr(first_sector)
            if not is_gpt_protective(mbr_partitions):
                plan = plan_games_partition_mbr(mbr_partitions, total_sectors)
            else:
                header_sector = f.read(SECTOR_SIZE)
                header = parse_gpt_header(header_sector)
                f.seek(header.partition_entry_lba * SECTOR_SIZE)
                entries_bytes = f.read(header.num_entries * header.entry_size)
                entries = parse_gpt_entries(entries_bytes, header)
                plan = plan_games_partition_gpt(header, entries, total_sectors)
    except (OSError, NoFreeSpaceForGamesPartition, NoFreeMbrSlot):
        return 0
    return plan.size_bytes


def create_and_format_games_partition_if_worthwhile(
    device: Device,
    label: str = GAMES_PARTITION_LABEL,
    filesystem: str = "exfat",
    min_worthwhile_bytes: int = GAMES_PARTITION_WORTHWHILE_BYTES,
) -> Optional[GamesPartitionResult]:
    """Décision entièrement automatique (§4.3, remplace la case à cocher du
    mode expert et la comparaison de chemin du parcours guidé, toutes deux
    retirées) : l'app dispose de toute l'information nécessaire (taille de
    l'image déjà écrite, taille réelle de la carte) pour décider seule s'il
    reste assez d'espace libre pour une partition de jeux -- l'utilisateur
    ne peut pas le savoir lui-même, surtout avec un firmware qu'il découvre
    (§1 : « le chemin par défaut doit fonctionner sans que l'utilisateur
    ait à comprendre ce qu'il fait »).

    Retourne `None` sans rien écrire ni lever si l'espace disponible
    (`_peek_free_games_partition_bytes`) n'atteint pas `min_worthwhile_
    bytes` (1 Go par défaut, `GAMES_PARTITION_WORTHWHILE_BYTES` -- un seuil
    métier, distinct du minimum technique `MIN_GAMES_PARTITION_BYTES`),
    plutôt que de créer une partition de jeux minuscule que personne ne
    demande. `NoFreeSpaceForGamesPartition`/`NoFreeMbrSlot` restent
    tolérées même après ce contrôle (rare : l'espace a pu changer entre
    l'estimation en lecture seule et la tentative réelle, ou le créneau MBR
    est plein alors que l'espace suffisait) -- ce point d'entrée ne lève
    donc jamais pour un simple manque de place, seulement pour une vraie
    erreur d'écriture/formatage (`OSError`, `subprocess.CalledProcessError`,
    `ValueError`), à la charge de l'appelant (`__main__.py::cmd_flash`,
    best-effort, même principe que `--eject-after`)."""
    if _peek_free_games_partition_bytes(device) < min_worthwhile_bytes:
        return None
    try:
        return create_and_format_games_partition(device, label, filesystem)
    except (NoFreeSpaceForGamesPartition, NoFreeMbrSlot):
        return None
