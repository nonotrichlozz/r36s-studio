# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Empêche la mise en veille de l'ordinateur pendant un flash USB (une
veille couperait le port USB au milieu de l'écriture). Windows seulement
(`SetThreadExecutionState`), sans effet ailleurs."""

from __future__ import annotations

import contextlib
import sys

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


def _etat(drapeaux: int) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.kernel32.SetThreadExecutionState(drapeaux))


@contextlib.contextmanager
def sans_veille():
    """À utiliser dans le thread qui dure tout le flash : l'état est lié
    au thread appelant."""
    _etat(_ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
    try:
        yield
    finally:
        _etat(_ES_CONTINUOUS)


__all__ = ["sans_veille"]
