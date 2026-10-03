# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Garde-fous ajoutés après validation du plan (session de refonte de
l'outil « Doublons de jeux ») -- l'outil déplace des fichiers sur la
carte d'un client, traité avec le même sérieux que le reste des
opérations d'écriture de ce projet (§2 du brief principal), même si
aucune de ces fonctions ne touche elle-même un fichier : ce sont des
vérifications pures, avant que quoi que ce soit ne démarre. Même esprit
que `r36s_studio/safety/__init__.py` pour les périphériques -- des
fonctions qui décrivent un risque, jamais qui agissent."""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import FrozenSet

from .normalize import strip_accents

__all__ = ["LARGE_FOLDER_FILE_THRESHOLD", "is_filesystem_root", "is_whole_user_folder"]

# Au-delà de ce nombre de fichiers rencontrés pendant l'analyse, le scan
# se met en pause et demande confirmation avant de continuer (§ interface,
# géré par `gui/doublons_runner.py::DoublonsScanRunner` -- ne peut être
# connu qu'en marchant réellement dans l'arborescence, pas de pré-comptage
# séparé qui referait deux fois le même travail).
LARGE_FOLDER_FILE_THRESHOLD = 200_000

_WINDOWS_DRIVE_ROOT_RE = re.compile(r"^[A-Za-z]:\\?$")

# Sous-dossiers standards du profil utilisateur, pris *en entier* --
# jamais un sous-dossier à l'intérieur de l'un d'eux (ex. "Documents\ROMs"
# reste autorisé sans confirmation). Noms anglais et français courants.
_STANDARD_HOME_SUBFOLDER_NAMES: FrozenSet[str] = frozenset(
    {
        "documents",
        "desktop",
        "downloads",
        "pictures",
        "music",
        "videos",
        "bureau",
        "telechargements",
        "images",
        "musique",
        "videos",
    }
)


def is_filesystem_root(path: str) -> bool:
    """Racine d'un disque entier (`C:\\`, `/`, ou tout autre volume) --
    volontairement toute racine, pas seulement celle du disque système :
    analyser la racine de n'importe quel disque est risqué de la même
    façon (des dizaines/centaines de milliers de fichiers hors de propos,
    des dossiers système illisibles en cours de route)."""
    resolved = Path(path).resolve()
    if platform.system() == "Windows":
        return bool(_WINDOWS_DRIVE_ROOT_RE.match(str(resolved)))
    return resolved == resolved.parent


def is_whole_user_folder(path: str) -> bool:
    """Le dossier personnel entier (`Path.home()`), le dossier qui
    contient tous les profils (son parent -- « Utilisateurs »/`C:\\Users`),
    ou l'un de ses sous-dossiers standards pris en entier (Documents,
    Bureau...). Comparaison insensible aux accents/casse -- un dossier
    "Téléchargements" doit être reconnu même si l'appel vient d'un
    contexte qui ne préserve pas l'accentuation."""
    resolved = Path(path).resolve()
    home = Path.home().resolve()
    if resolved == home or resolved == home.parent:
        return True
    if resolved.parent == home:
        normalized_name = strip_accents(resolved.name).lower()
        if normalized_name in _STANDARD_HOME_SUBFOLDER_NAMES:
            return True
    return False
