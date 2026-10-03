# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Identification d'un fichier de jeu, en cascade (docs/tri-roms.md) --
même principe que `imaging/image_source.py::_detect_format` : les octets
d'en-tête priment sur ce que le nom prétend.

1. L'extension désigne un seul système (`tables.extension_map`).
2. Si ce format a une signature d'en-tête universelle, elle doit être
   présente -- sinon le fichier n'est **pas** rangé (extension et contenu
   se contredisent : on ne tranche pas à la place de l'utilisateur).
3. Cas ambigus : `.zip` (contenu listé sans extraction, un seul jeu
   exigé) et `.bin` (en-tête Mega Drive, sinon non identifié).
4. Tout le reste : non identifié, avec un motif.

**Ne jamais deviner** : chaque chemin qui ne mène pas à une certitude
retourne `system_id=None`."""

from __future__ import annotations

import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Optional

from .tables import extension_map

__all__ = [
    "Identification",
    "identify_file",
    "identify_bytes",
    "DISC_EXTENSIONS",
    "MANIFEST_EXTENSIONS",
]

HEADER_READ_SIZE = 0x200

# Formats de disque : le système ne se déduit ni de l'extension ni d'une
# signature simple (PS1, Mega-CD, PC Engine CD, Saturn... partagent les
# mêmes). Non couverts en phase 1.
DISC_EXTENSIONS = frozenset(
    {".cue", ".chd", ".iso", ".img", ".gdi", ".m3u", ".pbp", ".cso", ".ccd", ".mdf", ".toc", ".cdi", ".cbn"}
)
# Manifestes qui listent d'autres fichiers (`doublons/linked_files.py`).
MANIFEST_EXTENSIONS = frozenset({".cue", ".m3u", ".gdi"})
# Fichiers d'accompagnement tolérés à côté du jeu dans un `.zip`.
_ZIP_COMPANION_EXTENSIONS = frozenset({".txt", ".nfo", ".diz"})

_GB_LOGO = bytes.fromhex(
    "CEED6666CC0D000B03730083000C000D0008111F8889000EDCCC6EE6DDDDD999BBBB67636E0EECCCDDDC999FBBB9333E"
)
_GBA_LOGO_PREFIX = bytes.fromhex("24FFAE51")
_N64_MAGICS = (bytes.fromhex("80371240"), bytes.fromhex("37804012"), bytes.fromhex("40123780"))
_SNK_HEADERS = (b"COPYRIGHT BY SNK CORPORATION", b" LICENSED BY SNK CORPORATION")
_CD_SYNC = bytes.fromhex("00FFFFFFFFFFFFFFFFFFFF00")


@dataclass(frozen=True)
class Identification:
    system_id: Optional[str]
    # Motif (clé stable, traduite côté interface) : comment le système a
    # été trouvé, ou pourquoi il ne l'a pas été.
    reason: str
    # Détail brut pour le journal (nom du fichier interne d'un zip...).
    detail: str = ""


def _sega_area(header: bytes) -> bytes:
    return header[0x100:0x110]


def _has_sega_header(header: bytes) -> bool:
    return b"SEGA" in _sega_area(header)


def _is_32x_header(header: bytes) -> bool:
    return b"32X" in _sega_area(header)


def _looks_like_disc(header: bytes) -> bool:
    """Secteur CD brut (motif de synchronisation) ou en-tête Mega-CD --
    un `.bin` de disque ne doit jamais être pris pour une cartouche."""
    return header.startswith(_CD_SYNC) or b"SEGADISCSYSTEM" in header[:0x20]


def _gba_ok(header: bytes) -> bool:
    return len(header) > 0xB2 and header[0x04:0x08] == _GBA_LOGO_PREFIX and header[0xB2] == 0x96


_SIGNATURES: Dict[str, Callable[[bytes], bool]] = {
    "ines": lambda h: h.startswith(b"NES\x1a"),
    "fds": lambda h: h.startswith(b"FDS\x1a") or h.startswith(b"\x01*NINTENDO-HVC*"),
    "gb_logo": lambda h: h[0x104:0x134] == _GB_LOGO,
    "gba_header": _gba_ok,
    "n64": lambda h: h[:4] in _N64_MAGICS,
    "megadrive": lambda h: _has_sega_header(h) and not _is_32x_header(h) and not _looks_like_disc(h),
    "smd_interleaved": lambda h: (len(h) > 9 and h[8] == 0xAA and h[9] == 0xBB) or _has_sega_header(h),
    "sega_header": lambda h: _has_sega_header(h) and not _looks_like_disc(h),
    "snk": lambda h: h[:28] in _SNK_HEADERS,
    "atari7800": lambda h: h[1:10] == b"ATARI7800",
    "lynx": lambda h: h.startswith(b"LYNX"),
    "coleco": lambda h: h[:2] in (b"\xaa\x55", b"\x55\xaa"),
}


def _identify_bin(header: bytes) -> Identification:
    if _looks_like_disc(header):
        return Identification(None, "disc_image")
    if _has_sega_header(header):
        return Identification("sega32x" if _is_32x_header(header) else "megadrive", "bin_header")
    return Identification(None, "bin_unknown")


def identify_bytes(extension: str, header: bytes) -> Identification:
    """Identifie à partir d'une extension (minuscules, avec le point) et
    des premiers octets -- partagé entre un fichier sur disque et un
    fichier contenu dans un `.zip`."""
    if extension == ".bin":
        return _identify_bin(header)
    if extension in DISC_EXTENSIONS:
        return Identification(None, "disc_image")
    if extension == ".7z":
        return Identification(None, "archive_7z")
    entry = extension_map().get(extension)
    if entry is None:
        return Identification(None, "unknown_extension")
    system_id, signature = entry
    if signature is None:
        return Identification(system_id, "extension")
    if _SIGNATURES[signature](header):
        return Identification(system_id, "extension_header")
    return Identification(None, "header_mismatch", detail=f"{extension} sans en-tête {signature}")


def _read_header(path: Path) -> Optional[bytes]:
    try:
        with open(path, "rb") as handle:
            return handle.read(HEADER_READ_SIZE)
    except OSError:
        return None


def _identify_zip(path: Path) -> Identification:
    """Liste le contenu sans rien extraire sur le disque. Exige exactement
    un fichier de jeu (plus d'éventuels `.txt`/`.nfo`/`.diz`) : un zip à
    plusieurs fichiers est typiquement un jeu d'arcade (MAME/FBNeo), dont
    le système ne se déduit pas du contenu -- jamais rangé au hasard."""
    try:
        with zipfile.ZipFile(path) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            games = [info for info in members if Path(info.filename).suffix.lower() not in _ZIP_COMPANION_EXTENSIONS]
            if not games:
                return Identification(None, "zip_empty")
            if len(games) > 1:
                return Identification(None, "zip_multiple", detail=f"{len(games)} fichiers")
            inner = games[0]
            inner_extension = Path(inner.filename).suffix.lower()
            with archive.open(inner) as handle:
                header = handle.read(HEADER_READ_SIZE)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, NotImplementedError, EOFError, OSError, zlib.error) as exc:
        return Identification(None, "zip_unreadable", detail=str(exc))
    inner_result = identify_bytes(inner_extension, header)
    if inner_result.system_id is None:
        return Identification(None, inner_result.reason, detail=inner.filename)
    return Identification(inner_result.system_id, "zip_content", detail=inner.filename)


def identify_file(path: Path) -> Identification:
    extension = path.suffix.lower()
    if extension == ".zip":
        return _identify_zip(path)
    needs_header = extension == ".bin"
    entry = extension_map().get(extension)
    if entry is not None and entry[1] is not None:
        needs_header = True
    header = b""
    if needs_header:
        read = _read_header(path)
        if read is None:
            return Identification(None, "unreadable")
        header = read
    return identify_bytes(extension, header)
