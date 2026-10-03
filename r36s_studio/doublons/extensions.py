# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Extensions considérées comme des fichiers de jeu (docs/doublons.md
§« Extensions considérées comme des jeux ») -- chargées depuis
`data/extensions.json`, pas en dur dans le code (demandé explicitement) :
un point de départ documenté comme tel, facile à étendre sans toucher au
code Python, même esprit que `identify/__init__.py::CLONE_DTB_FILENAMES`
ailleurs dans ce projet.

Trois catégories, structurelles (pas données -- elles décrivent un
format, pas une préférence utilisateur) :

- **manifest** (`.cue`/`.m3u`/`.gdi`) -- décrit un jeu à plusieurs
  fichiers ; résolu par `linked_files.py` en un `Unit` regroupant le
  manifeste et les fichiers qu'il référence.
- **companion_only** (`.bin`) -- ne constitue jamais un candidat à lui
  seul : un `.bin` orphelin (aucun `.cue`/`.gdi` du même dossier ne le
  référence) n'a aucune façon fiable d'être comparé à un autre fichier,
  donc n'est simplement jamais retenu (règle critique du fichiers liés,
  docs/doublons.md -- « ne jamais déplacer un .bin sans son .cue »
  s'étend logiquement à « ne jamais le comparer seul » : un faux positif
  ici détruirait un jeu aussi sûrement qu'un mauvais déplacement).
- **atomic** (tout le reste de la liste blanche) -- un fichier candidat
  à lui seul, éligible aux deux paliers de détection."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import FrozenSet

__all__ = ["ExtensionKind", "ROM_EXTENSIONS", "MANIFEST_EXTENSIONS", "COMPANION_ONLY_EXTENSIONS", "classify"]

_DATA_PATH = Path(__file__).parent / "data" / "extensions.json"

# Décrivent un format à plusieurs fichiers -- jamais un candidat solo
# eux-mêmes, `linked_files.py` les résout en `Unit`.
MANIFEST_EXTENSIONS: FrozenSet[str] = frozenset({".cue", ".m3u", ".gdi"})

# Ne constitue jamais un candidat sans son manifeste (voir docstring de
# module) -- filet de sécurité même si un jour ajouté par erreur ailleurs.
COMPANION_ONLY_EXTENSIONS: FrozenSet[str] = frozenset({".bin"})


def _load_rom_extensions() -> FrozenSet[str]:
    raw = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return frozenset(ext.lower() for ext in raw["rom_extensions"])


ROM_EXTENSIONS: FrozenSet[str] = _load_rom_extensions()


class ExtensionKind(Enum):
    MANIFEST = "manifest"
    COMPANION_ONLY = "companion_only"
    ATOMIC = "atomic"
    UNKNOWN = "unknown"


def classify(extension: str) -> ExtensionKind:
    """`extension` avec ou sans le point initial, insensible à la casse."""
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext not in ROM_EXTENSIONS:
        return ExtensionKind.UNKNOWN
    if ext in MANIFEST_EXTENSIONS:
        return ExtensionKind.MANIFEST
    if ext in COMPANION_ONLY_EXTENSIONS:
        return ExtensionKind.COMPANION_ONLY
    return ExtensionKind.ATOMIC
