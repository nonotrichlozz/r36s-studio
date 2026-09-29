"""Tests de imaging/card_probe.py -- reconnaissance en lecture seule d'une
carte SF3000 (`cubegm/rkgame` sur la première partition), sur des images
construites selon les spécifications exFAT et FAT32 (jamais de vrai
périphérique : fichiers factices dans `tmp_path`)."""

from __future__ import annotations

import struct

import pytest

from r36s_studio.imaging.card_probe import first_partition_contains, is_sf3000_card
from r36s_studio.imaging.fat32 import format_fat32

SECTOR = 512
PART_START_LBA = 32  # comme la carte SF3000HD d'origine (16 Kio)


def _mbr(part_type: int, start_lba: int, sectors: int) -> bytes:
    mbr = bytearray(SECTOR)
    entry = bytearray(16)
    entry[4] = part_type
    entry[8:12] = struct.pack("<I", start_lba)
    entry[12:16] = struct.pack("<I", sectors)
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xaa"
    return bytes(mbr)


# --- construction d'une image exFAT minimale ----------------------------------

EX_BPS_SHIFT, EX_SPC_SHIFT = 9, 3  # 512 o/secteur, 8 secteurs/cluster
EX_CLUSTER = 1 << (EX_BPS_SHIFT + EX_SPC_SHIFT)
EX_FAT_OFFSET, EX_FAT_LENGTH, EX_HEAP_OFFSET, EX_CLUSTERS = 24, 8, 32, 64


def _exfat_file_entry(name: str, is_dir: bool, first_cluster: int, size: int, no_fat_chain: bool = True) -> bytes:
    utf16 = name.encode("utf-16-le")
    name_entries = []
    for k in range(0, len(utf16), 30):
        e = bytearray(32)
        e[0] = 0xC1
        chunk = utf16[k : k + 30]
        e[2 : 2 + len(chunk)] = chunk
        name_entries.append(bytes(e))
    primary = bytearray(32)
    primary[0] = 0x85
    primary[1] = 1 + len(name_entries)
    primary[4:6] = struct.pack("<H", 0x10 if is_dir else 0x20)
    stream = bytearray(32)
    stream[0] = 0xC0
    stream[1] = 0x01 | (0x02 if no_fat_chain else 0)
    stream[3] = len(name)
    stream[20:24] = struct.pack("<I", first_cluster)
    stream[24:32] = struct.pack("<Q", size)
    return bytes(primary) + bytes(stream) + b"".join(name_entries)


def _exfat_other_entries() -> bytes:
    """Bitmap (0x81), table de majuscules (0x82), étiquette (0x83) : présentes
    sur une vraie carte, à ignorer par la lecture."""
    out = b""
    for kind in (0x83, 0x81, 0x82):
        e = bytearray(32)
        e[0] = kind
        out += bytes(e)
    return out


def _build_exfat(path, root_entries: bytes, extra_clusters: dict, fat: dict, root_cluster: int = 4) -> None:
    part_sectors = EX_HEAP_OFFSET + EX_CLUSTERS * (EX_CLUSTER // SECTOR)
    img = bytearray((PART_START_LBA + part_sectors) * SECTOR)
    img[0:SECTOR] = _mbr(0x07, PART_START_LBA, part_sectors)
    base = PART_START_LBA * SECTOR
    boot = bytearray(SECTOR)
    boot[0:3] = b"\xeb\x76\x90"
    boot[3:11] = b"EXFAT   "
    boot[80:84] = struct.pack("<I", EX_FAT_OFFSET)
    boot[84:88] = struct.pack("<I", EX_FAT_LENGTH)
    boot[88:92] = struct.pack("<I", EX_HEAP_OFFSET)
    boot[92:96] = struct.pack("<I", EX_CLUSTERS)
    boot[96:100] = struct.pack("<I", root_cluster)
    boot[108], boot[109] = EX_BPS_SHIFT, EX_SPC_SHIFT
    boot[510:512] = b"\x55\xaa"
    img[base : base + SECTOR] = boot
    for cluster, value in fat.items():
        off = base + EX_FAT_OFFSET * SECTOR + cluster * 4
        img[off : off + 4] = struct.pack("<I", value)

    def put(cluster: int, data: bytes) -> None:
        off = base + EX_HEAP_OFFSET * SECTOR + (cluster - 2) * EX_CLUSTER
        img[off : off + len(data)] = data

    put(root_cluster, root_entries)
    for cluster, data in extra_clusters.items():
        put(cluster, data)
    path.write_bytes(bytes(img))


EOC = 0xFFFFFFFF


def _sf3000_exfat(path, cubegm_name="cubegm", rkgame_name="rkgame") -> None:
    root = _exfat_other_entries() + _exfat_file_entry("roms", True, 6, EX_CLUSTER) + _exfat_file_entry(cubegm_name, True, 5, EX_CLUSTER)
    cubegm = _exfat_file_entry("icube.sh", False, 7, 137) + _exfat_file_entry(rkgame_name, False, 8, 1181848)
    _build_exfat(path, root, {5: cubegm, 6: b""}, fat={4: EOC})


# --- FAT32 : formateur du projet + entrées ajoutées ----------------------------


def _fat32_dir_entry(short: bytes, attr: int, cluster: int, size: int = 0) -> bytes:
    e = bytearray(32)
    e[0:11] = short.ljust(11, b" ")
    e[11] = attr
    e[20:22] = struct.pack("<H", cluster >> 16)
    e[26:28] = struct.pack("<H", cluster & 0xFFFF)
    e[28:32] = struct.pack("<I", size)
    return bytes(e)


def _fat32_lfn(name: str, short: bytes) -> bytes:
    checksum = 0
    for c in short.ljust(11, b" "):
        checksum = (((checksum & 1) << 7) + (checksum >> 1) + c) & 0xFF
    chars = (name.encode("utf-16-le") + b"\x00\x00").ljust(26, b"\xff")
    e = bytearray(32)
    e[0] = 0x41  # dernier (et seul) morceau
    e[1:11] = chars[0:10]
    e[11] = 0x0F
    e[13] = checksum
    e[14:26] = chars[10:22]
    e[28:32] = chars[22:26]
    return bytes(e)


# Plus petit volume que le formateur du projet accepte en FAT32 (65 525
# clusters minimum) -- fichier creux : seuls quelques secteurs sont écrits.
FAT32_TEST_BYTES = 300 * 1024 * 1024


def _new_fat32(path) -> None:
    with open(path, "wb") as f:
        f.truncate(PART_START_LBA * SECTOR + FAT32_TEST_BYTES)
        f.seek(0)
        f.write(_mbr(0x0C, PART_START_LBA, FAT32_TEST_BYTES // SECTOR))
    format_fat32(str(path), PART_START_LBA * SECTOR, FAT32_TEST_BYTES, "SDCARD")


def _build_fat32(path, with_lfn: bool, rkgame: bool = True) -> None:
    _new_fat32(path)
    base = PART_START_LBA * SECTOR
    with open(path, "r+b") as f:
        f.seek(base)
        boot = f.read(SECTOR)
        bps = struct.unpack_from("<H", boot, 11)[0]
        spc = boot[13]
        reserved = struct.unpack_from("<H", boot, 14)[0]
        fat_size = struct.unpack_from("<I", boot, 36)[0]
        nfats = boot[16]
        root_cluster = struct.unpack_from("<I", boot, 44)[0]
        data_off = base + (reserved + nfats * fat_size) * bps
        cluster_size = bps * spc

        def cluster_off(c: int) -> int:
            return data_off + (c - 2) * cluster_size

        cub = 3 if root_cluster != 3 else 4
        for fat_index in range(nfats):
            f.seek(base + (reserved + fat_index * fat_size) * bps + cub * 4)
            f.write(struct.pack("<I", 0x0FFFFFFF))
        f.seek(cluster_off(root_cluster))
        root = f.read(cluster_size)
        pos = 0
        while root[pos] != 0:  # après l'étiquette de volume écrite par le formateur
            pos += 32
        entries = (_fat32_lfn("cubegm", b"CUBEGM") if with_lfn else b"") + _fat32_dir_entry(b"CUBEGM", 0x10, cub)
        f.seek(cluster_off(root_cluster) + pos)
        f.write(entries)
        if rkgame:
            inner = (_fat32_lfn("rkgame", b"RKGAME") if with_lfn else b"") + _fat32_dir_entry(b"RKGAME", 0x20, 0, 1181848)
            f.seek(cluster_off(cub))
            f.write(inner)


# --- tests --------------------------------------------------------------------


def test_exfat_sf3000_card_is_recognized(tmp_path):
    img = tmp_path / "sf3000.img"
    _sf3000_exfat(img)
    assert is_sf3000_card(str(img)) is True


def test_exfat_name_comparison_ignores_case(tmp_path):
    img = tmp_path / "sf3000.img"
    _sf3000_exfat(img, cubegm_name="CUBEGM", rkgame_name="RkGame")
    assert is_sf3000_card(str(img)) is True


def test_exfat_cubegm_without_rkgame_is_not_sf3000(tmp_path):
    img = tmp_path / "x.img"
    root = _exfat_other_entries() + _exfat_file_entry("cubegm", True, 5, EX_CLUSTER)
    _build_exfat(img, root, {5: _exfat_file_entry("icube.sh", False, 7, 137)}, fat={4: EOC})
    assert is_sf3000_card(str(img)) is False


def test_exfat_rkgame_at_the_root_is_not_enough(tmp_path):
    img = tmp_path / "x.img"
    root = _exfat_other_entries() + _exfat_file_entry("rkgame", False, 5, 10)
    _build_exfat(img, root, {}, fat={4: EOC})
    assert is_sf3000_card(str(img)) is False


def test_exfat_root_directory_spread_over_a_fat_chain(tmp_path):
    """Racine sur deux clusters non contigus (chaîne FAT 4 -> 9), `cubegm`
    dans le second -- une vraie racine chargée n'a aucune raison de tenir
    dans un seul cluster."""
    img = tmp_path / "x.img"
    filler = b"".join(_exfat_file_entry(f"jeu{i:02}", False, 20, 1) for i in range(EX_CLUSTER // 96))
    root_first = (_exfat_other_entries() + filler)[:EX_CLUSTER]
    # Remplit exactement le premier cluster sans couper une entrée en deux.
    root_first = root_first[: len(root_first) // 96 * 96]
    root_first = root_first.ljust(EX_CLUSTER, b"\x05")  # entrées « inutilisées » (type 0x05), ignorées
    second = _exfat_file_entry("cubegm", True, 5, EX_CLUSTER)
    cubegm = _exfat_file_entry("rkgame", False, 8, 1)
    _build_exfat(img, root_first, {9: second, 5: cubegm}, fat={4: 9, 9: EOC})
    assert is_sf3000_card(str(img)) is True


def test_exfat_fat_loop_does_not_hang(tmp_path):
    img = tmp_path / "x.img"
    _build_exfat(img, _exfat_other_entries(), {}, fat={4: 9, 9: 4})
    assert is_sf3000_card(str(img)) is False


@pytest.mark.parametrize("with_lfn", [False, True])
def test_fat32_treefrogui_card_is_recognized(tmp_path, with_lfn):
    img = tmp_path / "tf.img"
    _build_fat32(img, with_lfn=with_lfn)
    assert is_sf3000_card(str(img)) is True


def test_fat32_without_rkgame_is_not_sf3000(tmp_path):
    img = tmp_path / "tf.img"
    _build_fat32(img, with_lfn=True, rkgame=False)
    assert is_sf3000_card(str(img)) is False


def test_empty_fat32_is_not_sf3000(tmp_path):
    img = tmp_path / "vide.img"
    _new_fat32(img)
    assert is_sf3000_card(str(img)) is False


def test_linux_partition_arkos_like_is_not_sf3000(tmp_path):
    """Première partition ni exFAT ni FAT32 (ext4 d'ArkOS, par exemple)."""
    img = tmp_path / "arkos.img"
    data = bytearray((PART_START_LBA + 64) * SECTOR)
    data[0:SECTOR] = _mbr(0x83, PART_START_LBA, 64)
    img.write_bytes(bytes(data))
    assert is_sf3000_card(str(img)) is False


def test_gpt_disk_is_not_sf3000(tmp_path):
    img = tmp_path / "gpt.img"
    data = bytearray(64 * SECTOR)
    data[0:SECTOR] = _mbr(0xEE, 1, 63)
    img.write_bytes(bytes(data))
    assert is_sf3000_card(str(img)) is False


@pytest.mark.parametrize("content", [b"", b"\x00" * 100, b"\x00" * SECTOR])
def test_unreadable_or_truncated_device_never_raises(tmp_path, content):
    img = tmp_path / "vide.img"
    img.write_bytes(content)
    assert is_sf3000_card(str(img)) is False


def test_missing_device_never_raises(tmp_path):
    assert is_sf3000_card(str(tmp_path / "absent.img")) is False


def test_partition_boot_sector_beyond_end_of_device_never_raises(tmp_path):
    img = tmp_path / "coupe.img"
    img.write_bytes(_mbr(0x07, 10_000, 100))
    assert first_partition_contains(str(img)) is False
