"""Fichiers creux pour les images de test volumineuses (cartes factices de
plusieurs centaines de Mo à 1 Go dont seul l'en-tête compte).

Sur macOS/Linux, `seek` au-delà de la fin suffit à créer un fichier creux. Pas sur NTFS : sans le drapeau « sparse » posé explicitement,
Windows remplit le trou de vrais zéros -- chaque série de tests laissait
ainsi ~6,5 Go dans le dossier temporaire de pytest."""

from __future__ import annotations

import sys


def create_sparse_file(path, size: int, head: bytes = b"") -> None:
    """Crée `path` de `size` octets ; seul `head` (écrit à l'offset 0)
    occupe réellement le disque."""
    with open(path, "wb") as f:
        if sys.platform == "win32":
            _set_sparse_flag(f.fileno())
        f.write(head)
        # Pas `truncate` : sous Windows, la CRT étend le fichier en écrivant
        # de vrais zéros, alloués même sur un fichier marqué creux.
        f.seek(size - 1)
        f.write(b"\x00")


def _set_sparse_flag(fd: int) -> None:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    fsctl_set_sparse = 0x000900C4
    returned = wintypes.DWORD()
    # Échec possible sur un volume sans fichiers creux (FAT32) : le fichier
    # reste alors plein, comme avant -- le test, lui, n'en dépend pas.
    ctypes.windll.kernel32.DeviceIoControl(
        wintypes.HANDLE(msvcrt.get_osfhandle(fd)), fsctl_set_sparse,
        None, 0, None, 0, ctypes.byref(returned), None,
    )
