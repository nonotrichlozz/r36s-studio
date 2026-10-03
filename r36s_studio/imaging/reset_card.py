# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""« Remettre la carte à zéro » : après des essais de firmware, une carte
peut rester en trois à cinq partitions illisibles pour un PC -- Windows ne
sait pas la remettre simplement en état de carte de stockage normale
(constaté en usage réel). Efface toute la table de partitions existante
(MBR ou GPT) et recrée une seule partition (exFAT par défaut, ou FAT32 sur
demande explicite -- § `format_reset_partition`, `imaging/fat32.py`, pour
les consoles anciennes qui ne lisent pas l'exFAT) occupant toute la carte.

Réutilise les briques déjà en place plutôt que d'en écrire de nouvelles :
`imaging/write_target.py::prepared_write_target` (verrouillage/démontage
par OS, §4.3, identique à `flash_device`/`create_games_partition`) pour
l'écriture, et `imaging/games_partition.py::format_games_partition` (déjà
multiplateforme : `diskutil eraseVolume` / `mkfs.exfat` / PowerShell
`Format-Volume`) pour le formatage natif -- rien de nouveau à maintenir
par OS pour cette dernière étape.

Différent de `games_partition.py` dans son principe : celui-ci *ajoute*
une partition à une table existante (restauration d'une sauvegarde
système sans les jeux) ; celui-ci *remplace* toute la table par une seule
partition neuve -- la planification (« où commence/finit la partition »)
n'a donc pas besoin de lire de table existante, contrairement à `plan_
games_partition_gpt`/`plan_games_partition_mbr`.

Exposé en deux fonctions distinctes (`erase_partition_table`/`create_
single_partition`) plutôt qu'une seule combinée -- bug corrigé, confirmé
sur du vrai matériel : le formatage échouait *silencieusement* (aucune
partition exFAT créée, carte restée brute) parce que Windows n'avait pas
encore repris en compte la nouvelle table au moment où `format_games_
partition` interrogeait `Get-Partition` (pipeline PowerShell vide, jamais
d'erreur levée -- voir aussi le correctif jumeau dans `games_partition.py
::_format_windows`, qui rend cet échec bruyant au lieu de silencieux).
Séparer les étapes permet à l'appelant (`__main__.py::cmd_reset_card`) de
journaliser et de faire progresser une barre par étape réellement
terminée (§2 n°5 : jamais une progression simulée), et donne un point
précis où insérer le délai de reprise en compte côté Windows."""

from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from r36s_studio.devices import Device
from r36s_studio.winprocess import no_console_kwargs

from .fat32 import Fat32VolumeTooSmall, format_fat32, plan_fat32_layout
from .games_partition import (
    ALIGNMENT_SECTORS,
    MBR_NTFS_EXFAT_PARTITION_TYPE,
    format_games_partition,
)
from .mbr import PARTITION_ENTRY_SIZE, PARTITION_TABLE_OFFSET, SECTOR_SIZE
from .write_target import prepared_write_target

# Type de partition MBR FAT32 LBA -- distinct de `MBR_NTFS_EXFAT_PARTITION_
# TYPE` (0x07, partagé NTFS/exFAT). Purement indicatif une fois la
# partition formatée nativement/à la main (§ `imaging/fat32.py`) -- aucun
# outil de ce projet ne s'en sert pour décider quoi que ce soit, mais un
# octet de type cohérent avec le système de fichiers réellement présent
# évite qu'un outil tiers (gestionnaire de disques, `fdisk -l`...) affiche
# une incohérence.
MBR_FAT32_LBA_PARTITION_TYPE = 0x0C

# Bug corrigé, signalé par un utilisateur (carte de 128 Go pour une
# SF3000HD, voulue en FAT32 -- vraisemblablement pour TreeFrogUI : la
# carte d'origine de cette console est en exFAT et lue par le menu
# d'origine, voir docs/claude/reset-card.md) : `Format-Volume`/`format.exe` (et `diskpart`, qui
# passe par la même API `fmifs.dll`) refusent de formater en FAT32 tout
# volume dépassant 32 Go -- limite artificielle du formateur Windows
# standard, pas du pilote qui *lit* du FAT32 (`fastfat.sys`, voir
# `imaging/fat32.py`). Sur une carte SD R36S typique (64-256 Go), ça rend
# le choix FAT32 impossible en pratique avec l'outil natif -- contourné en
# écrivant nous-mêmes la structure FAT32 (`format_fat32`), jamais en
# refusant silencieusement l'option à l'utilisateur.

# Étiquette simple par défaut (§ demande explicite : « permettre de choisir
# l'étiquette du volume, avec une valeur par défaut simple ») -- ni le nom
# d'une console ni un jargon technique, juste ce qu'un PC affichera pour
# une carte SD ordinaire.
DEFAULT_RESET_LABEL = "SDCARD"

# Efface aussi ce nombre de secteurs en fin de disque avant d'écrire la
# nouvelle table -- une éventuelle table GPT secondaire vit en toute fin
# de disque (§4.3, `imaging/system_backup.py`) ; l'effacer ici évite qu'un
# outil qui la retrouverait malgré un MBR neuf en tête (LBA0) ne continue
# de rapporter l'ancien schéma. Même taille que la marge déjà réservée
# ailleurs pour une table GPT secondaire (`ALIGNMENT_SECTORS`, 1 Mio) --
# largement suffisant, une table GPT réelle (en-tête + 128 entrées de
# 128 octets) tenant dans 33 secteurs.
_WIPE_EDGE_SECTORS = ALIGNMENT_SECTORS

# Bug corrigé, confirmé sur du vrai matériel : Windows n'avait pas encore
# repris en compte le MBR tout juste écrit au moment où le formatage
# interrogeait `Get-Partition` -- ce court délai, après le rafraîchissement
# explicite (`IOCTL_DISK_UPDATE_PROPERTIES`, déjà utilisé par `write_
# target.py` pour ce même disque), laisse à Windows le temps de terminer
# cette reprise en compte avant l'étape suivante. `_format_windows`
# (games_partition.py) réessaie en plus plusieurs fois de son côté --
# défense en profondeur, ce délai n'a pas besoin d'être garanti suffisant
# à lui seul.
_WINDOWS_TABLE_REFRESH_DELAY_SECONDS = 1.0


class CardTooSmallForReset(Exception):
    """La carte est trop petite pour qu'une partition exFAT utile tienne
    entre les deux zones effacées en tête et en fin de disque -- une carte
    SD réelle en fait au minimum plusieurs centaines de Mio, ce cas ne
    devrait jamais se produire en pratique (garde-fou, pas un cas attendu)."""


@dataclass
class ResetCardPlan:
    start_lba: int
    end_lba: int  # inclusif

    @property
    def size_bytes(self) -> int:
        return (self.end_lba - self.start_lba + 1) * SECTOR_SIZE


def plan_full_disk_partition(total_sectors: int) -> ResetCardPlan:
    """Une seule partition, alignée (`ALIGNMENT_SECTORS`, même convention
    que `games_partition.py`), occupant tout le disque entre les deux
    zones effacées (§ docstring de module). Lève `CardTooSmallForReset` si
    ça ne laisse pas de place."""
    start_lba = ALIGNMENT_SECTORS
    end_lba = total_sectors - 1 - _WIPE_EDGE_SECTORS
    if end_lba <= start_lba:
        raise CardTooSmallForReset(f"Carte trop petite pour la remettre à zéro ({total_sectors} secteurs).")
    return ResetCardPlan(start_lba=start_lba, end_lba=end_lba)


def check_fat32_feasible(device: Device) -> None:
    """Vérifie, sans rien écrire, que le FAT32 tient sur cette carte --
    appelée avant toute écriture (`__main__.py::cmd_reset_card`, `gui/
    main_window.py`), jamais seulement à l'étape de formatage. Demande
    explicite : « si le FAT32 s'avère impossible sur une taille donnée, le
    dire clairement avant de lancer l'opération, jamais après » --
    l'effacement de la table (étape 1/4) est irréversible, donc découvrir
    l'impossibilité seulement à l'étape de formatage (3/4) serait déjà
    trop tard, la carte ayant entre-temps perdu son ancienne table sans
    qu'aucune nouvelle ne l'ait encore remplacée utilement.

    En pratique, ne devrait jamais se déclencher sur une vraie carte SD
    (le seuil FAT32, `Fat32VolumeTooSmall`, se situe autour de quelques
    dizaines de Mio) -- garde-fou par principe, pas un cas attendu. Ne
    concerne jamais la limite Windows de 32 Go pour `Format-Volume`/
    `format.exe`/`diskpart` : celle-ci est contournée par un formateur
    FAT32 écrit à la main (`imaging/fat32.py::format_fat32`), qui n'a pas
    cette limite, quelle que soit la taille de la carte. Lève `CardTooSmallForReset`
    (carte trop petite pour la remise à zéro elle-même, sans rapport avec
    le système de fichiers choisi) ou `Fat32VolumeTooSmall` -- jamais
    silencieux."""
    total_sectors = device.size_bytes // SECTOR_SIZE
    plan = plan_full_disk_partition(total_sectors)
    partition_sectors = plan.end_lba - plan.start_lba + 1
    plan_fat32_layout(partition_sectors, plan.size_bytes)


def build_full_disk_mbr_sector(plan: ResetCardPlan, filesystem: str = "exfat") -> bytes:
    """Construit un secteur MBR neuf (tous les autres octets à zéro,
    aucun code de démarrage) avec une seule entrée de partition -- à la
    différence de `rewrite_mbr_with_games_partition` (`games_partition.py`)
    qui préserve les entrées déjà présentes, ici on repart d'un secteur
    entièrement vide : toute la table précédente est censée disparaître,
    pas seulement gagner une entrée de plus.

    `filesystem` ne choisit que l'octet de type de partition -- purement
    indicatif (§ `MBR_FAT32_LBA_PARTITION_TYPE`), le formatage réel a lieu
    séparément (`format_reset_partition`)."""
    sector = bytearray(SECTOR_SIZE)
    entry = bytearray(PARTITION_ENTRY_SIZE)
    entry[4] = MBR_FAT32_LBA_PARTITION_TYPE if filesystem == "fat32" else MBR_NTFS_EXFAT_PARTITION_TYPE
    entry[8:12] = plan.start_lba.to_bytes(4, "little")
    sector_count = plan.end_lba - plan.start_lba + 1
    entry[12:16] = sector_count.to_bytes(4, "little")
    sector[PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + PARTITION_ENTRY_SIZE] = bytes(entry)
    sector[510:512] = b"\x55\xaa"
    return bytes(sector)


def erase_partition_table(device: Device) -> None:
    """Étape 1/4 (§4.3 bis) : efface (zéros) une marge en tête *et* en fin
    de disque -- une éventuelle signature GPT (« EFI PART », LBA1) ou une
    table secondaire en fin de disque ne doit pas pouvoir resurgir une
    fois le nouveau MBR écrit par `create_single_partition` (étape
    suivante) par-dessus le seul LBA0."""
    total_sectors = device.size_bytes // SECTOR_SIZE
    zero_edge = b"\x00" * (_WIPE_EDGE_SECTORS * SECTOR_SIZE)
    with prepared_write_target(device) as raw_path:
        with open(raw_path, "r+b") as f:
            f.write(zero_edge)
            f.seek((total_sectors - _WIPE_EDGE_SECTORS) * SECTOR_SIZE)
            f.write(zero_edge)
            f.flush()
            os.fsync(f.fileno())


def create_single_partition(device: Device, filesystem: str = "exfat") -> ResetCardPlan:
    """Étape 2/4 : écrit un MBR neuf (`build_full_disk_mbr_sector`) avec
    une unique partition alignée occupant tout l'espace restant.

    Sur Windows uniquement : `prepared_write_target` rafraîchit déjà la
    vue du disque (`winlock.refresh_disk_properties`, `IOCTL_DISK_UPDATE_
    PROPERTIES`) en quittant son bloc `with` -- mais ce rafraîchissement
    ne garantit pas que Windows ait *terminé* de reprendre en compte la
    nouvelle table au moment où l'appelant interroge `Get-Partition`
    juste après (§ docstring de module, bug confirmé sur du vrai
    matériel : formatage silencieusement sans effet). Cette fonction
    attend donc un court instant supplémentaire avant de rendre la main --
    `_format_windows` (games_partition.py) réessaie en plus plusieurs fois
    de son côté, ce délai n'a donc pas besoin d'être garanti suffisant à
    lui seul."""
    total_sectors = device.size_bytes // SECTOR_SIZE
    plan = plan_full_disk_partition(total_sectors)
    with prepared_write_target(device) as raw_path:
        with open(raw_path, "r+b") as f:
            f.write(build_full_disk_mbr_sector(plan, filesystem))
            f.flush()
            os.fsync(f.fileno())
    if platform.system() == "Windows":
        time.sleep(_WINDOWS_TABLE_REFRESH_DELAY_SECONDS)
    return plan


def _windows_assign_drive_letter_after_raw_format(device_path: str) -> Optional[str]:
    """Après une écriture FAT32 « à la main » (`imaging/fat32.py::
    format_fat32`, jamais `Format-Volume` -- § docstring de module),
    Windows doit encore reprendre en compte le volume et lui attribuer une
    lettre pour qu'il apparaisse dans l'Explorateur -- même réessai/délai
    que `games_partition.py::_format_windows`, mais sans jamais appeler
    `Format-Volume` (déjà fait nous-mêmes, l'étiquette étant déjà posée par
    `format_fat32`). Lève `OSError` si la partition reste introuvable après
    les réessais -- jamais un succès silencieux (§4.4), même principe que
    `_format_windows`."""
    from .games_partition import _WINDOWS_PARTITION_RETRY_COUNT, _WINDOWS_PARTITION_RETRY_DELAY_MS

    match = re.search(r"PhysicalDrive(\d+)", device_path)
    if not match:
        raise ValueError(f"chemin de périphérique Windows invalide : {device_path}")
    disk_number = match.group(1)
    command = (
        "$diskNumber = %s\n"
        "$partition = $null\n"
        "for ($i = 0; $i -lt %d; $i++) {\n"
        "    $partition = Get-Partition -DiskNumber $diskNumber -ErrorAction SilentlyContinue |"
        " Sort-Object PartitionNumber | Select-Object -Last 1\n"
        "    if ($partition) { break }\n"
        "    Start-Sleep -Milliseconds %d\n"
        "}\n"
        "if (-not $partition) {\n"
        "    Write-Error \"Aucune partition trouvee sur le disque $diskNumber apres plusieurs tentatives.\"\n"
        "    exit 1\n"
        "}\n"
        "$partition | Add-PartitionAccessPath -AssignDriveLetter -ErrorAction SilentlyContinue\n"
        "$updated = Get-Partition -DiskNumber $diskNumber -PartitionNumber $partition.PartitionNumber"
        " -ErrorAction SilentlyContinue\n"
        "if ($updated -and $updated.DriveLetter) {\n"
        "    Write-Output \"DRIVE_LETTER=$($updated.DriveLetter)\"\n"
        "}\n"
    ) % (disk_number, _WINDOWS_PARTITION_RETRY_COUNT, _WINDOWS_PARTITION_RETRY_DELAY_MS)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        **no_console_kwargs(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        message = f"Attribution de la lettre de lecteur : échec (code {result.returncode})"
        raise OSError(message + (f" : {detail}" if detail else ""))
    match_letter = re.search(r"^DRIVE_LETTER=(\S)$", result.stdout or "", re.MULTILINE)
    return match_letter.group(1) if match_letter else None


def format_reset_partition(device: Device, plan: ResetCardPlan, label: str, filesystem: str = "exfat") -> Optional[str]:
    """Étape 3/4 : formate nativement la partition créée par `create_
    single_partition`, sauf sur Windows avec `filesystem == "fat32"` --
    `Format-Volume`/`format.exe`/`diskpart` refusent tous de formater en
    FAT32 au-delà de 32 Go (limite du formateur standard, pas du pilote de
    lecture, § docstring de module), ce qui rend ce choix impossible en
    pratique sur une carte SD R36S typique. Contourné en écrivant
    nous-mêmes une structure FAT32 conforme à la spécification directement
    sur le disque physique (`imaging/fat32.py`), puis en demandant
    seulement à Windows de reconnaître le nouveau volume et de lui
    attribuer une lettre (`_windows_assign_drive_letter_after_raw_format`).

    macOS (`diskutil eraseVolume "MS-DOS FAT32"`) et Linux (`mkfs.vfat -F
    32`) n'ont pas cette limite (rapporté comme tel, § `imaging/fat32.py` --
    non vérifié indépendamment ici) : ces deux OS, et Windows en exFAT,
    continuent de passer par `games_partition.format_games_partition`,
    inchangé."""
    if platform.system() == "Windows" and filesystem == "fat32":
        with prepared_write_target(device) as raw_path:
            format_fat32(raw_path, plan.start_lba * SECTOR_SIZE, plan.size_bytes, label)
        return _windows_assign_drive_letter_after_raw_format(device.path)
    return format_games_partition(device, label, filesystem, known_partition_paths=set())


__all__ = [
    "DEFAULT_RESET_LABEL",
    "MBR_FAT32_LBA_PARTITION_TYPE",
    "CardTooSmallForReset",
    "ResetCardPlan",
    "plan_full_disk_partition",
    "check_fat32_feasible",
    "build_full_disk_mbr_sector",
    "erase_partition_table",
    "create_single_partition",
    "format_reset_partition",
]
