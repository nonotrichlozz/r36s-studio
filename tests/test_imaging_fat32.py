"""Tests du formateur FAT32 « à la main » (imaging/fat32.py) -- même style
que `test_imaging_reset_card.py`/`test_imaging_system_backup.py` : jeux de
données factices, reparsing indépendant (struct.unpack_from direct plutôt
que réutiliser les fonctions de construction) de la structure produite,
aucune carte réelle."""

from __future__ import annotations

import struct

import pytest

from r36s_studio.imaging.fat32 import (
    Fat32VolumeTooSmall,
    build_fat_table,
    compute_fat_size_sectors,
    format_fat32,
    plan_fat32_layout,
    sectors_per_cluster_for_size,
)

SECTOR_SIZE = 512


# --- taille de cluster --------------------------------------------------------


def test_sectors_per_cluster_matches_the_default_table():
    assert sectors_per_cluster_for_size(32 * 1024 * 1024) == 1
    assert sectors_per_cluster_for_size(100 * 1024 * 1024) == 2
    assert sectors_per_cluster_for_size(200 * 1024 * 1024) == 4
    assert sectors_per_cluster_for_size(1 * 1024 * 1024 * 1024) == 8
    assert sectors_per_cluster_for_size(10 * 1024 * 1024 * 1024) == 16
    assert sectors_per_cluster_for_size(20 * 1024 * 1024 * 1024) == 32


def test_sectors_per_cluster_uses_32kio_clusters_beyond_the_windows_formatter_ceiling():
    """Au-delà de 32 Go, le formateur Windows standard refuse simplement le
    FAT32 (§ docstring de module) -- ce module reprend la dernière taille
    de cluster de sa table plutôt que d'en inventer une nouvelle, comme le
    font les formateurs tiers qui contournent cette même limite. Cas réel
    qui motive ce module : une carte de 128 Go."""
    assert sectors_per_cluster_for_size(128 * 1024 * 1024 * 1024) == 64


# --- dimensionnement de la table FAT ------------------------------------------


def test_plan_fat32_layout_fat_is_large_enough_to_address_every_cluster():
    """Vérifie une propriété plutôt que de recalculer la même formule : la
    FAT produite doit pouvoir adresser toutes les entrées 0..total_clusters+1
    (les deux premières sont réservées) sans déborder de `fat_size_sectors`."""
    total_sectors = 200_000
    layout = plan_fat32_layout(total_sectors, total_sectors * SECTOR_SIZE)

    assert layout.fat_size_sectors * SECTOR_SIZE >= (layout.total_clusters + 2) * 4
    assert layout.first_data_sector == 32 + 2 * layout.fat_size_sectors
    assert layout.total_clusters > 0


def test_plan_fat32_layout_raises_when_volume_is_too_small_for_fat32():
    with pytest.raises(Fat32VolumeTooSmall):
        plan_fat32_layout(total_sectors=40_000, size_bytes=40_000 * SECTOR_SIZE)


def test_compute_fat_size_sectors_grows_with_more_sectors_to_address():
    small = compute_fat_size_sectors(200_000, reserved_sectors=32, num_fats=2, sectors_per_cluster=8)
    large = compute_fat_size_sectors(2_000_000, reserved_sectors=32, num_fats=2, sectors_per_cluster=8)
    assert large > small


# --- écriture complète, reparsée indépendamment -------------------------------


def _make_backing_file(tmp_path, name, total_bytes):
    path = tmp_path / name
    with open(path, "wb") as f:
        f.seek(total_bytes - 1)
        f.write(b"\x00")
    return str(path)


def _read_sector(path, offset_bytes, lba):
    with open(path, "rb") as f:
        f.seek(offset_bytes + lba * SECTOR_SIZE)
        return f.read(SECTOR_SIZE)


def test_format_fat32_writes_a_boot_sector_readable_as_valid_fat32(tmp_path):
    total_sectors = 200_000
    partition_size = total_sectors * SECTOR_SIZE
    partition_start = 2048 * SECTOR_SIZE  # même alignement que reset_card.py
    path = _make_backing_file(tmp_path, "fake_partition.img", partition_start + partition_size)

    format_fat32(path, partition_start, partition_size, "Ma Carte!")

    boot = _read_sector(path, partition_start, 0)
    assert boot[0:3] == b"\xeb\x58\x90"
    assert boot[3:11] == b"MSWIN4.1"
    assert struct.unpack_from("<H", boot, 11)[0] == SECTOR_SIZE  # BPB_BytsPerSec
    sec_per_clus = boot[13]
    assert sec_per_clus == sectors_per_cluster_for_size(partition_size)
    assert struct.unpack_from("<H", boot, 14)[0] == 32  # BPB_RsvdSecCnt
    assert boot[16] == 2  # BPB_NumFATs
    assert struct.unpack_from("<H", boot, 17)[0] == 0  # BPB_RootEntCnt
    assert boot[21] == 0xF8  # BPB_Media
    assert struct.unpack_from("<I", boot, 28)[0] == 2048  # BPB_HiddSec
    assert struct.unpack_from("<I", boot, 32)[0] == total_sectors  # BPB_TotSec32
    fat_size_sectors = struct.unpack_from("<I", boot, 36)[0]  # BPB_FATSz32
    assert fat_size_sectors > 0
    assert struct.unpack_from("<I", boot, 44)[0] == 2  # BPB_RootClus
    assert struct.unpack_from("<H", boot, 48)[0] == 1  # BPB_FSInfo
    assert struct.unpack_from("<H", boot, 50)[0] == 6  # BPB_BkBootSec
    assert boot[66] == 0x29  # BS_BootSig
    # Étiquette tronquée à 11 caractères, mise en majuscules, espaces en
    # complément -- le "!" (non ASCII-safe pour un label FAT) n'est pas
    # transformé par le remplacement ASCII (déjà un caractère ASCII valide).
    assert boot[71:82] == b"MA CARTE!  "
    assert boot[82:90] == b"FAT32   "
    assert boot[510:512] == b"\x55\xaa"

    # Sauvegarde du secteur de démarrage (BPB_BkBootSec = 6)
    assert _read_sector(path, partition_start, 6) == boot


def test_format_fat32_fsinfo_sector_and_its_backup_are_consistent(tmp_path):
    total_sectors = 200_000
    partition_size = total_sectors * SECTOR_SIZE
    partition_start = 2048 * SECTOR_SIZE
    path = _make_backing_file(tmp_path, "fake_partition.img", partition_start + partition_size)

    format_fat32(path, partition_start, partition_size, "SDCARD")

    layout = plan_fat32_layout(total_sectors, partition_size)
    fsinfo = _read_sector(path, partition_start, 1)
    assert struct.unpack_from("<I", fsinfo, 0)[0] == 0x41615252  # FSI_LeadSig
    assert struct.unpack_from("<I", fsinfo, 484)[0] == 0x61417272  # FSI_StrucSig
    assert struct.unpack_from("<I", fsinfo, 488)[0] == layout.total_clusters - 1  # FSI_Free_Count
    assert struct.unpack_from("<I", fsinfo, 492)[0] == 3  # FSI_Nxt_Free
    assert struct.unpack_from("<I", fsinfo, 508)[0] == 0xAA550000  # FSI_TrailSig

    # Sauvegarde du secteur FSInfo (BPB_BkBootSec + 1 = 7)
    assert _read_sector(path, partition_start, 7) == fsinfo


def test_format_fat32_fat_tables_mark_reserved_and_root_dir_entries(tmp_path):
    total_sectors = 200_000
    partition_size = total_sectors * SECTOR_SIZE
    partition_start = 2048 * SECTOR_SIZE
    path = _make_backing_file(tmp_path, "fake_partition.img", partition_start + partition_size)

    format_fat32(path, partition_start, partition_size, "SDCARD")

    layout = plan_fat32_layout(total_sectors, partition_size)
    with open(path, "rb") as f:
        f.seek(partition_start + 32 * SECTOR_SIZE)
        fat1 = f.read(layout.fat_size_sectors * SECTOR_SIZE)
        fat2 = f.read(layout.fat_size_sectors * SECTOR_SIZE)

    assert struct.unpack_from("<I", fat1, 0)[0] == 0x0FFFFFF8
    assert struct.unpack_from("<I", fat1, 4)[0] == 0x0FFFFFFF
    assert struct.unpack_from("<I", fat1, 8)[0] == 0x0FFFFFFF  # cluster 2 (racine) : fin de chaîne
    assert fat1[12:] == bytes(len(fat1) - 12)  # tout le reste libre
    assert fat1 == fat2  # les deux tables sont des copies identiques


def test_format_fat32_root_directory_carries_only_the_volume_label(tmp_path):
    total_sectors = 200_000
    partition_size = total_sectors * SECTOR_SIZE
    partition_start = 2048 * SECTOR_SIZE
    path = _make_backing_file(tmp_path, "fake_partition.img", partition_start + partition_size)

    format_fat32(path, partition_start, partition_size, "SDCARD")

    layout = plan_fat32_layout(total_sectors, partition_size)
    with open(path, "rb") as f:
        f.seek(partition_start + layout.first_data_sector * SECTOR_SIZE)
        root = f.read(layout.sectors_per_cluster * SECTOR_SIZE)

    assert root[0:11] == b"SDCARD     "
    assert root[11] == 0x08  # ATTR_VOLUME_ID
    assert root[32:] == bytes(len(root) - 32)  # aucune autre entrée


def test_build_fat_table_size_matches_requested_sector_count():
    table = build_fat_table(fat_size_sectors=10)
    assert len(table) == 10 * SECTOR_SIZE
