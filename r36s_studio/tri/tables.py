# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Tables de données du tri (docs/tri-roms.md) : systèmes reconnus
(`data/systems.json`) et nom de dossier + extensions acceptées par
firmware cible (`data/firmware_folders.json`).

**Risque principal de l'outil** : un nom de dossier faux et la console
n'affiche aucun jeu, sans que l'utilisateur comprenne pourquoi. D'où une
table *par firmware*, relevée dans les fichiers de configuration officiels
de chacun (jamais supposée), avec sa source, sa date et un indicateur
`verified_on_hardware` distinct -- seule une table relevée sur une vraie
carte le porte. Les extensions acceptées par chaque dossier sont relevées
au même endroit : un fichier qu'un firmware n'afficherait pas dans le
dossier visé n'y est jamais rangé (`plan.py`)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Tuple

__all__ = [
    "SystemInfo",
    "FirmwareFolders",
    "load_systems",
    "load_firmware_tables",
    "extension_map",
    "SORT_FIRMWARE_IDS",
]

_DATA_DIR = Path(__file__).parent / "data"

# Ordre d'affichage dans le choix du firmware cible. Les autres entrées du
# catalogue de flash (AmberELEC, MinUI, Android) n'ont pas de table : non
# proposées plutôt qu'un nom de dossier supposé.
SORT_FIRMWARE_IDS: Tuple[str, ...] = ("arkos", "rocknix", "emuelec", "treefrogui")


@dataclass(frozen=True)
class SystemInfo:
    id: str
    label: str
    # extension (minuscules, avec le point) -> nom de signature d'en-tête
    # (`identify.py::_SIGNATURES`), ou None quand aucune signature
    # universelle n'existe pour ce format (l'extension seule fait foi).
    extensions: Dict[str, Optional[str]]


@dataclass(frozen=True)
class FirmwareFolders:
    id: str
    source: str
    source_date: str
    verified_on_hardware: bool
    # id de système -> nom exact du dossier (casse comprise)
    folders: Dict[str, str]
    # id de système -> extensions acceptées par ce dossier, ou None quand
    # la liste n'est pas connue (aucun contrôle possible, documenté).
    accepted_extensions: Dict[str, Optional[FrozenSet[str]]]

    def folder_names_lower(self) -> FrozenSet[str]:
        return frozenset(name.lower() for name in self.folders.values())


@lru_cache(maxsize=1)
def load_systems() -> Dict[str, SystemInfo]:
    raw = json.loads((_DATA_DIR / "systems.json").read_text(encoding="utf-8"))
    return {
        system_id: SystemInfo(id=system_id, label=entry["label"], extensions=dict(entry["extensions"]))
        for system_id, entry in raw["systems"].items()
    }


@lru_cache(maxsize=1)
def load_firmware_tables() -> Dict[str, FirmwareFolders]:
    raw = json.loads((_DATA_DIR / "firmware_folders.json").read_text(encoding="utf-8"))
    tables: Dict[str, FirmwareFolders] = {}
    for firmware_id, entry in raw["firmwares"].items():
        folders = {system_id: spec["folder"] for system_id, spec in entry["systems"].items()}
        accepted = {
            system_id: (frozenset(spec["extensions"]) if spec["extensions"] is not None else None)
            for system_id, spec in entry["systems"].items()
        }
        tables[firmware_id] = FirmwareFolders(
            id=firmware_id,
            source=entry["source"],
            source_date=entry["source_date"],
            verified_on_hardware=bool(entry["verified_on_hardware"]),
            folders=folders,
            accepted_extensions=accepted,
        )
    return tables


@lru_cache(maxsize=1)
def extension_map() -> Dict[str, Tuple[str, Optional[str]]]:
    """extension -> (id de système, signature). Une extension n'appartient
    qu'à un seul système en phase 1 -- vérifié ici plutôt que supposé :
    une extension en double dans `systems.json` serait une ambiguïté
    silencieuse, exactement ce que l'outil s'interdit."""
    mapping: Dict[str, Tuple[str, Optional[str]]] = {}
    for system in load_systems().values():
        for extension, signature in system.extensions.items():
            if extension in mapping:
                raise ValueError(f"Extension {extension} déclarée pour deux systèmes : {mapping[extension][0]}, {system.id}")
            mapping[extension] = (system.id, signature)
    return mapping
