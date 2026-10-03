# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""« Tout annuler » (docs/doublons.md) -- restaure les fichiers déplacés
à partir de `journal.json`, écrit au fil de l'eau par `move.py` dans le
dossier de destination lui-même (donc fidèle même après une interruption
brutale en cours de lot).

**Plusieurs destinations possibles** (signalé : « garder aussi dans la
config de l'app la liste des dernières destinations utilisées, pour que
Tout annuler retrouve le journal même si la destination a changé ») --
`undo_all` reçoit désormais la liste des destinations connues (session en
cours + historique mémorisé, `AppConfig.doublons_recent_destinations`) et
balaie chacune : une même carte a pu être traitée avec des destinations
différentes d'une session à l'autre, rien ne doit rester injoignable.

Chaque journal accumule toutes ses sessions de déplacement (jamais
écrasé) : une restauration traite *toutes* les entrées qu'il contient,
pas seulement la dernière. Chaque entrée restaurée avec succès est
retirée du journal -- un second clic, ou une session ultérieure, ne
retente jamais une entrée déjà traitée. Jamais d'écrasement : un conflit
(le fichier d'origine a été récréé entre-temps, ou le fichier déplacé
n'y est plus) est signalé plutôt que résolu silencieusement, et l'entrée
correspondante reste dans le journal pour un futur essai."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .move import JOURNAL_FILENAME, _read_journal, _write_journal

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


def _undo_one_destination(destination: str) -> UndoResult:
    destination_path = Path(destination).resolve()
    journal_path = destination_path / JOURNAL_FILENAME
    entries = _read_journal(journal_path)
    if not entries:
        # Rien à annuler -- jamais créer ce dossier comme effet de bord
        # d'un « Tout annuler » qui n'avait rien à faire ici.
        return UndoResult()

    remaining: List[dict] = []
    conflicts: List[UndoConflict] = []
    restored = 0

    for entry in entries:
        source = Path(entry["source"])
        destination_file = Path(entry["destination"])

        if not destination_file.exists():
            conflicts.append(
                UndoConflict(source=str(source), destination=str(destination_file), reason="destination_missing")
            )
            remaining.append(entry)
            continue
        if source.exists():
            conflicts.append(
                UndoConflict(source=str(source), destination=str(destination_file), reason="source_occupied")
            )
            remaining.append(entry)
            continue

        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(destination_file), str(source))
        restored += 1

    _write_journal(journal_path, remaining)
    return UndoResult(restored=restored, conflicts=conflicts)


def undo_all(destinations: List[str]) -> UndoResult:
    """Agrège la restauration sur toutes les `destinations` connues --
    dédupliquées (chemins résolus) pour ne jamais traiter deux fois le
    même journal si la même destination apparaît plusieurs fois dans
    l'historique mémorisé."""
    aggregate = UndoResult()
    seen: set = set()
    for destination in destinations:
        resolved = str(Path(destination).resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        result = _undo_one_destination(destination)
        aggregate.restored += result.restored
        aggregate.conflicts.extend(result.conflicts)
    return aggregate
