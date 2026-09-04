"""Tests de la sauvegarde « système sans les jeux » (imaging/system_backup.py)
-- jeux de données factices (MBR et GPT), aucune carte réelle. `list_
partitions` (étiquettes) et `prepared_source` (démontage macOS) sont mockés,
comme dans `test_backup.py`/`test_partitions_jobs.py`.

Le point critique testé ici, bout en bout sur le cas GPT : l'image produite
doit rester une GPT cohérente une fois tronquée -- table secondaire présente
à la nouvelle fin de fichier, CRC32 corrects, partition de jeux absente des
deux tables (primaire *et* secondaire)."""

from __future__ import annotations

import contextlib
import os
import struct
import zlib
from unittest.mock import patch

import pytest

from r36s_studio.devices import Device
from r36s_studio.imaging.gpt import (
    GPT_ENTRY_SIZE,
    GPT_HEADER_SIZE,
    GptPartitionEntry,
    build_gpt_entries,
    build_gpt_header,
    parse_gpt_entries,
    parse_gpt_header,
)
from r36s_studio.imaging.mbr import parse_mbr
from r36s_studio.imaging.system_backup import (
    GamesPartitionNotFound,
    backup_system_only,
    compute_system_boundary,
    estimate_system_backup_size,
    estimate_system_backup_size_unprivileged,
)
from r36s_studio.partitions.locate import PartitionInfo

SECTOR_SIZE = 512
PARTITION_TABLE_OFFSET = 446


@contextlib.contextmanager
def _no_prep(path):
    yield path


def _make_device(path: str, size_bytes: int) -> Device:
    return Device(
        path=path, display="Carte SD factice", size_bytes=size_bytes, removable=True, bus="USB",
        is_system=False, mountpoints=[],
    )


# --- MBR -------------------------------------------------------------------


def _build_fake_mbr_image(
    tmp_path, *, boot=(2048, 4095), root=(4096, 6143), games=(6144, 8191), trailing=4096, sparse=False
):
    """BOOT/root/EASYROMS, une carte ArkOS-like en miniature -- tuples
    (start_lba, end_lba inclusif). `sparse=True` n'écrit que le premier
    secteur (la table de partitions) puis étend le fichier par `seek` --
    un vrai fichier creux sur un système de fichiers qui le permet, bien
    plus rapide pour les images de test volumineuses (seuil de grande
    taille, § note de module) dont le contenu au-delà de l'en-tête n'est
    de toute façon jamais lu par `compute_system_boundary`."""
    total_sectors = games[1] + 1 + trailing
    first_sector = bytearray(SECTOR_SIZE)
    for i, (ptype, (start, end)) in enumerate([(0x0E, boot), (0x83, root), (0x0B, games)]):
        offset = PARTITION_TABLE_OFFSET + i * 16
        first_sector[offset + 4] = ptype
        first_sector[offset + 8 : offset + 12] = struct.pack("<I", start)
        first_sector[offset + 12 : offset + 16] = struct.pack("<I", end - start + 1)
    first_sector[510:512] = b"\x55\xaa"

    path = tmp_path / "fake_mbr_sd.img"
    if sparse:
        with open(path, "wb") as f:
            f.write(bytes(first_sector))
            f.seek(total_sectors * SECTOR_SIZE - 1)
            f.write(b"\x00")
    else:
        data = bytearray(os.urandom(total_sectors * SECTOR_SIZE))
        data[0:SECTOR_SIZE] = bytes(first_sector)
        path.write_bytes(bytes(data))
    return str(path), total_sectors


def _mbr_partition_labels(source_path, games_label="EASYROMS"):
    return [
        PartitionInfo(f"{source_path}s1", "", "msdos", None),
        PartitionInfo(f"{source_path}s2", "", "ext4", None),
        PartitionInfo(f"{source_path}s3", games_label, "ntfs", None),
    ]


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_mbr_stops_before_games_partition(mock_list, tmp_path):
    source_path, _ = _build_fake_mbr_image(tmp_path)
    mock_list.return_value = _mbr_partition_labels(source_path)

    boundary = compute_system_boundary(source_path)

    assert boundary.is_gpt is False
    assert boundary.end_bytes == (6143) * SECTOR_SIZE + SECTOR_SIZE  # fin de root (secteur 6143 inclus)


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_mbr_copies_only_up_to_boundary(mock_prep, mock_list, tmp_path):
    source_path, total_sectors = _build_fake_mbr_image(tmp_path)
    mock_list.return_value = _mbr_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    output_path = tmp_path / "system_backup.img"

    written = backup_system_only(device, str(output_path))

    expected_end = 6144 * SECTOR_SIZE
    assert written == expected_end
    assert output_path.stat().st_size == expected_end
    assert output_path.stat().st_size < total_sectors * SECTOR_SIZE  # bien plus petit que le disque entier
    with open(source_path, "rb") as f:
        expected_data = bytearray(f.read(expected_end))
    # Le créneau MBR de la partition de jeux (retirée) est mis à zéro dans
    # l'image produite (§ point critique de module) -- seul le premier
    # secteur diffère de la source, le reste est une copie à l'identique.
    expected_data[PARTITION_TABLE_OFFSET + 2 * 16 : PARTITION_TABLE_OFFSET + 3 * 16] = bytes(16)
    assert output_path.read_bytes() == bytes(expected_data)


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_recognizes_storage_label(mock_list, tmp_path):
    """EmuELEC nomme sa partition de jeux STORAGE, pas EASYROMS (§4.6)."""
    source_path, _ = _build_fake_mbr_image(tmp_path)
    mock_list.return_value = _mbr_partition_labels(source_path, games_label="STORAGE")

    boundary = compute_system_boundary(source_path)

    assert boundary.end_bytes == 6144 * SECTOR_SIZE


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_raises_when_no_games_partition_recognized(mock_list, tmp_path):
    """Cas d'une carte ROCKNIX (§4.5) : pas de partition de jeux séparée,
    les ROMs vivent dans la partition Linux -- rien où s'arrêter."""
    source_path, _ = _build_fake_mbr_image(tmp_path)
    mock_list.return_value = [
        PartitionInfo(f"{source_path}s1", "ROCKNIX", "msdos", None),
        PartitionInfo(f"{source_path}s2", "", "ext4", None),
    ]

    with pytest.raises(GamesPartitionNotFound):
        compute_system_boundary(source_path)


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_raises_when_games_partition_is_first(mock_list, tmp_path):
    source_path, _ = _build_fake_mbr_image(tmp_path)
    mock_list.return_value = [PartitionInfo(f"{source_path}s1", "EASYROMS", "ntfs", None)]

    with pytest.raises(GamesPartitionNotFound):
        compute_system_boundary(source_path)


# --- repli sans étiquette reconnue : dernière partition FAT/NTFS de -------
# --- grande taille (§ note de module) -------------------------------------


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_falls_back_to_large_unlabeled_last_fat_partition(mock_list, tmp_path):
    """Aucune étiquette EASYROMS/STORAGE -- mais la dernière partition est
    un grand FAT32, un signal suffisant pour la traiter comme la
    partition de jeux."""
    source_path, _ = _build_fake_mbr_image(tmp_path)  # games : secteurs 6144-8191, ~1 Mo -> trop petit pour ce test
    mock_list.return_value = [
        PartitionInfo(f"{source_path}s1", "", "msdos", None),
        PartitionInfo(f"{source_path}s2", "", "ext4", None),
        PartitionInfo(f"{source_path}s3", "", "fat32", None),  # pas d'étiquette reconnue
    ]

    with pytest.raises(GamesPartitionNotFound):
        # La partition factice ne fait que ~1 Mo ici : sous le seuil de
        # « grande taille » -- confirme que le repli ne se déclenche pas
        # sur n'importe quelle dernière partition FAT, voir le test dédié
        # au seuil ci-dessous pour le cas qui doit réussir.
        compute_system_boundary(source_path)


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_fallback_requires_large_size(mock_list, tmp_path):
    """Repli déclenché avec succès quand la dernière partition FAT/NTFS
    dépasse le seuil de grande taille (`_LARGE_PARTITION_THRESHOLD_BYTES`,
    1 Go) -- construit une image dédiée dont la partition de jeux dépasse
    ce seuil, sans étiquette EASYROMS/STORAGE."""
    boot = (2048, 4095)
    root = (4096, 6143)
    games = (6144, 6144 + 2_100_000 - 1)  # ~1,05 Go, au-dessus du seuil
    source_path, _ = _build_fake_mbr_image(tmp_path, boot=boot, root=root, games=games, trailing=16, sparse=True)
    mock_list.return_value = [
        PartitionInfo(f"{source_path}s1", "", "msdos", None),
        PartitionInfo(f"{source_path}s2", "", "ext4", None),
        PartitionInfo(f"{source_path}s3", "", "fat32", None),  # pas d'étiquette reconnue
    ]

    boundary = compute_system_boundary(source_path)

    assert boundary.end_bytes == 6144 * SECTOR_SIZE  # fin de root, juste avant la partition de jeux


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_fallback_accepts_exfat(mock_list, tmp_path):
    """Confirmé sur du vrai matériel : le système de fichiers d'EASYROMS
    varie selon le vendeur (NTFS constaté ailleurs, exFAT ici) -- le repli
    sans étiquette doit l'accepter comme il accepte FAT/NTFS."""
    boot = (2048, 4095)
    root = (4096, 6143)
    games = (6144, 6144 + 2_100_000 - 1)  # ~1,05 Go, au-dessus du seuil
    source_path, _ = _build_fake_mbr_image(tmp_path, boot=boot, root=root, games=games, trailing=16, sparse=True)
    mock_list.return_value = [
        PartitionInfo(f"{source_path}s1", "", "msdos", None),
        PartitionInfo(f"{source_path}s2", "", "ext4", None),
        PartitionInfo(f"{source_path}s3", "", "exfat", None),  # pas d'étiquette reconnue
    ]

    boundary = compute_system_boundary(source_path)

    assert boundary.end_bytes == 6144 * SECTOR_SIZE  # fin de root, juste avant la partition de jeux


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_fallback_ignores_non_fat_ntfs_last_partition(mock_list, tmp_path):
    """Une dernière partition volumineuse mais pas FAT/NTFS (ext4, par
    exemple) ne doit jamais être prise pour la partition de jeux --
    signal insuffisant sans le bon système de fichiers."""
    boot = (2048, 4095)
    root = (4096, 6143)
    games = (6144, 6144 + 2_100_000 - 1)
    source_path, _ = _build_fake_mbr_image(tmp_path, boot=boot, root=root, games=games, trailing=16, sparse=True)
    mock_list.return_value = [
        PartitionInfo(f"{source_path}s1", "", "msdos", None),
        PartitionInfo(f"{source_path}s2", "", "ext4", None),
        PartitionInfo(f"{source_path}s3", "", "ext4", None),  # grande mais pas FAT/NTFS
    ]

    with pytest.raises(GamesPartitionNotFound):
        compute_system_boundary(source_path)


# --- réparation de la table MBR de l'image produite (§ point critique) ----


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_mbr_output_table_is_consistent_with_real_file_size(mock_prep, mock_list, tmp_path):
    """Le point critique côté MBR : la table de l'image produite ne doit
    plus contenir d'entrée décrivant un espace au-delà de la taille
    réelle du fichier -- exactement ce qui rendrait l'image incohérente
    pour un outil de partitionnement, confirmé sur du vrai matériel côté
    GPT (voir le test équivalent plus bas)."""
    source_path, total_sectors = _build_fake_mbr_image(tmp_path)
    mock_list.return_value = _mbr_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    output_path = tmp_path / "system_backup.img"

    backup_system_only(device, str(output_path))
    output_bytes = output_path.read_bytes()

    partitions = parse_mbr(output_bytes[:SECTOR_SIZE])
    assert [p.start_lba for p in partitions] == [2048, 4096]  # jamais la partition de jeux
    for partition in partitions:
        assert partition.end_bytes <= len(output_bytes)


# --- estimation sans accès brut (§4.3) -- confirmé sur du vrai matériel : --
# --- lire la table de partitions brute (/dev/diskN) exige les droits -----
# --- administrateur sur macOS, contrairement à `list_partitions` (déjà ---
# --- non élevé). Une estimation n'a pas besoin d'être exacte à l'octet ---
# --- près -- l'opération réelle, elle, passe par `compute_system_boundary` -
# --- (table brute, précis), inchangé. --------------------------------------


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_sums_sizes_of_kept_partitions_by_label(mock_list):
    mock_list.return_value = [
        PartitionInfo("/dev/x1", "", "msdos", None, size_bytes=100_000_000),
        PartitionInfo("/dev/x2", "", "ext4", None, size_bytes=500_000_000),
        PartitionInfo("/dev/x3", "EASYROMS", "ntfs", None, size_bytes=9_000_000_000),
    ]

    estimate = estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1")

    assert estimate == 600_000_000


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_uses_storage_label_too(mock_list):
    mock_list.return_value = [
        PartitionInfo("/dev/x1", "", "msdos", None, size_bytes=100_000_000),
        PartitionInfo("/dev/x2", "STORAGE", "fat32", None, size_bytes=25_000_000_000),
    ]

    assert estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1") == 100_000_000


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_falls_back_to_large_unlabeled_last_fat_partition(mock_list):
    mock_list.return_value = [
        PartitionInfo("/dev/x1", "", "msdos", None, size_bytes=100_000_000),
        PartitionInfo("/dev/x2", "", "ext4", None, size_bytes=500_000_000),
        PartitionInfo("/dev/x3", "", "fat32", None, size_bytes=9_000_000_000),  # pas d'étiquette reconnue
    ]

    estimate = estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1")

    assert estimate == 600_000_000


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_falls_back_to_large_unlabeled_last_exfat_partition(mock_list):
    """Confirmé sur du vrai matériel : EASYROMS peut être en exFAT selon le
    vendeur -- le repli sans étiquette doit l'accepter comme il accepte
    FAT/NTFS."""
    mock_list.return_value = [
        PartitionInfo("/dev/x1", "", "msdos", None, size_bytes=100_000_000),
        PartitionInfo("/dev/x2", "", "ext4", None, size_bytes=500_000_000),
        PartitionInfo("/dev/x3", "", "exfat", None, size_bytes=9_000_000_000),  # pas d'étiquette reconnue
    ]

    estimate = estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1")

    assert estimate == 600_000_000


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_returns_none_when_a_kept_partition_has_no_size(mock_list):
    """Repli élevé nécessaire (§4.3) -- au moins une taille manque parmi
    les partitions à sommer, impossible de produire une estimation
    fiable sans lecture brute."""
    mock_list.return_value = [
        PartitionInfo("/dev/x1", "", "msdos", None, size_bytes=None),
        PartitionInfo("/dev/x2", "EASYROMS", "ntfs", None, size_bytes=9_000_000_000),
    ]

    assert estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1") is None


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_returns_none_when_fallback_needs_a_missing_size(mock_list):
    """Aucune étiquette reconnue, et la taille de la dernière partition
    (nécessaire pour vérifier le seuil de grande taille) manque -- pas
    assez d'information pour même tenter le repli."""
    mock_list.return_value = [
        PartitionInfo("/dev/x1", "", "msdos", None, size_bytes=100_000_000),
        PartitionInfo("/dev/x2", "", "fat32", None, size_bytes=None),
    ]

    assert estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1") is None


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_raises_when_no_games_partition_recognized(mock_list):
    mock_list.return_value = [
        PartitionInfo("/dev/x1", "ROCKNIX", "msdos", None, size_bytes=100_000_000),
        PartitionInfo("/dev/x2", "", "ext4", None, size_bytes=30_000_000_000),
    ]

    with pytest.raises(GamesPartitionNotFound):
        estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1")


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_unprivileged_raises_when_games_partition_is_first(mock_list):
    mock_list.return_value = [PartitionInfo("/dev/x1", "EASYROMS", "ntfs", None, size_bytes=9_000_000_000)]

    with pytest.raises(GamesPartitionNotFound):
        estimate_system_backup_size_unprivileged("/dev/fake-disk-test-1")


# --- GPT ---------------------------------------------------------------


def _gpt_entry(bounds, name):
    start, end = bounds
    return GptPartitionEntry(
        type_guid=b"\x01" * 16,
        unique_guid=b"\xaa" * 16,
        start_lba=start,
        end_lba=end,
        attributes=0,
        name=name.encode("utf-16-le").ljust(72, b"\x00")[:72],
    )


def _build_fake_gpt_image(tmp_path, *, boot=(34, 133), root=(134, 233), games=(234, 333), trailing=200, sparse=False):
    """`sparse=True` : voir `_build_fake_mbr_image` -- même principe, un
    vrai fichier creux au-delà de la tête (MBR protecteur + en-tête GPT +
    tableau d'entrées, LBA0-33), jamais lue par `compute_system_boundary`."""
    total_sectors = games[1] + 1 + trailing
    head = bytearray(34 * SECTOR_SIZE)  # LBA0 (MBR protecteur) à LBA33 (fin du tableau d'entrées)

    head[PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + 4 * 16] = bytes(4 * 16)
    head[PARTITION_TABLE_OFFSET + 4] = 0xEE
    head[PARTITION_TABLE_OFFSET + 8 : PARTITION_TABLE_OFFSET + 12] = struct.pack("<I", 1)
    head[PARTITION_TABLE_OFFSET + 12 : PARTITION_TABLE_OFFSET + 16] = struct.pack(
        "<I", min(total_sectors - 1, 0xFFFFFFFF)
    )
    head[510:512] = b"\x55\xaa"

    entries = [_gpt_entry(boot, "BOOT"), _gpt_entry(root, "root"), _gpt_entry(games, "EASYROMS")]
    entries_bytes = build_gpt_entries(entries, num_entries=128, entry_size=GPT_ENTRY_SIZE)
    header_sector = build_gpt_header(
        revision=b"\x00\x00\x01\x00",
        my_lba=1,
        alternate_lba=total_sectors - 1,
        first_usable_lba=34,
        last_usable_lba=total_sectors - 34,
        disk_guid=b"\x99" * 16,
        partition_entry_lba=2,
        num_entries=128,
        entry_size=GPT_ENTRY_SIZE,
        entries_bytes=entries_bytes,
    )
    head[1 * SECTOR_SIZE : 2 * SECTOR_SIZE] = header_sector
    head[2 * SECTOR_SIZE : 2 * SECTOR_SIZE + len(entries_bytes)] = entries_bytes

    path = tmp_path / "fake_gpt_sd.img"
    if sparse:
        with open(path, "wb") as f:
            f.write(bytes(head))
            f.seek(total_sectors * SECTOR_SIZE - 1)
            f.write(b"\x00")
    else:
        data = bytearray(os.urandom(total_sectors * SECTOR_SIZE))
        data[0 : len(head)] = bytes(head)
        path.write_bytes(bytes(data))
    return str(path), total_sectors


def _gpt_partition_labels(source_path, games_label="EASYROMS"):
    return [
        PartitionInfo(f"{source_path}s1", "BOOT", "msdos", None, partition_type="efi"),
        PartitionInfo(f"{source_path}s2", "", "ext4", None, partition_type="linux filesystem"),
        PartitionInfo(f"{source_path}s3", games_label, "ntfs", None, partition_type="microsoft basic data"),
    ]


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_gpt_stops_before_games_partition(mock_list, tmp_path):
    source_path, _ = _build_fake_gpt_image(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)

    boundary = compute_system_boundary(source_path)

    assert boundary.is_gpt is True
    assert boundary.end_bytes == 234 * SECTOR_SIZE  # fin de root (secteur 233 inclus)
    assert [e.start_lba for e in boundary.kept_gpt_entries] == [34, 134]


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_compute_system_boundary_gpt_falls_back_to_large_unlabeled_last_fat_partition(mock_list, tmp_path):
    games = (234, 234 + 2_100_000 - 1)  # ~1,05 Go, au-dessus du seuil de grande taille
    source_path, _ = _build_fake_gpt_image(tmp_path, games=games, trailing=16, sparse=True)
    mock_list.return_value = [
        PartitionInfo(f"{source_path}s1", "BOOT", "msdos", None),
        PartitionInfo(f"{source_path}s2", "", "ext4", None),
        PartitionInfo(f"{source_path}s3", "", "fat32", None),  # pas d'étiquette reconnue
    ]

    boundary = compute_system_boundary(source_path)

    assert boundary.end_bytes == 234 * SECTOR_SIZE


@patch("r36s_studio.imaging.system_backup.list_partitions")
def test_estimate_system_backup_size_gpt_includes_secondary_table(mock_list, tmp_path):
    source_path, _ = _build_fake_gpt_image(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)

    estimate = estimate_system_backup_size(source_path)

    # 234 secteurs de données + 32 secteurs de tableau secondaire + 1
    # secteur d'en-tête secondaire.
    assert estimate == (234 + 32 + 1) * SECTOR_SIZE


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_gpt_output_is_much_smaller_than_source(mock_prep, mock_list, tmp_path):
    source_path, total_sectors = _build_fake_gpt_image(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    output_path = tmp_path / "system_backup.img"

    written = backup_system_only(device, str(output_path))

    assert output_path.stat().st_size == written
    assert written < total_sectors * SECTOR_SIZE


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_gpt_preserves_partition_data_bytes(mock_prep, mock_list, tmp_path):
    """Les octets des partitions gardées (au-delà de la table primaire,
    réécrite) doivent être copiés tels quels, sans altération."""
    source_path, total_sectors = _build_fake_gpt_image(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    output_path = tmp_path / "system_backup.img"

    backup_system_only(device, str(output_path))

    data_region_start = 34 * SECTOR_SIZE  # après LBA0-33 (MBR protecteur + en-tête + tableau)
    boundary_end = 234 * SECTOR_SIZE
    with open(source_path, "rb") as f:
        f.seek(data_region_start)
        expected = f.read(boundary_end - data_region_start)
    actual = output_path.read_bytes()[data_region_start:boundary_end]
    assert actual == expected


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_gpt_output_has_a_consistent_partition_table(mock_prep, mock_list, tmp_path):
    """Le point critique : l'image tronquée doit être une GPT valide et
    cohérente -- en-tête primaire pointant vers un en-tête secondaire réel
    en fin de fichier, CRC32 corrects des deux côtés, partition de jeux
    absente des deux tableaux d'entrées."""
    source_path, total_sectors = _build_fake_gpt_image(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    output_path = tmp_path / "system_backup.img"

    backup_system_only(device, str(output_path))
    output_bytes = output_path.read_bytes()

    primary_header = parse_gpt_header(output_bytes[SECTOR_SIZE : 2 * SECTOR_SIZE])
    assert primary_header.my_lba == 1
    assert primary_header.last_usable_lba == 234 - 1  # juste avant le tableau secondaire

    primary_entries_bytes = output_bytes[
        primary_header.partition_entry_lba * SECTOR_SIZE
        : primary_header.partition_entry_lba * SECTOR_SIZE + primary_header.num_entries * primary_header.entry_size
    ]
    primary_entries = parse_gpt_entries(primary_entries_bytes, primary_header)
    assert [e.start_lba for e in primary_entries] == [34, 134]  # jamais la partition de jeux (234)
    assert _verify_header_crc32(output_bytes, 1 * SECTOR_SIZE)
    assert _verify_entry_array_crc32(primary_header, primary_entries_bytes)
    # Aucune entrée gardée ne doit décrire un espace au-delà de la taille
    # réelle du fichier -- exactement ce qui rend une image GPT tronquée
    # incohérente pour un outil de partitionnement (confirmé sur du vrai
    # matériel, CLAUDE.md).
    for entry in primary_entries:
        assert (entry.end_lba + 1) * SECTOR_SIZE <= len(output_bytes)

    secondary_header_lba = primary_header.alternate_lba
    secondary_header = parse_gpt_header(
        output_bytes[secondary_header_lba * SECTOR_SIZE : (secondary_header_lba + 1) * SECTOR_SIZE]
    )
    assert secondary_header.my_lba == secondary_header_lba
    assert secondary_header.alternate_lba == 1
    assert secondary_header.last_usable_lba == primary_header.last_usable_lba
    # La table secondaire est censée se trouver en toute fin du fichier.
    assert (secondary_header_lba + 1) * SECTOR_SIZE == len(output_bytes)

    secondary_entries_bytes = output_bytes[
        secondary_header.partition_entry_lba * SECTOR_SIZE
        : secondary_header.partition_entry_lba * SECTOR_SIZE
        + secondary_header.num_entries * secondary_header.entry_size
    ]
    secondary_entries = parse_gpt_entries(secondary_entries_bytes, secondary_header)
    assert [e.start_lba for e in secondary_entries] == [34, 134]
    assert _verify_header_crc32(output_bytes, secondary_header_lba * SECTOR_SIZE)
    assert _verify_entry_array_crc32(secondary_header, secondary_entries_bytes)


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_gpt_updates_protective_mbr_sector_count(mock_prep, mock_list, tmp_path):
    """Bug corrigé, confirmé sur du vrai matériel : le même symptôme
    (image inbootable, `gdisk` signalant « Disk size is smaller than the
    main header indicates ») apparaissait sur macOS et Windows, quelle que
    soit la carte cible -- l'en-tête GPT (primaire/secondaire) était bien
    corrigé (test ci-dessus), mais le MBR protecteur (LBA0) continuait de
    décrire la taille du disque *source* (128 Go dans le scénario réel)
    au lieu de la taille du fichier produit (quelques Go). Cette
    incohérence n'était couverte par aucun test -- ce test ferme
    exactement ce trou, sur la même image produite bout en bout par
    `backup_system_only` (pas une table synthétique construite à la
    main)."""
    source_path, total_sectors = _build_fake_gpt_image(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    output_path = tmp_path / "system_backup.img"

    backup_system_only(device, str(output_path))
    output_bytes = output_path.read_bytes()

    mbr_partitions = parse_mbr(output_bytes[:SECTOR_SIZE])
    protective = next(p for p in mbr_partitions if p.partition_type == 0xEE)
    expected_sector_count = (len(output_bytes) // SECTOR_SIZE) - 1
    assert protective.sector_count == expected_sector_count
    # Le défaut corrigé, constaté avant ce correctif : `sector_count`
    # décrivait encore le disque source (bien plus grand que le fichier
    # produit) -- jamais une valeur qui dépasse la taille réelle du
    # fichier.
    assert (protective.start_lba + protective.sector_count) * SECTOR_SIZE <= len(output_bytes)


def _verify_header_crc32(disk_bytes: bytes, header_offset: int) -> bool:
    header_bytes = bytearray(disk_bytes[header_offset : header_offset + GPT_HEADER_SIZE])
    stored = int.from_bytes(header_bytes[16:20], "little")
    header_bytes[16:20] = b"\x00\x00\x00\x00"
    return stored == (zlib.crc32(bytes(header_bytes)) & 0xFFFFFFFF)


def _verify_entry_array_crc32(header, entries_bytes: bytes) -> bool:
    return header.entry_array_crc32 == (zlib.crc32(entries_bytes) & 0xFFFFFFFF)


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_gpt_reports_progress(mock_prep, mock_list, tmp_path):
    source_path, total_sectors = _build_fake_gpt_image(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    events = []

    backup_system_only(device, str(tmp_path / "out.img"), on_progress=events.append, block_size=1024)

    assert events
    assert events[-1].done == 234 * SECTOR_SIZE


# --- Vérification bout en bout entièrement indépendante ---------------------
#
# Bug rapporté sur du vrai matériel (macOS et Windows identiquement) :
# aucune image produite par `backup --system-only` n'a jamais démarré de
# console, alors que la sauvegarde complète et le flash d'une image
# téléchargée fonctionnent tous les deux -- pointant précisément vers ce
# code de troncature/réparation, seul chemin que les deux autres
# n'exécutent jamais.
#
# Différence délibérée avec les tests ci-dessus : `_build_fake_gpt_image`
# construit son disque source factice en réutilisant `build_gpt_header`/
# `build_gpt_entries` -- les MÊMES fonctions que celles testées ici. Un bug
# systématique dans ces fonctions de construction pourrait donc, en
# principe, se retrouver identiquement dans le disque source *et* dans la
# réparation, sans jamais être détecté par un test qui compare les deux.
# `_build_independent_fake_gpt_source`/`_independent_parse_*` ci-dessous
# n'importent RIEN de `r36s_studio.imaging.gpt`/`mbr` : struct.pack/unpack
# à la main, des deux côtés (construction du disque source ET vérification
# de la sortie) -- la seule façon d'éliminer ce risque de bug symétrique.


def _independent_gpt_header_bytes(*, my_lba, alt_lba, first_usable, last_usable, part_entry_lba, entries_bytes):
    h = bytearray(92)
    h[0:8] = b"EFI PART"
    h[8:12] = b"\x00\x00\x01\x00"
    h[12:16] = struct.pack("<I", 92)
    h[24:32] = my_lba.to_bytes(8, "little")
    h[32:40] = alt_lba.to_bytes(8, "little")
    h[40:48] = first_usable.to_bytes(8, "little")
    h[48:56] = last_usable.to_bytes(8, "little")
    h[56:72] = b"\x99" * 16
    h[72:80] = part_entry_lba.to_bytes(8, "little")
    h[80:84] = struct.pack("<I", 128)
    h[84:88] = struct.pack("<I", 128)
    h[88:92] = (zlib.crc32(entries_bytes) & 0xFFFFFFFF).to_bytes(4, "little")
    crc = zlib.crc32(bytes(h)) & 0xFFFFFFFF
    h[16:20] = crc.to_bytes(4, "little")
    return bytes(h).ljust(SECTOR_SIZE, b"\x00")


def _independent_gpt_entry_bytes(start_lba, end_lba, name):
    return (
        (b"\x01" * 16) + (b"\xaa" * 16)
        + start_lba.to_bytes(8, "little") + end_lba.to_bytes(8, "little")
        + (0).to_bytes(8, "little")
        + name.encode("utf-16-le").ljust(72, b"\x00")[:72]
    ).ljust(128, b"\x00")[:128]


def _build_independent_fake_gpt_source(tmp_path, *, boot=(34, 133), root=(134, 233), games=(234, 20233)):
    """`games` s'étend délibérément sur ~20 000 secteurs (~10 Mo) plutôt
    que quelques centaines comme les fixtures ci-dessus -- plus proche du
    ratio réel (partition de jeux largement plus grande que le système,
    §4.3) sans pour autant construire un fichier de plusieurs Go pour un
    test unitaire."""
    total_sectors = games[1] + 1 + 2000
    head = bytearray(34 * SECTOR_SIZE)
    head[PARTITION_TABLE_OFFSET + 4] = 0xEE
    head[PARTITION_TABLE_OFFSET + 8 : PARTITION_TABLE_OFFSET + 12] = struct.pack("<I", 1)
    head[PARTITION_TABLE_OFFSET + 12 : PARTITION_TABLE_OFFSET + 16] = struct.pack(
        "<I", min(total_sectors - 1, 0xFFFFFFFF)
    )
    head[510:512] = b"\x55\xaa"

    entries = [
        _independent_gpt_entry_bytes(*boot, "BOOT"),
        _independent_gpt_entry_bytes(*root, "root"),
        _independent_gpt_entry_bytes(*games, "EASYROMS"),
    ]
    entries_bytes = b"".join(entries) + b"\x00" * 128 * (128 - len(entries))
    header_sector = _independent_gpt_header_bytes(
        my_lba=1, alt_lba=total_sectors - 1, first_usable=34, last_usable=total_sectors - 34,
        part_entry_lba=2, entries_bytes=entries_bytes,
    )
    head[1 * SECTOR_SIZE : 2 * SECTOR_SIZE] = header_sector
    head[2 * SECTOR_SIZE : 2 * SECTOR_SIZE + len(entries_bytes)] = entries_bytes

    path = tmp_path / "independent_fake_source.img"
    with open(path, "wb") as f:
        f.write(bytes(head))
        f.seek(total_sectors * SECTOR_SIZE - 1)
        f.write(b"\x00")
    return str(path), total_sectors


def _independent_parse_mbr_lba0(data):
    assert data[510:512] == b"\x55\xaa"
    out = []
    for i in range(4):
        off = PARTITION_TABLE_OFFSET + i * 16
        ptype = data[off + 4]
        if ptype == 0:
            continue
        start_lba = struct.unpack_from("<I", data, off + 8)[0]
        sector_count = struct.unpack_from("<I", data, off + 12)[0]
        out.append((i, ptype, start_lba, sector_count))
    return out


def _independent_parse_gpt_header(sector):
    assert sector[0:8] == b"EFI PART"
    check = bytearray(sector[:92])
    stored_crc = struct.unpack_from("<I", check, 16)[0]
    check[16:20] = b"\x00\x00\x00\x00"
    header_crc_valid = stored_crc == (zlib.crc32(bytes(check)) & 0xFFFFFFFF)
    return dict(
        my_lba=struct.unpack_from("<Q", sector, 24)[0],
        alt_lba=struct.unpack_from("<Q", sector, 32)[0],
        last_usable=struct.unpack_from("<Q", sector, 48)[0],
        part_entry_lba=struct.unpack_from("<Q", sector, 72)[0],
        num_entries=struct.unpack_from("<I", sector, 80)[0],
        entry_size=struct.unpack_from("<I", sector, 84)[0],
        entry_crc=struct.unpack_from("<I", sector, 88)[0],
        header_crc_valid=header_crc_valid,
    )


@patch("r36s_studio.imaging.system_backup.list_partitions")
@patch("r36s_studio.imaging.system_backup.prepared_source", side_effect=_no_prep)
def test_backup_system_only_gpt_output_survives_fully_independent_structural_verification(
    mock_prep, mock_list, tmp_path
):
    """Bug rapporté sur du vrai matériel : aucune image `--system-only`
    n'a jamais démarré une console, sur macOS comme sur Windows -- pointe
    vers ce code de troncature/réparation, le seul que la sauvegarde
    complète (qui démarre, elle) n'exécute jamais. Contrairement aux tests
    ci-dessus, ni la construction du disque source ni la vérification de
    la sortie ne passent par `r36s_studio.imaging.gpt`/`mbr` -- struct
    pack/unpack à la main des deux côtés, pour éliminer tout risque qu'un
    bug de `build_gpt_header`/`build_gpt_entries` se retrouve identique
    dans la fixture de test et dans le code réparé, invisible à toute
    comparaison entre les deux."""
    source_path, total_sectors = _build_independent_fake_gpt_source(tmp_path)
    mock_list.return_value = _gpt_partition_labels(source_path)
    device = _make_device(source_path, total_sectors * SECTOR_SIZE)
    output_path = tmp_path / "independent_system_backup.img"

    backup_system_only(device, str(output_path))
    data = output_path.read_bytes()

    # LBA0 : le MBR protecteur doit décrire la taille réelle du fichier
    # produit, jamais celle du disque source (bug corrigé, §4.3).
    protective_entries = [e for e in _independent_parse_mbr_lba0(data) if e[1] == 0xEE]
    assert len(protective_entries) == 1
    _, _, start_lba, sector_count = protective_entries[0]
    assert (start_lba + sector_count) * SECTOR_SIZE == len(data)

    # LBA1 : en-tête primaire, CRC valide, AlternateLBA pointant sur la
    # fin réelle du fichier.
    primary = _independent_parse_gpt_header(data[SECTOR_SIZE : 2 * SECTOR_SIZE])
    assert primary["header_crc_valid"] is True
    assert (primary["alt_lba"] + 1) * SECTOR_SIZE == len(data)

    # En-tête secondaire, à l'emplacement annoncé par le primaire : CRC
    # valide, AlternateLBA pointant en retour sur le primaire (LBA1).
    secondary_lba = primary["alt_lba"]
    secondary = _independent_parse_gpt_header(data[secondary_lba * SECTOR_SIZE : (secondary_lba + 1) * SECTOR_SIZE])
    assert secondary["header_crc_valid"] is True
    assert secondary["alt_lba"] == 1
    assert secondary["last_usable"] == primary["last_usable"]

    # Tableau d'entrées primaire : CRC valide, exactement BOOT+root
    # (jamais EASYROMS), aucune entrée ne débordant du fichier produit.
    entries_off = primary["part_entry_lba"] * SECTOR_SIZE
    entries_bytes = data[entries_off : entries_off + primary["num_entries"] * primary["entry_size"]]
    assert (zlib.crc32(entries_bytes) & 0xFFFFFFFF) == primary["entry_crc"]
    kept = []
    for i in range(primary["num_entries"]):
        raw = entries_bytes[i * primary["entry_size"] : (i + 1) * primary["entry_size"]]
        if raw[0:16] == b"\x00" * 16:
            continue
        start_lba = struct.unpack_from("<Q", raw, 32)[0]
        end_lba = struct.unpack_from("<Q", raw, 40)[0]
        assert (end_lba + 1) * SECTOR_SIZE <= len(data)
        kept.append(start_lba)
    assert kept == [34, 134]
