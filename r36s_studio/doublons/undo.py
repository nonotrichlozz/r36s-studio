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

"""« Tout annuler » (docs/doublons.md) -- restaure les fichiers déplacés
vers `_doublons/` à partir de `journal.json` (écrit au fil de l'eau par
`move.py`, donc fidèle même après une interruption brutale en cours de
lot).

Le journal accumule toutes les sessions de déplacement (jamais écrasé) :
une restauration traite *toutes* les entrées qu'il contient, pas
seulement la dernière session. Chaque entrée restaurée avec succès est
retirée du journal -- un second clic, ou une session ultérieure, ne
retente jamais une entrée déjà traitée. Jamais d'écrasement : un conflit
(le fichier d'origine a été récréé entre-temps, ou le fichier dans
`_doublons/` n'y est plus) est signalé plutôt que résolu silencieusement,
et l'entrée correspondante reste dans le journal pour un futur essai."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .move import JOURNAL_FILENAME, _read_journal, _write_journal
from .scan import DUPLICATES_DIR_NAME

__all__ = ["UndoConflict", "UndoResult", "undo_all"]


@dataclass
class UndoConflict:
    source: str
    destination: str
    reason: str  # "destination_missing" | "source_occupied"


@dataclass
class UndoResult:
    restored: int = 0
    conflicts: List[UndoConflict] = field(default_factory=list)


def undo_all(root: str) -> UndoResult:
    root_path = Path(root).resolve()
    journal_path = root_path / DUPLICATES_DIR_NAME / JOURNAL_FILENAME
    entries = _read_journal(journal_path)
    if not entries:
        # Rien à annuler -- jamais créer `_doublons/` comme effet de bord
        # d'un « Tout annuler » qui n'avait rien à faire.
        return UndoResult()

    remaining: List[dict] = []
    conflicts: List[UndoConflict] = []
    restored = 0

    for entry in entries:
        source = Path(entry["source"])
        destination = Path(entry["destination"])

        if not destination.exists():
            conflicts.append(
                UndoConflict(source=str(source), destination=str(destination), reason="destination_missing")
            )
            remaining.append(entry)
            continue
        if source.exists():
            conflicts.append(
                UndoConflict(source=str(source), destination=str(destination), reason="source_occupied")
            )
            remaining.append(entry)
            continue

        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination), str(source))
        restored += 1

    _write_journal(journal_path, remaining)
    return UndoResult(restored=restored, conflicts=conflicts)
