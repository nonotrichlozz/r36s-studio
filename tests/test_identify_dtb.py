"""Parseur DTB pur Python (`identify/dtb.py`) : lit le magic FDT_MAGIC
(0xd00dfeed), le compatible racine, le compatible du nœud panel, et les
propriétés de timing d'affichage (entiers big-endian 32 bits)."""

from __future__ import annotations

import struct

import pytest

from r36s_studio.identify.dtb import DtbInfo, InvalidDtbError, parse_dtb

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 0x00000001
FDT_END_NODE = 0x00000002
FDT_PROP = 0x00000003
FDT_END = 0x00000009


def _align4(blob: bytes) -> bytes:
    pad = (-len(blob)) % 4
    return blob + b"\x00" * pad


def _begin_node(name: str) -> bytes:
    return _align4(struct.pack(">I", FDT_BEGIN_NODE) + name.encode("utf-8") + b"\x00")


def _end_node() -> bytes:
    return struct.pack(">I", FDT_END_NODE)


class _StringsBlock:
    def __init__(self) -> None:
        self._blob = b""
        self._offsets: dict[str, int] = {}

    def offset_for(self, name: str) -> int:
        if name not in self._offsets:
            self._offsets[name] = len(self._blob)
            self._blob += name.encode("utf-8") + b"\x00"
        return self._offsets[name]

    @property
    def blob(self) -> bytes:
        return self._blob


def _prop(strings: _StringsBlock, name: str, value: bytes) -> bytes:
    token = struct.pack(">I", FDT_PROP)
    header = struct.pack(">II", len(value), strings.offset_for(name))
    return _align4(token + header + value)


def _u32(value: int) -> bytes:
    return struct.pack(">I", value)


def _build_fake_dtb(
    *,
    board_compatible: str = "rk3326-evb-lp3-v12",
    panel_compatible: str = "sitronix,st7703",
    timings: dict[str, int] | None = None,
) -> bytes:
    """Construit un .dtb minimal à la main : nœud racine avec `compatible`,
    un enfant `panel@0` avec son propre `compatible` et ses propriétés de
    timing -- assez pour exercer `parse_dtb` sans dépendre d'un vrai
    fichier issu du matériel."""
    if timings is None:
        timings = {
            "hactive": 640,
            "vactive": 480,
            "clock-frequency": 25175000,
            "hfront-porch": 16,
            "hback-porch": 48,
            "hsync-len": 96,
            "vfront-porch": 10,
            "vback-porch": 33,
            "vsync-len": 2,
            "dsi,lanes": 4,
        }

    strings = _StringsBlock()
    struct_block = b""
    struct_block += _begin_node("")
    struct_block += _prop(strings, "compatible", board_compatible.encode("utf-8") + b"\x00")
    struct_block += _begin_node("panel@0")
    struct_block += _prop(strings, "compatible", panel_compatible.encode("utf-8") + b"\x00")
    for name, value in timings.items():
        struct_block += _prop(strings, name, _u32(value))
    struct_block += _end_node()
    struct_block += _end_node()
    struct_block += _u32(FDT_END)

    header_size = 40
    off_dt_struct = header_size
    off_dt_strings = off_dt_struct + len(struct_block)

    header = struct.pack(
        ">10I",
        FDT_MAGIC,
        off_dt_strings + len(strings.blob),  # totalsize
        off_dt_struct,
        off_dt_strings,
        header_size,  # off_mem_rsvmap (vide, juste après le header)
        17,  # version
        16,  # last_comp_version
        0,  # boot_cpuid_phys
        len(strings.blob),  # size_dt_strings
        len(struct_block),  # size_dt_struct
    )
    return header + struct_block + strings.blob


def test_parse_dtb_extracts_board_and_panel_compatible_and_timings():
    data = _build_fake_dtb()

    info = parse_dtb(data)

    assert info == DtbInfo(
        board_compatible="rk3326-evb-lp3-v12",
        panel_compatible="sitronix,st7703",
        timings={
            "hactive": 640,
            "vactive": 480,
            "clock-frequency": 25175000,
            "hfront-porch": 16,
            "hback-porch": 48,
            "hsync-len": 96,
            "vfront-porch": 10,
            "vback-porch": 33,
            "vsync-len": 2,
            "dsi,lanes": 4,
        },
    )


def test_parse_dtb_rejects_invalid_magic_without_raising_unhandled_exception():
    not_a_dtb = b"this is not a device tree blob at all, just plain text" * 4

    with pytest.raises(InvalidDtbError):
        parse_dtb(not_a_dtb)
