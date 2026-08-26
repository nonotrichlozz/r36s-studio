"""Ouverture d'une image source pour le flash, avec décompression à la
volée (§4.3) — `.img`, `.img.gz`, `.img.xz`. Aucun fichier temporaire : la
décompression se fait en flux, au fil de la lecture."""

from __future__ import annotations

import gzip
import lzma
import os
import struct
from typing import BinaryIO, Optional

SUPPORTED_EXTENSIONS = (".img", ".img.gz", ".img.xz")


def open_image_source(path: str) -> BinaryIO:
    """Retourne un flux binaire lisant l'image décompressée. À utiliser
    comme gestionnaire de contexte (`with open_image_source(...) as f:`)."""
    lower = path.lower()
    if lower.endswith(".gz"):
        return gzip.open(path, "rb")
    if lower.endswith(".xz"):
        return lzma.open(path, "rb")
    if lower.endswith(".img"):
        return open(path, "rb")
    raise ValueError(
        f"format d'image non supporté : {path} (formats acceptés : {', '.join(SUPPORTED_EXTENSIONS)})"
    )


def _gzip_uncompressed_size(path: str) -> Optional[int]:
    """Lit les 4 derniers octets d'un `.gz` (champ ISIZE) : la taille
    décompressée modulo 2**32. Fiable pour un fichier gzip à un seul
    membre — le cas normal pour une image disque."""
    try:
        with open(path, "rb") as f:
            f.seek(-4, os.SEEK_END)
            (isize,) = struct.unpack("<I", f.read(4))
        return isize
    except (OSError, struct.error):
        return None


def estimate_total_bytes(path: str) -> Optional[int]:
    """Taille (en octets) à écrire sur le périphérique.

    Exacte pour `.img` (taille du fichier) et `.img.gz` (champ ISIZE). Pour
    `.img.xz`, la taille décompressée n'est pas récupérable sans
    décompression complète : retourne None plutôt qu'une estimation
    trompeuse (règle §2 n°5 — jamais de fausse progression). `copy_range`
    traite alors la copie comme non bornée."""
    lower = path.lower()
    if lower.endswith(".gz"):
        return _gzip_uncompressed_size(path)
    if lower.endswith(".xz"):
        return None
    return os.path.getsize(path)
