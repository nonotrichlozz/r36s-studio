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

"""Affiche un dossier (typiquement une archive BOOT/EASYROMS, §4.4) dans le
gestionnaire de fichiers de l'OS — le bouton « Afficher dans le Finder » de
l'écran Résultat (§5). Purement une commodité GUI : contrairement à
`partitions/eject.py`, le CLI n'en a pas besoin, donc ce module vit ici et
pas dans `partitions/`."""

from __future__ import annotations

import platform
import subprocess


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
        return "Afficher dans le Finder"
    if system == "Windows":
        return "Afficher dans l'Explorateur"
    return "Afficher dans le gestionnaire de fichiers"


__all__ = ["reveal", "reveal_label"]
