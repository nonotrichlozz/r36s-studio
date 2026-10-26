# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Raccourcis web personnels. La liste livrée est vide : aucun lien en dur
dans le code (CLAUDE.md §8). Ils sont lus, s'il existe, dans
`raccourcis.json` du dossier de configuration (`~/.config/r36s-studio/`,
hors dépôt, absent par défaut) :

    [{"nom": "Mon tableau de bord", "url": "https://exemple.org/"}]

Donnée de l'utilisateur, mais jamais interprétée : seuls des liens
`https://` sont gardés, nom réduit à une ligne, liste plafonnée. Un fichier
illisible donne une liste vide, jamais une exception."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from r36s_studio import config as app_config

SHORTCUTS_FILENAME = "raccourcis.json"
MAX_SHORTCUTS = 20
MAX_NAME_CHARS = 60
MAX_URL_CHARS = 2000

__all__ = ["SHORTCUTS_FILENAME", "Shortcut", "load_shortcuts", "shortcuts_path"]


@dataclass(frozen=True)
class Shortcut:
    name: str
    url: str


def shortcuts_path() -> Path:
    return app_config.config_dir() / SHORTCUTS_FILENAME


def _valid_url(url) -> bool:
    if not isinstance(url, str) or len(url) > MAX_URL_CHARS:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.hostname)


def load_shortcuts(path: Optional[Path] = None) -> List[Shortcut]:
    path = path or shortcuts_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    shortcuts = []
    for entry in raw:
        if not isinstance(entry, dict) or not _valid_url(entry.get("url")):
            continue
        name = entry.get("nom")
        name = " ".join(name.split()) if isinstance(name, str) else ""
        if not name or len(name) > MAX_NAME_CHARS:
            continue
        shortcuts.append(Shortcut(name, entry["url"]))
        if len(shortcuts) == MAX_SHORTCUTS:
            break
    return shortcuts
