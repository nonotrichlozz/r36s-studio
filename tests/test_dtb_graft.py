"""Greffe des réglages d'écran sur une carte KNULLI R36S
(`partitions/dtb_graft.py`, `boot_sets._apply_knulli_screen`,
`screen_backup.knulli_donor`). Cas réel du 2026-10-20 (R36S noire
d'origine) : le .dtb noyau d'usine posé tel quel empêchait KNULLI de
démarrer ; ses seuls réglages d'écran greffés dans le .dtb de KNULLI ont
fait démarrer la console avec l'image. Les .dtb sont construits ici au vrai
format FDT, avec la même structure que les fichiers relevés
(`/dsi@ff450000/panel@0`, `display-timings/60Hz`)."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from r36s_studio.partitions import boot_sets, dtb_graft, screen_backup


def _u32(value: int) -> bytes:
    return struct.pack(">I", value)


def build_dtb(tree: dict) -> bytes:
    """`tree` : {nom de propriété: bytes, nom de nœud: dict}, racine sans nom."""
    strings = bytearray()
    offsets: dict = {}

    def name_offset(name: str) -> int:
        if name not in offsets:
            offsets[name] = len(strings)
            strings.extend(name.encode() + b"\0")
        return offsets[name]

    def node(name: str, content: dict) -> bytes:
        raw = name.encode() + b"\0"
        out = _u32(1) + raw + b"\0" * ((-len(raw)) % 4)
        for key, value in content.items():
            if isinstance(value, bytes):
                out += _u32(3) + _u32(len(value)) + _u32(name_offset(key)) + value + b"\0" * ((-len(value)) % 4)
        for key, value in content.items():
            if isinstance(value, dict):
                out += node(key, value)
        return out + _u32(2)

    structure = node("", tree) + _u32(9)
    rsv = b"\0" * 16
    off_rsv = 40
    off_struct = off_rsv + len(rsv)
    off_strings = off_struct + len(structure)
    total = off_strings + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, off_struct, off_strings, off_rsv, 17, 16, 0, len(strings), len(structure))
    return header + rsv + structure + bytes(strings)


def knulli_like(model: bytes = b"Game Console R35S/R36S fix by lxc\0") -> dict:
    return {
        "model": model,
        "joypad": {"compatible": b"odroidgo3-joypad\0", "poll-interval": _u32(10)},
        "dsi@ff450000": {
            "status": b"okay\0",
            "panel@0": {
                "compatible": b"elida,kd35t133\0",
                "reset-delay-ms": _u32(150),
                "panel-init-sequence": b"\x15\x00\x02\xff\x30" * 40,
                "display-timings": {
                    "native-mode": _u32(0xA00),
                    "60Hz": {"clock-frequency": _u32(29000000), "hback-porch": _u32(44), "phandle": _u32(0xA00)},
                },
            },
        },
    }


def factory_like(init: bytes = b"\x39\x00\x04\xb9\xf1\x12\x83") -> dict:
    return {
        "model": b"Hardkernel ODROID-GO3\0",
        "joypad": {"compatible": b"odroidgo3-joypad\0", "poll-interval": _u32(99)},
        "dsi@ff450000": {
            "status": b"okay\0",
            "panel@0": {
                "compatible": b"elida,kd35t133\0",
                "reset-delay-ms": _u32(1),
                "panel-init-sequence": init,
                "only-in-factory": b"x",
                "display-timings": {
                    "native-mode": _u32(0x10D),
                    "60Hz": {"clock-frequency": _u32(50000000), "hback-porch": _u32(450), "phandle": _u32(0x10D)},
                },
            },
        },
    }


PANEL = "/dsi@ff450000/panel@0"


def test_graft_replaces_only_the_screen_settings():
    base, donor = build_dtb(knulli_like()), build_dtb(factory_like())

    result = dtb_graft.graft_panel(base, donor)

    props, before, wanted = dtb_graft.properties(result), dtb_graft.properties(base), dtb_graft.properties(donor)
    assert set(props) == set(before)  # aucun nœud ni propriété ajouté (« only-in-factory » non plus)
    assert props[(PANEL, "panel-init-sequence")] == wanted[(PANEL, "panel-init-sequence")]
    assert props[(PANEL, "reset-delay-ms")] == _u32(1)
    assert props[(PANEL + "/display-timings/60Hz", "clock-frequency")] == _u32(50000000)
    # phandle et native-mode (référence à un phandle) : ceux de KNULLI (ils désignent ses propres nœuds)
    assert props[(PANEL + "/display-timings/60Hz", "phandle")] == _u32(0xA00)
    assert props[(PANEL + "/display-timings", "native-mode")] == _u32(0xA00)
    # hors de l'écran : rien ne change, modèle compris
    assert props[("", "model")] == before[("", "model")]
    assert props[("/joypad", "poll-interval")] == _u32(10)


def test_graft_is_idempotent_and_refuses_unknown_files():
    base, donor = build_dtb(knulli_like()), build_dtb(factory_like())
    once = dtb_graft.graft_panel(base, donor)
    assert dtb_graft.graft_panel(once, donor) == once
    assert dtb_graft.graft_panel(base, b"pas un dtb") is None
    no_panel = factory_like()
    del no_panel["dsi@ff450000"]["panel@0"]["panel-init-sequence"]
    assert dtb_graft.graft_panel(base, build_dtb(no_panel)) is None
    assert dtb_graft.has_panel(donor) and not dtb_graft.has_panel(b"x")


def _knulli_card(root: Path) -> bytes:
    (root / "boot").mkdir(parents=True)
    (root / "rk3326-odroidgo2-linux.dtb").write_bytes(b"u-boot")
    (root / "boot" / "knulli.board").write_bytes(b"r36s\n")
    original = build_dtb(knulli_like())
    (root / "boot" / "rk3326-rg351mp-linux.dtb").write_bytes(original)
    return original


def test_choose_screen_on_knulli_grafts_from_the_original_knulli_dtb(tmp_path):
    card = tmp_path / "card"
    original = _knulli_card(card)
    for name, init in (("dalle-a", b"\x39\xaa"), ("dalle-b", b"\x39\xbb")):
        (card / name).mkdir()
        (card / name / "rk3326-r35s-linux.dtb").write_bytes(build_dtb(factory_like(init)))
    target = card / "boot" / "rk3326-rg351mp-linux.dtb"

    boot_sets.apply_set(card, "dalle-a")
    assert dtb_graft.properties(target.read_bytes())[(PANEL, "panel-init-sequence")] == b"\x39\xaa"
    assert dtb_graft.properties(target.read_bytes())[("", "model")] == b"Game Console R35S/R36S fix by lxc\0"

    boot_sets.apply_set(card, "dalle-b")  # repart du .dtb de KNULLI d'origine, pas de la dalle A
    assert target.read_bytes() == dtb_graft.graft_panel(original, build_dtb(factory_like(b"\x39\xbb")))
    assert (card / "rk3326-odroidgo2-linux.dtb").read_bytes() == b"u-boot"

    boot_sets.restore_original(card)
    assert target.read_bytes() == original


def test_knulli_donor_uses_boot_ini_and_accepts_clone_names(tmp_path):
    arkos = tmp_path / "arkos"  # BOOT ArkOS d'usine réel : deux .dtb noyau
    arkos.mkdir()
    (arkos / "rk3326-r35s-linux.dtb").write_bytes(build_dtb(factory_like()))
    (arkos / "rk3326-rg351mp-linux.dtb").write_bytes(build_dtb(factory_like()))
    (arkos / "rg351mp-kernel.dtb").write_bytes(b"u-boot usine")
    assert screen_backup.knulli_donor(arkos) is None  # sans boot.ini : on ne devine pas
    (arkos / "boot.ini").write_text("load mmc 1:1 ${dtb_loadaddr} rk3326-r35s-linux.dtb\n")
    assert screen_backup.knulli_donor(arkos) == "rk3326-r35s-linux.dtb"

    clone = tmp_path / "clone"  # autres noms : on garde le seul .dtb qui décrit un écran
    clone.mkdir()
    (clone / "rf3536k4ka.dtb").write_bytes(build_dtb(factory_like()))
    (clone / "rk3326-odroidgo2-linux.dtb").write_bytes(build_dtb(factory_like()))
    (clone / "autre.dtb").write_bytes(b"illisible")
    assert screen_backup.knulli_donor(clone) == "rf3536k4ka.dtb"

    card = tmp_path / "card"
    _knulli_card(card)
    assert screen_backup.install_original_screen(clone, card) == {"rf3536k4ka.dtb": "rk3326-rg351mp-linux.dtb"}


def test_save_retries_a_rename_blocked_by_windows(tmp_path, monkeypatch):
    boot = tmp_path / "boot"
    boot.mkdir()
    (boot / "rk3326-r35s-linux.dtb").write_bytes(b"k")
    real_rename = Path.rename
    failures = []

    def flaky(self, target):
        if len(failures) < 2:
            failures.append(self)
            raise PermissionError("fichier ouvert par l'indexeur")
        return real_rename(self, target)

    monkeypatch.setattr(Path, "rename", flaky)
    monkeypatch.setattr(screen_backup.time, "sleep", lambda s: None)
    folder, created = screen_backup.save_original_screen(boot, tmp_path / "b", "12" * 32)
    assert created and folder.is_dir() and not folder.name.endswith(".partiel")
    assert len(failures) == 2
