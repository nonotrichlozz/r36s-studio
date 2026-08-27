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


_XZ_FOOTER_MAGIC = b"YZ"
_XZ_FOOTER_SIZE = 12


def _read_xz_vli(data: bytes, offset: int) -> tuple:
    """Décode un entier de taille variable façon xz (« Variable Length
    Integer », format-xz.txt §Vli) à partir de `data[offset:]` : chaque
    octet porte 7 bits de poids croissant, le bit de poids fort indique la
    suite. Retourne `(valeur, offset après le dernier octet lu)`."""
    value = 0
    for i in range(9):  # un VLI xz tient sur 9 octets au plus (63 bits utiles)
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << (7 * i)
        if not byte & 0x80:
            return value, offset
    raise ValueError("VLI xz invalide (dépasse 9 octets)")


def _xz_uncompressed_size(path: str) -> Optional[int]:
    """Lit le pied (footer) d'un `.xz` pour récupérer la taille décompressée
    totale, **sans décompresser le flux** : le footer xz (12 derniers
    octets) donne la taille de l'Index qui le précède, et cet Index liste,
    pour chaque bloc du flux, sa taille décompressée (format-xz.txt) — la
    somme de ces tailles est la taille décompressée exacte du flux. Ne gère
    qu'un flux xz unique (le cas normal pour une image disque, comme
    `_gzip_uncompressed_size` ne gère qu'un seul membre gzip) ; retourne
    None si le footer ne ressemble pas à un footer xz standard (magique
    absente, fichier tronqué...) plutôt que de lever — `estimate_total_bytes`
    retombe alors sur la taille du périphérique cible."""
    try:
        with open(path, "rb") as f:
            f.seek(-_XZ_FOOTER_SIZE, os.SEEK_END)
            footer = f.read(_XZ_FOOTER_SIZE)
            if footer[10:12] != _XZ_FOOTER_MAGIC:
                return None
            (backward_size,) = struct.unpack("<I", footer[4:8])
            index_size = (backward_size + 1) * 4
            f.seek(-_XZ_FOOTER_SIZE - index_size, os.SEEK_END)
            index_data = f.read(index_size)
    except (OSError, struct.error, IndexError):
        return None

    if len(index_data) != index_size or not index_data or index_data[0] != 0x00:
        return None

    try:
        offset = 1
        num_records, offset = _read_xz_vli(index_data, offset)
        total = 0
        for _ in range(num_records):
            _unpadded_size, offset = _read_xz_vli(index_data, offset)
            uncompressed_size, offset = _read_xz_vli(index_data, offset)
            total += uncompressed_size
    except (IndexError, ValueError):
        return None
    return total


def estimate_total_bytes(path: str) -> Optional[int]:
    """Taille (en octets) à écrire sur le périphérique.

    Exacte pour `.img` (taille du fichier), `.img.gz` (champ ISIZE) et
    `.img.xz` (Index du pied de l'archive, `_xz_uncompressed_size` —
    aucune décompression nécessaire). Retourne None seulement si le pied
    `.xz`/`.gz` ne peut pas être lu (fichier tronqué, format non standard) :
    à `flash_device` (qui connaît la taille du périphérique cible) de
    retomber sur une estimation plutôt que de laisser la copie non bornée."""
    lower = path.lower()
    if lower.endswith(".gz"):
        return _gzip_uncompressed_size(path)
    if lower.endswith(".xz"):
        return _xz_uncompressed_size(path)
    return os.path.getsize(path)
