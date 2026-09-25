"""Octets d'en-tête factices pour les tests du tri (docs/tri-roms.md) --
juste assez pour satisfaire chaque signature, jamais une vraie ROM."""

from __future__ import annotations

import zipfile
from pathlib import Path

from r36s_studio.tri.identify import _CD_SYNC, _GB_LOGO, _GBA_LOGO_PREFIX


def _pad(prefix: bytes, size: int = 0x400) -> bytearray:
    data = bytearray(size)
    data[: len(prefix)] = prefix
    return data


def nes() -> bytes:
    return bytes(_pad(b"NES\x1a"))


def fds() -> bytes:
    return bytes(_pad(b"FDS\x1a"))


def gb() -> bytes:
    data = _pad(b"")
    data[0x104:0x134] = _GB_LOGO
    return bytes(data)


def gba() -> bytes:
    data = _pad(b"")
    data[0x04:0x08] = _GBA_LOGO_PREFIX
    data[0xB2] = 0x96
    return bytes(data)


def n64() -> bytes:
    return bytes(_pad(bytes.fromhex("80371240")))


def megadrive() -> bytes:
    data = _pad(b"")
    data[0x100:0x110] = b"SEGA MEGA DRIVE "
    return bytes(data)


def sega32x() -> bytes:
    data = _pad(b"")
    data[0x100:0x110] = b"SEGA 32X        "
    return bytes(data)


def smd() -> bytes:
    data = _pad(b"")
    data[8] = 0xAA
    data[9] = 0xBB
    return bytes(data)


def cd_bin() -> bytes:
    data = _pad(_CD_SYNC)
    data[0x100:0x110] = b"SEGA MEGA DRIVE "
    return bytes(data)


def snk() -> bytes:
    return bytes(_pad(b"COPYRIGHT BY SNK CORPORATION"))


def atari7800() -> bytes:
    return bytes(_pad(b"\x01ATARI7800"))


def lynx() -> bytes:
    return bytes(_pad(b"LYNX"))


def coleco() -> bytes:
    return bytes(_pad(b"\xaa\x55"))


def raw(size: int = 0x400) -> bytes:
    return bytes(size)


def write(path: Path, content: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def write_zip(path: Path, members: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path
