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

"""Formateur FAT32 « à la main », écrit directement les structures sur le
disque brut -- réservé au cas où le formateur natif de l'OS ne convient
pas. Cas réel qui motive ce module : sous Windows, `Format-Volume`/
`format.exe` (et `diskpart`, qui appelle la même API `fmifs.dll`) refusent
de formater en FAT32 tout volume dépassant 32 Go -- limite artificielle du
formateur standard de Microsoft, pas du pilote qui *lit* du FAT32
(`fastfat.sys` monte sans problème un FAT32 bien formé de n'importe quelle
taille, jusqu'à la limite protocolaire de 2 To imposée par le champ 32 bits
`BPB_TotSec32`). Une carte SD R36S fait typiquement 64 à 256 Go -- cette
limite rend donc le choix FAT32 impossible en pratique sur ce genre de
carte avec l'outil Windows standard, ce qui a été signalé par un
utilisateur (carte de 128 Go pour une SF3000HD, inutilisable après un
formatage exFAT). Précisé depuis : la SF3000HD elle-même lit l'exFAT (sa
carte d'origine l'est) ; le besoin de FAT32 venait vraisemblablement de
TreeFrogUI -- voir docs/claude/reset-card.md.

macOS (`diskutil eraseVolume "MS-DOS FAT32"`) et Linux (`mkfs.vfat -F 32`)
n'ont pas cette limite -- rapporté comme tel, non vérifié indépendamment
sur du vrai matériel dans ce projet (aucun Mac/machine Linux avec carte SD
disponible au moment d'écrire ce module) -- donc ce module n'est utilisé
que sur Windows (`imaging/reset_card.py::format_reset_partition`) ; les
deux autres OS continuent de passer par `games_partition.format_games_
partition`, inchangé.

Implémente exactement ce que fait un formateur FAT32 tiers qui contourne
cette même limite (ex. `guiformat`/`fat32format` de Ridgecrop, ou Rufus) :
écrire soi-même le secteur de démarrage, le secteur FSInfo, les deux tables
FAT et le répertoire racine, en suivant la spécification Microsoft
« FAT32 File System Specification » (fatgen103, réutilisée par la quasi-
totalité des implémentations FAT32 libres, dont `mkfs.fat`/`mtools`) --
sans dépendre d'aucun outil externe, dans le même esprit que le reste de
ce paquet (`imaging/mbr.py`/`imaging/gpt.py`, déjà construits/reconstruits
à la main plutôt qu'appelés via un outil).

⚠️ **Non vérifié sur du vrai matériel au moment d'écrire ce module** :
couvert par des tests qui reparsent indépendamment la structure produite
(même discipline que `test_imaging_system_backup.py` pour GPT), mais
aucune machine Windows avec droits administrateur et carte SD réelle
n'était disponible dans cet environnement pour confirmer que Windows
monte effectivement le résultat comme un volume FAT32 valide. À tester en
priorité sur la carte de 128 Go ayant motivé ce correctif avant de
considérer le problème définitivement réglé."""

from __future__ import annotations

import os
import random
import struct
from dataclasses import dataclass

SECTOR_SIZE = 512
RESERVED_SECTORS = 32
NUM_FATS = 2
BACKUP_BOOT_SECTOR_LBA = 6

# En dessous de ce nombre de clusters, la spécification Microsoft exige du
# FAT12/FAT16 plutôt que du FAT32 (fatgen103) -- ne devrait jamais se
# produire sur une carte SD réelle (au minimum plusieurs centaines de Mio),
# gardé comme garde-fou plutôt que supposé impossible (même principe que
# `reset_card.CardTooSmallForReset`).
MIN_FAT32_CLUSTERS = 65525

# Table de taille de cluster par défaut, reprise de celle utilisée par le
# formateur Windows standard pour les volumes jusqu'à 32 Go (§ docstring de
# module) -- au-delà, ce même formateur refuse simplement le FAT32 plutôt
# que de proposer une taille de cluster plus grande ; ce module reprend la
# dernière valeur de la table (32 Kio, 64 secteurs) pour tout volume plus
# grand, comme le font les formateurs tiers cités ci-dessus.
_CLUSTER_SIZE_TABLE = [
    (64 * 1024 * 1024, 1),
    (128 * 1024 * 1024, 2),
    (256 * 1024 * 1024, 4),
    (8 * 1024 * 1024 * 1024, 8),
    (16 * 1024 * 1024 * 1024, 16),
    (32 * 1024 * 1024 * 1024, 32),
]
_LARGE_VOLUME_SECTORS_PER_CLUSTER = 64


class Fat32VolumeTooSmall(Exception):
    """Le volume est trop petit pour contenir un système de fichiers FAT32
    valide (`MIN_FAT32_CLUSTERS`) -- ne devrait jamais se produire sur une
    carte SD réelle, garde-fou plutôt que cas attendu."""


@dataclass
class Fat32Layout:
    total_sectors: int
    sectors_per_cluster: int
    fat_size_sectors: int
    first_data_sector: int
    total_clusters: int


def sectors_per_cluster_for_size(size_bytes: int) -> int:
    for threshold, spc in _CLUSTER_SIZE_TABLE:
        if size_bytes < threshold:
            return spc
    return _LARGE_VOLUME_SECTORS_PER_CLUSTER


def compute_fat_size_sectors(total_sectors: int, reserved_sectors: int, num_fats: int, sectors_per_cluster: int) -> int:
    """Formule officielle de dimensionnement de la FAT pour FAT32
    (Microsoft, « fatgen103 », section BPB_FATSz32) -- reprise telle
    quelle, c'est la même que celle utilisée par la quasi-totalité des
    implémentations FAT32 libres (`mkfs.fat` compris)."""
    tmp1 = total_sectors - reserved_sectors
    tmp2 = ((256 * sectors_per_cluster) + num_fats) // 2
    return (tmp1 + tmp2 - 1) // tmp2


def plan_fat32_layout(total_sectors: int, size_bytes: int) -> Fat32Layout:
    sectors_per_cluster = sectors_per_cluster_for_size(size_bytes)
    fat_size_sectors = compute_fat_size_sectors(total_sectors, RESERVED_SECTORS, NUM_FATS, sectors_per_cluster)
    first_data_sector = RESERVED_SECTORS + NUM_FATS * fat_size_sectors
    data_sectors = total_sectors - first_data_sector
    total_clusters = data_sectors // sectors_per_cluster if data_sectors > 0 else 0
    if total_clusters < MIN_FAT32_CLUSTERS:
        raise Fat32VolumeTooSmall(
            f"Volume trop petit pour du FAT32 ({total_clusters} clusters, {MIN_FAT32_CLUSTERS} requis)."
        )
    return Fat32Layout(
        total_sectors=total_sectors,
        sectors_per_cluster=sectors_per_cluster,
        fat_size_sectors=fat_size_sectors,
        first_data_sector=first_data_sector,
        total_clusters=total_clusters,
    )


def _pad_label(label: str) -> bytes:
    """Étiquette FAT (11 caractères, majuscules -- convention historique du
    format, reprise par tous les formateurs natifs déjà utilisés ailleurs
    dans ce projet) : tronquée, complétée par des espaces, et tout
    caractère non ASCII remplacé plutôt que de lever (un néophyte ne tape
    normalement que des caractères simples pour ce champ, §4.3 bis --
    valeur par défaut `DEFAULT_RESET_LABEL`, "SDCARD")."""
    cleaned = label.strip().upper()[:11].ljust(11)
    return cleaned.encode("ascii", "replace")


def _volume_id() -> int:
    return random.getrandbits(32)


def build_boot_sector(
    total_sectors: int,
    hidden_sectors: int,
    sectors_per_cluster: int,
    fat_size_sectors: int,
    label: bytes,
    volume_id: int,
) -> bytes:
    """Secteur de démarrage FAT32 (BPB), disposition des champs reprise de
    la spécification Microsoft (fatgen103) -- code de démarrage laissé à
    zéro (une carte de stockage de données n'a pas besoin d'amorcer quoi
    que ce soit)."""
    bs = bytearray(SECTOR_SIZE)
    bs[0:3] = b"\xeb\x58\x90"  # BS_jmpBoot -- valeur déjà utilisée par le formateur Windows natif
    bs[3:11] = b"MSWIN4.1"  # BS_OEMName -- pour la meilleure compatibilité de reconnaissance
    struct.pack_into("<H", bs, 11, SECTOR_SIZE)  # BPB_BytsPerSec
    bs[13] = sectors_per_cluster  # BPB_SecPerClus
    struct.pack_into("<H", bs, 14, RESERVED_SECTORS)  # BPB_RsvdSecCnt
    bs[16] = NUM_FATS  # BPB_NumFATs
    struct.pack_into("<H", bs, 17, 0)  # BPB_RootEntCnt -- 0 en FAT32 (répertoire racine = une chaîne de clusters)
    struct.pack_into("<H", bs, 19, 0)  # BPB_TotSec16 -- 0, la taille passe par BPB_TotSec32
    bs[21] = 0xF8  # BPB_Media
    struct.pack_into("<H", bs, 22, 0)  # BPB_FATSz16 -- 0, la taille de FAT passe par BPB_FATSz32
    struct.pack_into("<H", bs, 24, 63)  # BPB_SecPerTrk -- géométrie de compatibilité, plus utilisée en pratique
    struct.pack_into("<H", bs, 26, 255)  # BPB_NumHeads
    struct.pack_into("<I", bs, 28, hidden_sectors)  # BPB_HiddSec -- secteurs avant le début de la partition
    struct.pack_into("<I", bs, 32, total_sectors)  # BPB_TotSec32
    struct.pack_into("<I", bs, 36, fat_size_sectors)  # BPB_FATSz32
    struct.pack_into("<H", bs, 40, 0)  # BPB_ExtFlags -- deux FAT en miroir, pas de FAT active isolée
    struct.pack_into("<H", bs, 42, 0)  # BPB_FSVer
    struct.pack_into("<I", bs, 44, 2)  # BPB_RootClus -- répertoire racine au cluster 2
    struct.pack_into("<H", bs, 48, 1)  # BPB_FSInfo -- secteur 1 (relatif au début de la zone réservée)
    struct.pack_into("<H", bs, 50, BACKUP_BOOT_SECTOR_LBA)  # BPB_BkBootSec
    bs[64] = 0x80  # BS_DrvNum
    bs[65] = 0  # BS_Reserved1
    bs[66] = 0x29  # BS_BootSig -- signe la présence des trois champs suivants
    struct.pack_into("<I", bs, 67, volume_id)  # BS_VolID
    bs[71:82] = label  # BS_VolLab (11 octets)
    bs[82:90] = b"FAT32   "  # BS_FilSysType -- purement indicatif, jamais vérifié par un pilote conforme
    bs[510:512] = b"\x55\xaa"
    return bytes(bs)


def build_fsinfo_sector(free_cluster_count: int, next_free_cluster: int) -> bytes:
    fs = bytearray(SECTOR_SIZE)
    struct.pack_into("<I", fs, 0, 0x41615252)  # FSI_LeadSig
    struct.pack_into("<I", fs, 484, 0x61417272)  # FSI_StrucSig
    struct.pack_into("<I", fs, 488, free_cluster_count)  # FSI_Free_Count
    struct.pack_into("<I", fs, 492, next_free_cluster)  # FSI_Nxt_Free
    struct.pack_into("<I", fs, 508, 0xAA550000)  # FSI_TrailSig
    return bytes(fs)


def build_fat_table(fat_size_sectors: int) -> bytes:
    """Deux tables identiques sont écrites (`NUM_FATS`) -- seules les trois
    premières entrées sont significatives : `FAT[0]`/`FAT[1]` (valeurs
    réservées imposées par la spécification) et `FAT[2]` (fin de chaîne
    pour le répertoire racine, qui n'occupe qu'un seul cluster à la
    création). Tout le reste de l'espace de données est libre (zéro)."""
    fat = bytearray(fat_size_sectors * SECTOR_SIZE)
    struct.pack_into("<I", fat, 0, 0x0FFFFFF8)
    struct.pack_into("<I", fat, 4, 0x0FFFFFFF)
    struct.pack_into("<I", fat, 8, 0x0FFFFFFF)  # cluster 2 (répertoire racine) : fin de chaîne
    return bytes(fat)


def build_root_directory(sectors_per_cluster: int, label: bytes) -> bytes:
    """Répertoire racine vide, à l'exception d'une entrée d'étiquette de
    volume (`ATTR_VOLUME_ID`) -- sans elle, Windows affiche un volume sans
    nom dans l'Explorateur malgré `BS_VolLab` (l'étiquette visible dans
    l'Explorateur vient de cette entrée de répertoire, pas du secteur de
    démarrage, sur les systèmes Windows modernes)."""
    root = bytearray(sectors_per_cluster * SECTOR_SIZE)
    root[0:11] = label
    root[11] = 0x08  # ATTR_VOLUME_ID
    return bytes(root)


def format_fat32(raw_path: str, partition_start_bytes: int, partition_size_bytes: int, label: str) -> None:
    """Écrit un système de fichiers FAT32 vide directement sur `raw_path`
    (périphérique déjà verrouillé/démonté par l'appelant, §4.3 --
    `imaging/write_target.py::prepared_write_target`), à l'octet
    `partition_start_bytes` de ce périphérique, sur `partition_size_bytes`
    octets. N'écrit jamais au-delà de la zone métadonnées (secteurs
    réservés + tables FAT + premier cluster du répertoire racine) -- le
    reste de l'espace de données n'a pas besoin d'être mis à zéro pour
    qu'un système de fichiers vide soit valide, exactement comme les
    formateurs natifs déjà utilisés ailleurs dans ce projet
    (`mkfs.vfat`/`diskutil eraseVolume`/`Format-Volume`)."""
    total_sectors = partition_size_bytes // SECTOR_SIZE
    hidden_sectors = partition_start_bytes // SECTOR_SIZE
    layout = plan_fat32_layout(total_sectors, partition_size_bytes)

    label_bytes = _pad_label(label)
    boot_sector = build_boot_sector(
        total_sectors=total_sectors,
        hidden_sectors=hidden_sectors,
        sectors_per_cluster=layout.sectors_per_cluster,
        fat_size_sectors=layout.fat_size_sectors,
        label=label_bytes,
        volume_id=_volume_id(),
    )
    fsinfo_sector = build_fsinfo_sector(free_cluster_count=layout.total_clusters - 1, next_free_cluster=3)
    fat_table = build_fat_table(layout.fat_size_sectors)
    root_directory = build_root_directory(layout.sectors_per_cluster, label_bytes)
    zero_sector = bytes(SECTOR_SIZE)

    with open(raw_path, "r+b") as f:

        def write_at(lba: int, data: bytes) -> None:
            f.seek(partition_start_bytes + lba * SECTOR_SIZE)
            f.write(data)

        write_at(0, boot_sector)
        write_at(1, fsinfo_sector)
        for lba in range(2, RESERVED_SECTORS):
            write_at(lba, zero_sector)
        # Secteurs de sauvegarde (§ spec : `BPB_BkBootSec`) -- utilisés par
        # un outil de réparation si le secteur de démarrage principal est
        # corrompu, jamais lus par un montage normal.
        write_at(BACKUP_BOOT_SECTOR_LBA, boot_sector)
        write_at(BACKUP_BOOT_SECTOR_LBA + 1, fsinfo_sector)

        fat_region_start = RESERVED_SECTORS
        write_at(fat_region_start, fat_table)
        write_at(fat_region_start + layout.fat_size_sectors, fat_table)

        write_at(layout.first_data_sector, root_directory)

        f.flush()
        os.fsync(f.fileno())


__all__ = [
    "Fat32VolumeTooSmall",
    "Fat32Layout",
    "sectors_per_cluster_for_size",
    "compute_fat_size_sectors",
    "plan_fat32_layout",
    "build_boot_sector",
    "build_fsinfo_sector",
    "build_fat_table",
    "build_root_directory",
    "format_fat32",
]
