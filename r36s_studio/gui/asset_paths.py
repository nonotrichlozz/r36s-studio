# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Résolution du dossier `gui/assets/` (images d'habillage décoratives,
§5) — fonctionne aussi bien en développement qu'une fois l'app empaquetée
(PyInstaller copie ce dossier à côté du binaire, voir `packaging/
r36s_studio.spec`, même principe que `gui/build_info.py` pour l'horodatage
de construction)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_ASSETS_SUBDIR = "assets"


def assets_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / _ASSETS_SUBDIR
    return Path(__file__).resolve().parent / _ASSETS_SUBDIR


def asset_path(filename: str) -> Optional[Path]:
    """None si le fichier n'existe pas -- l'absence d'un asset décoratif ne
    doit jamais empêcher l'interface de s'afficher normalement (§5)."""
    path = assets_dir() / filename
    return path if path.exists() else None
