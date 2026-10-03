# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Numéro de version et horodatage de construction, affichés sur l'écran
d'accueil (§5). Sans cette information, impossible de savoir si l'app
testée contient les derniers correctifs — problème vécu directement en
développement (plusieurs reconstructions locales de suite, aucun moyen de
les distinguer une fois lancées) et qui se reposerait à l'identique pour
un utilisateur signalant un bug.

L'horodatage n'a de sens que pour un binaire empaqueté : `packaging/
r36s_studio.spec` écrit l'heure de construction — en heure locale de la
machine de construction, pas UTC, pour éviter une conversion mentale à
chaque vérification (c'est la même machine qui teste le binaire juste
après) — dans un petit fichier embarqué au moment de l'exécution de
PyInstaller, introuvable en développement (`python -m r36s_studio gui`) —
là, seul le numéro de version est affiché."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from r36s_studio import __version__

from .strings import tr

_BUILD_TIMESTAMP_FILENAME = "build_timestamp.txt"


def build_timestamp() -> Optional[str]:
    """None en développement (pas de construction, donc rien à horodater) —
    un vrai horodatage seulement pour un binaire PyInstaller ayant trouvé
    son fichier embarqué (absent si le `.spec` n'a pas pu le générer,
    ex. horloge système illisible : mieux vaut l'omettre que mentir)."""
    if not getattr(sys, "frozen", False):
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return None
    try:
        return (Path(meipass) / _BUILD_TIMESTAMP_FILENAME).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def version_label() -> str:
    """Ex. « R36S Studio v0.1.0 (build du 27/08/2026 à 16:28) » une fois
    empaqueté, « R36S Studio v0.1.0 (version de développement) » sinon."""
    timestamp = build_timestamp()
    suffix = tr("about_build", timestamp=timestamp) if timestamp else tr("about_dev")
    return tr("about_version", version=__version__, suffix=suffix)
