# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

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
