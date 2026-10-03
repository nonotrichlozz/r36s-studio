# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Affiche un dossier (typiquement une archive BOOT/EASYROMS, §4.4) dans le
gestionnaire de fichiers de l'OS — le bouton « Afficher dans le Finder » de
l'écran Résultat (§5). Purement une commodité GUI : contrairement à
`partitions/eject.py`, le CLI n'en a pas besoin, donc ce module vit ici et
pas dans `partitions/`."""

from __future__ import annotations

import platform
import subprocess

from .strings import tr


def reveal(path: str) -> None:
    """Ouvre le gestionnaire de fichiers avec `path` sélectionné quand l'OS
    le permet (macOS, Windows) ; se contente d'ouvrir `path` lui-même sous
    Linux, où il n'existe pas d'équivalent universel à la sélection."""
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["open", "-R", path], check=True)
    elif system == "Linux":
        subprocess.run(["xdg-open", path], check=True)
    elif system == "Windows":
        # `explorer` renvoie souvent un code de sortie non nul même en cas
        # de succès (comportement documenté) -- pas de `check=True` ici.
        subprocess.run(["explorer", f"/select,{path}"])
    else:
        raise NotImplementedError(f"Affichage dans le gestionnaire de fichiers non supporté sur {system}")


def reveal_label() -> str:
    """Libellé du bouton, adapté au vocabulaire de l'OS courant (§5 :
    jamais de jargon, mais « Finder »/« Explorateur » sont les noms réels
    que l'utilisateur connaît déjà sur sa machine)."""
    system = platform.system()
    if system == "Darwin":
        return tr("reveal_finder")
    if system == "Windows":
        return tr("reveal_explorer")
    return tr("reveal_file_manager")


__all__ = ["reveal", "reveal_label"]
