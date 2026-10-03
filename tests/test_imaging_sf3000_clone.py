"""Tests de « utiliser toute la carte » (carte SF3000) : lecteur exFAT
(`imaging/exfat_reader.py`), disposition, copie et vérification
(`imaging/sf3000_clone.py`), commande `clone-sf3000`. Images exFAT
construites selon la spécification dans `tmp_path` ; aucun vrai
périphérique (écriture brute et formatage mockés).

`R36S_SF3000_IMAGE=<chemin d'une vraie image .img>` active en plus un test
en lecture seule sur une vraie carte SF3000 sauvegardée."""

from __future__ import annotations

import hashlib
import math
import os
import struct
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging import sf3000_clone
from r36s_studio.imaging.copy import OperationCancelled
from r36s_studio.imaging.exfat_reader import ExFatError, ExFatVolume, first_partition_start

SECTOR = 512
PART_LBA = 32
CLUSTER = 4096
CLUSTERS = 128
FAT_OFFSET, HEAP_OFFSET = 24, 32  # en secteurs
EOC = 0xFFFFFFFF


def _stamp(y, mo, d, h, mi, s) -> int:
    return ((y - 1980) << 25) | (mo << 21) | (d << 16) | (h << 11) | (mi << 5) | (s // 2)


def _file_set(name, is_dir, first, size, no_fat_chain, attrs=0, stamp=0, utc=0, valid=None) -> bytes:
    utf16 = name.encode("utf-16-le")
    names = []
    for k in range(0, len(utf16), 30):
        e = bytearray(32)
        e[0] = 0xC1
        e[2 : 2 + len(utf16[k : k + 30])] = utf16[k : k + 30]
        names.append(bytes(e))
    primary = bytearray(32)
    primary[0], primary[1] = 0x85, 1 + len(names)
    primary[4:6] = struct.pack("<H", attrs | (0x10 if is_dir else 0x20))
    primary[12:16] = struct.pack("<I", stamp)
    primary[23] = utc
    stream = bytearray(32)
    stream[0], stream[1], stream[3] = 0xC0, 0x01 | (0x02 if no_fat_chain else 0), len(name)
    stream[8:16] = struct.pack("<Q", size if valid is None else valid)
    stream[20:24] = struct.pack("<I", first)
    stream[24:32] = struct.pack("<Q", size)
    return bytes(primary) + bytes(stream) + b"".join(names)


def build_image(path, tree, label="", disk_signature=b"\x12\x34\x56\x78"):
    """`tree` : liste de ("dir", nom, enfants) / ("file", nom, données, options)."""
    heap = {}
    fat = {2: EOC, 3: EOC, 4: EOC}
    used = {2, 3, 4}
    state = {"next": 5}

    def alloc(n, fragmented):
        clusters = []
        for _ in range(n):
            clusters.append(state["next"])
            state["next"] += 2 if fragmented else 1
        used.update(clusters)
        return clusters

    def store(data, fragmented=False, force_one=False):
        n = max(1 if force_one else 0, math.ceil(len(data) / CLUSTER))
        if n == 0:
            return 0
        clusters = alloc(n, fragmented)
        for i, c in enumerate(clusters):
            heap[c] = data[i * CLUSTER : (i + 1) * CLUSTER]
            if fragmented:
                fat[c] = clusters[i + 1] if i + 1 < len(clusters) else EOC
        return clusters[0]

    def entries(nodes):
        out = b""
        for node in nodes:
            if node[0] == "dir":
                data = entries(node[2])
                first = store(data, force_one=True)
                out += _file_set(node[1], True, first, max(1, math.ceil(len(data) / CLUSTER)) * CLUSTER, True, stamp=_stamp(2024, 1, 2, 3, 4, 6))
            else:
                _, name, data, opts = node
                first = store(data, opts.get("fragmented", False))
                out += _file_set(
                    name, False, first, len(data), not opts.get("fragmented", False),
                    attrs=opts.get("attrs", 0), stamp=opts.get("stamp", 0), utc=opts.get("utc", 0),
                    valid=opts.get("valid"),
                )
        return out

    body = entries(tree)
    special = bytearray(32 * 3)
    special[0], special[1] = 0x83, len(label)
    special[2 : 2 + 2 * len(label)] = label.encode("utf-16-le")
    special[32] = 0x81
    special[32 + 20 : 32 + 24] = struct.pack("<I", 2)
    special[32 + 24 : 32 + 32] = struct.pack("<Q", CLUSTERS // 8)
    special[64] = 0x82
    heap[4] = bytes(special) + body
    assert len(heap[4]) <= CLUSTER
    bitmap = bytearray(CLUSTERS // 8)
    for c in used:
        bitmap[(c - 2) // 8] |= 1 << ((c - 2) % 8)
    heap[2] = bytes(bitmap)

    part_sectors = HEAP_OFFSET + CLUSTERS * (CLUSTER // SECTOR)
    img = bytearray((PART_LBA + part_sectors) * SECTOR)
    img[440:444] = disk_signature
    entry = bytearray(16)
    entry[4] = 0x07
    entry[8:12] = struct.pack("<I", PART_LBA)
    entry[12:16] = struct.pack("<I", part_sectors)
    img[446:462] = entry
    img[510:512] = b"\x55\xaa"
    base = PART_LBA * SECTOR
    boot = bytearray(SECTOR)
    boot[3:11] = b"EXFAT   "
    boot[72:80] = struct.pack("<Q", part_sectors)
    boot[80:84] = struct.pack("<I", FAT_OFFSET)
    boot[88:92] = struct.pack("<I", HEAP_OFFSET)
    boot[92:96] = struct.pack("<I", CLUSTERS)
    boot[96:100] = struct.pack("<I", 4)
    boot[108], boot[109] = 9, 3
    boot[510:512] = b"\x55\xaa"
    img[base : base + SECTOR] = boot
    for c, v in fat.items():
        off = base + FAT_OFFSET * SECTOR + c * 4
        img[off : off + 4] = struct.pack("<I", v)
    for c, data in heap.items():
        off = base + HEAP_OFFSET * SECTOR + (c - 2) * CLUSTER
        img[off : off + len(data)] = data
    path.write_bytes(bytes(img))
    return used


BIG = bytes(range(256)) * 50  # 12 800 octets : 4 clusters
FRAG = b"frag" * 3000  # 12 000 octets, clusters non contigus


def sf3000_tree():
    return [
        ("dir", "cubegm", [
            ("file", "rkgame", b"\x7fELF" + b"r" * 5000, {"stamp": _stamp(2024, 5, 6, 10, 20, 30), "utc": 0x80 | 8}),
            ("file", "icube.sh", b"#!/bin/sh\n", {}),
        ]),
        ("dir", "roms", [
            ("dir", "GBA", [("file", "Jeu très long.gba", BIG, {})]),
            ("file", "fragmente.bin", FRAG, {"fragmented": True}),
            ("file", "vide.txt", b"", {}),
        ]),
        ("dir", "MD", [("file", "dummy.md", b"md", {"attrs": 0x02})]),
        ("dir", "System Volume Information", [("file", "IndexerVolumeGuid", b"guid", {})]),
    ]


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "sf3000.img"
    build_image(path, sf3000_tree())
    return path


def _volume(f):
    return ExFatVolume(f, first_partition_start(f))


# --- lecteur exFAT -----------------------------------------------------------


def test_walk_lists_the_whole_tree_folders_before_their_content(image):
    with open(image, "rb") as f:
        paths = ["/".join(e.parts) for e in _volume(f).walk()]
    assert paths.index("roms") < paths.index("roms/GBA") < paths.index("roms/GBA/Jeu très long.gba")
    assert "cubegm/rkgame" in paths and "roms/vide.txt" in paths and "MD/dummy.md" in paths


def test_read_file_contiguous_fragmented_and_empty(image):
    with open(image, "rb") as f:
        volume = _volume(f)
        entries = {"/".join(e.parts): e for e in volume.walk()}
        read = lambda p: b"".join(volume.read_file(entries[p], chunk_size=CLUSTER * 2))  # noqa: E731
        assert read("roms/GBA/Jeu très long.gba") == BIG
        assert read("roms/fragmente.bin") == FRAG
        assert read("roms/vide.txt") == b""


def test_bytes_past_valid_length_read_as_zeros(tmp_path):
    path = tmp_path / "v.img"
    build_image(path, [("dir", "cubegm", [("file", "rkgame", b"a" * 100, {"valid": 40})])])
    with open(path, "rb") as f:
        volume = _volume(f)
        entry = [e for e in volume.walk() if e.parts[-1] == "rkgame"][0]
        assert b"".join(volume.read_file(entry)) == b"a" * 40 + b"\x00" * 60


def test_modification_time_uses_the_utc_offset(image):
    with open(image, "rb") as f:
        entry = [e for e in _volume(f).walk() if e.parts == ("cubegm", "rkgame")][0]
    # 10:20:30 à UTC+2 (8 quarts d'heure) = 08:20:30 UTC.
    assert entry.mtime == datetime(2024, 5, 6, 8, 20, 30, tzinfo=timezone.utc).timestamp()


def test_used_bytes_and_label(tmp_path):
    path = tmp_path / "l.img"
    used = build_image(path, sf3000_tree(), label="SF3000")
    with open(path, "rb") as f:
        volume = _volume(f)
        assert volume.used_bytes() == len(used) * CLUSTER
        assert volume.label == "SF3000"


def test_looping_fat_chain_raises_instead_of_hanging(tmp_path):
    path = tmp_path / "loop.img"
    build_image(path, [("dir", "cubegm", [("file", "rkgame", FRAG, {"fragmented": True})])])
    with open(path, "rb") as f:
        volume = _volume(f)
        entry = [e for e in volume.walk() if e.parts[-1] == "rkgame"][0]
    data = bytearray(path.read_bytes())
    off = PART_LBA * SECTOR + FAT_OFFSET * SECTOR + entry.first_cluster * 4
    data[off : off + 4] = struct.pack("<I", 1)  # cluster invalide au milieu de la chaîne
    path.write_bytes(bytes(data))
    with open(path, "rb") as f:
        with pytest.raises(ExFatError):
            b"".join(_volume(f).read_file(entry))


# --- image SF3000 : reconnaissance et inventaire -----------------------------


def test_image_without_rkgame_is_not_an_sf3000_image(tmp_path):
    path = tmp_path / "autre.img"
    build_image(path, [("dir", "roms", [])])
    with pytest.raises(sf3000_clone.NotSf3000Image):
        with sf3000_clone.open_sf3000_image(str(path)):
            pass


def test_scan_skips_system_volume_information_and_counts(image):
    with sf3000_clone.open_sf3000_image(str(image)) as (_f, volume):
        content = sf3000_clone.scan_image(volume)
    paths = {"/".join(e.parts) for e in content.entries}
    assert not any(p.startswith("System Volume Information") for p in paths)
    assert content.file_count == 6
    assert content.total_bytes == 5004 + 10 + len(BIG) + len(FRAG) + 0 + 2


def test_scan_refuses_names_windows_cannot_create_before_any_write(tmp_path):
    path = tmp_path / "noms.img"
    build_image(path, [("dir", "cubegm", [("file", "rkgame", b"x", {}), ("file", "AUX.txt", b"x", {}), ("file", "fin.", b"x", {})])])
    with sf3000_clone.open_sf3000_image(str(path)) as (_f, volume):
        with pytest.raises(sf3000_clone.InvalidFileNames) as exc:
            sf3000_clone.scan_image(volume)
    assert exc.value.names == ["cubegm/AUX.txt", "cubegm/fin."]


@pytest.mark.parametrize("name,invalid", [
    ("Sonic.md", False), ("CON", True), ("com1.txt", True), ("a?b", True), ("espace ", True), ("CONSOLE.txt", False),
])
def test_invalid_windows_names(name, invalid):
    assert sf3000_clone.is_invalid_windows_name(name) is invalid


# --- disposition de la carte --------------------------------------------------


def _device(size_bytes=128 * 1024**3, path="\\\\.\\PhysicalDrive9902", mountpoints=None) -> Device:
    return Device(path=path, display="Carte factice", size_bytes=size_bytes, removable=True, bus="USB",
                  is_system=False, mountpoints=mountpoints or [])


def test_head_keeps_disk_signature_and_has_a_single_whole_card_entry(image):
    device = _device()
    head = sf3000_clone.build_head(image.read_bytes()[: sf3000_clone.HEAD_BYTES], device)
    assert len(head) == 16 * 1024
    assert head[440:444] == b"\x12\x34\x56\x78"
    entry = head[446:462]
    assert entry[4] == 0x07
    assert struct.unpack("<I", entry[8:12])[0] == 32
    count = struct.unpack("<I", entry[12:16])[0]
    assert count == sf3000_clone.partition_sector_count(device)
    assert (32 + count) * SECTOR == device.size_bytes - 1024 * 1024  # 1 Mio laissé en fin de carte
    assert head[462:510] == bytes(48)
    assert head[512:] == bytes(len(head) - 512)


def test_whole_card_offered_only_on_windows_for_a_bigger_card(image, monkeypatch):
    size = os.path.getsize(image)
    monkeypatch.setattr(sf3000_clone.platform, "system", lambda: "Linux")
    assert sf3000_clone.whole_card_used_bytes(str(image), _device(size + 2 * 1024**3)) is None
    monkeypatch.setattr(sf3000_clone.platform, "system", lambda: "Windows")
    assert sf3000_clone.whole_card_used_bytes(str(image), _device(size + 1024)) is None
    assert sf3000_clone.whole_card_used_bytes(str(image), _device(size + 2 * 1024**3)) > 0


def test_duration_estimates_are_whole_positive_minutes():
    used = int(46.5 * 1024**3)
    assert sf3000_clone.extra_minutes_vs_raw(used, int(45.4 * 1024**3)) >= 1
    assert sf3000_clone.verify_minutes(used) == math.ceil(used / sf3000_clone.VERIFY_BYTES_PER_SECOND / 60)
    assert sf3000_clone.total_minutes(used) > sf3000_clone.total_minutes(used, verify=False)


# --- copie et vérification -------------------------------------------------


def _copy(image, dest, **kwargs):
    with sf3000_clone.open_sf3000_image(str(image)) as (_f, volume):
        content = sf3000_clone.scan_image(volume)
        return content, sf3000_clone.copy_files(volume, content, str(dest), **kwargs)


def test_copy_recreates_files_dates_and_hashes(image, tmp_path):
    dest = tmp_path / "carte"
    dest.mkdir()
    content, hashes = _copy(image, dest)
    assert (dest / "roms" / "GBA" / "Jeu très long.gba").read_bytes() == BIG
    assert (dest / "roms" / "fragmente.bin").read_bytes() == FRAG
    assert (dest / "roms" / "vide.txt").read_bytes() == b""
    assert not (dest / "System Volume Information").exists()
    rkgame = dest / "cubegm" / "rkgame"
    assert rkgame.stat().st_mtime == datetime(2024, 5, 6, 8, 20, 30, tzinfo=timezone.utc).timestamp()
    assert hashes[("roms", "GBA", "Jeu très long.gba")] == hashlib.sha256(BIG).hexdigest()
    sf3000_clone.verify_files(hashes, str(dest), content.total_bytes)


def test_verify_reports_the_first_different_file(image, tmp_path):
    dest = tmp_path / "carte"
    dest.mkdir()
    content, hashes = _copy(image, dest)
    (dest / "roms" / "fragmente.bin").write_bytes(b"abime")
    with pytest.raises(sf3000_clone.VerifyMismatch) as exc:
        sf3000_clone.verify_files(hashes, str(dest), content.total_bytes)
    assert exc.value.path == "roms/fragmente.bin"


def test_copy_can_be_cancelled(image, tmp_path):
    dest = tmp_path / "carte"
    dest.mkdir()
    with pytest.raises(OperationCancelled):
        _copy(image, dest, should_cancel=lambda: True)


def test_progress_reports_real_bytes_up_to_the_total(image, tmp_path):
    dest = tmp_path / "carte"
    dest.mkdir()
    events = []
    content, _ = _copy(image, dest, on_progress=events.append)
    assert events[-1].done == events[-1].total == content.total_bytes


def test_set_attributes_keeps_only_dos_bits_and_calls_windows_api(monkeypatch):
    """`ctypes.windll` simulé (create=True) : tourne aussi sur Linux/macOS."""
    import ctypes

    monkeypatch.setattr(sf3000_clone.platform, "system", lambda: "Windows")
    with patch.object(ctypes, "windll", create=True) as windll:
        windll.kernel32.SetFileAttributesW.return_value = 1
        sf3000_clone._set_attributes("Z:\f", sf3000_clone.ATTR_HIDDEN | 0x20)
        windll.kernel32.SetFileAttributesW.assert_called_once_with("Z:\f", sf3000_clone.ATTR_HIDDEN)

        windll.kernel32.SetFileAttributesW.return_value = 0
        with pytest.raises(OSError):
            sf3000_clone._set_attributes("Z:\f", sf3000_clone.ATTR_SYSTEM)


def test_marker_round_trip(tmp_path):
    sf3000_clone.write_marker(str(tmp_path))
    assert sf3000_clone.has_marker(str(tmp_path))
    sf3000_clone.remove_marker(str(tmp_path))
    assert not sf3000_clone.has_marker(str(tmp_path))


# --- commande clone-sf3000 ----------------------------------------------------


def _run(image, device, tmp_path, extra=(), probe=True):
    """Lance la commande avec l'écriture brute, le formatage et le démontage
    mockés ; la « carte » est un dossier de `tmp_path`."""
    card = tmp_path / "carte"
    card.mkdir(exist_ok=True)
    with patch.object(cli.platform, "system", return_value="Windows"), \
         patch("r36s_studio.__main__.list_devices", return_value=[device]), \
         patch.object(sf3000_clone, "write_layout") as layout, \
         patch.object(sf3000_clone, "format_whole_card", return_value="Z") as fmt, \
         patch.object(sf3000_clone, "drop_volume_cache"), \
         patch.object(sf3000_clone, "long_path_root", return_value=str(card)),          patch.object(sf3000_clone, "_set_attributes"), \
         patch("r36s_studio.__main__.is_sf3000_card", return_value=probe), \
         patch("r36s_studio.__main__.eject_device") as eject:
        args = cli.build_parser().parse_args(
            ["clone-sf3000", "--image", str(image), "--device", device.path, "--worker", *extra]
        )
        code = args.func(args)
    return code, card, layout, fmt, eject


def test_cli_clone_copies_verifies_and_removes_the_marker(image, tmp_path, capsys):
    code, card, layout, fmt, eject = _run(image, _device(), tmp_path, extra=["--eject-after"])
    out = capsys.readouterr().out
    assert code == 0, out
    head = layout.call_args[0][1]
    assert head[446 + 4] == 0x07
    fmt.assert_called_once()
    assert (card / "cubegm" / "rkgame").exists()
    assert not sf3000_clone.has_marker(str(card))
    assert "Vérification SHA-256 réussie" in out
    eject.assert_called_once()
    assert '"ok": true' in out


def test_cli_clone_without_verify_says_so(image, tmp_path, capsys):
    code, *_ = _run(image, _device(), tmp_path, extra=["--no-verify"])
    out = capsys.readouterr().out
    assert code == 0
    assert "Vérification des fichiers désactivée" in out


def test_cli_clone_refuses_bad_names_before_writing(tmp_path, capsys):
    path = tmp_path / "noms.img"
    build_image(path, [("dir", "cubegm", [("file", "rkgame", b"x", {}), ("file", "NUL", b"x", {})])])
    code, _card, layout, _fmt, _ej = _run(path, _device(), tmp_path)
    assert code == 1
    layout.assert_not_called()
    assert "INVALID_FILE_NAMES" in capsys.readouterr().out


def test_cli_clone_refuses_a_card_too_small_before_writing(image, tmp_path, capsys):
    code, _card, layout, _fmt, _ej = _run(image, _device(size_bytes=40 * 1024**2), tmp_path)
    assert code == 1
    layout.assert_not_called()
    assert "DESTINATION_TOO_SMALL" in capsys.readouterr().out


def test_cli_clone_refuses_a_non_sf3000_image(tmp_path, capsys):
    path = tmp_path / "autre.img"
    build_image(path, [("dir", "roms", [])])
    code, _card, layout, _fmt, _ej = _run(path, _device(), tmp_path)
    assert code == 1
    layout.assert_not_called()
    assert "NOT_SF3000_IMAGE" in capsys.readouterr().out


def test_cli_clone_copy_failure_leaves_the_marker(image, tmp_path, capsys):
    with patch.object(sf3000_clone, "copy_files", side_effect=OSError("carte retirée")):
        code, card, *_ = _run(image, _device(), tmp_path)
    assert code == 1
    assert sf3000_clone.has_marker(str(card))
    assert "WHOLE_CARD_COPY_FAILED" in capsys.readouterr().out


def test_cli_clone_is_windows_only(image, capsys):
    with patch.object(cli.platform, "system", return_value="Linux"):
        args = cli.build_parser().parse_args(["clone-sf3000", "--image", str(image), "--device", "/dev/fake-disk-test-1"])
        assert args.func(args) == 1
    assert "UNSUPPORTED_OS" in capsys.readouterr().out


# --- vraie image (optionnel) ---------------------------------------------------


@pytest.mark.skipif(not os.environ.get("R36S_SF3000_IMAGE"), reason="R36S_SF3000_IMAGE non défini")
def test_real_sf3000_image_can_be_listed_read_only():
    with sf3000_clone.open_sf3000_image(os.environ["R36S_SF3000_IMAGE"]) as (_f, volume):
        content = sf3000_clone.scan_image(volume)
        assert content.file_count > 0
        assert content.total_bytes <= volume.used_bytes()


def test_write_layout_writes_head_and_blanks_new_partition_start_and_card_end(image, tmp_path, monkeypatch):
    import contextlib

    card = tmp_path / "carte.bin"
    card.write_bytes(b"\xaa" * (8 * 1024 * 1024))
    device = _device(size_bytes=8 * 1024 * 1024)

    @contextlib.contextmanager
    def fake_target(_device):
        yield str(card)

    monkeypatch.setattr(sf3000_clone, "prepared_write_target", fake_target)
    monkeypatch.setattr(sf3000_clone.platform, "system", lambda: "Linux")
    head = sf3000_clone.build_head(image.read_bytes()[: sf3000_clone.HEAD_BYTES], device)
    sf3000_clone.write_layout(device, head)

    data = card.read_bytes()
    mib = 1024 * 1024
    assert data[: len(head)] == head
    assert data[len(head) : len(head) + mib] == bytes(mib)  # ancien secteur de démarrage effacé
    assert data[len(head) + mib : -mib] == b"\xaa" * (len(data) - len(head) - 2 * mib)
    assert data[-mib:] == bytes(mib)
