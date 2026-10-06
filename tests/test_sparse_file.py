"""`create_sparse_file` : la taille logique est respectée, mais le fichier
n'occupe presque rien sur le disque (cf. tests/sparse_file.py)."""

from __future__ import annotations

import os
import sys

from .sparse_file import create_sparse_file


def _allocated_bytes(path) -> int:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        high = wintypes.DWORD()
        low = ctypes.windll.kernel32.GetCompressedFileSizeW(str(path), ctypes.byref(high))
        return (high.value << 32) + low
    return os.stat(path).st_blocks * 512


def test_sparse_file_has_logical_size_but_almost_no_allocation(tmp_path):
    path = tmp_path / "big.img"
    create_sparse_file(path, 256 * 1024 * 1024, b"\x55\xaa" * 256)

    assert path.stat().st_size == 256 * 1024 * 1024
    assert path.read_bytes()[:4] == b"\x55\xaa\x55\xaa"
    assert _allocated_bytes(path) < 16 * 1024 * 1024
