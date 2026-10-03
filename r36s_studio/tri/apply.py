# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Exécution du tri après confirmation, et son annulation
(docs/tri-roms.md). **Déplacer, jamais supprimer** : réutilise le
déplacement fichier par fichier du dédoublonnage (`doublons/move.py::
_move_one_file`, `_unique_destination` : aucun écrasement, suffixe `_2`).

Journal : `<dossier>/_rangement_journal.json`, une ligne JSON par fichier
déplacé (JSON Lines), écrite au fil de l'eau -- fidèle même après une
interruption brutale. Pas le format liste de `doublons/move.py`, qui
réécrit tout le fichier à chaque ajout : acceptable pour quelques
doublons, pas pour des milliers de jeux sur une carte SD lente."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from r36s_studio.doublons.move import MoveFileFailed, _check_writable, _move_one_file, _path_exists_long, _unique_destination
from r36s_studio.doublons.undo import UndoConflict, UndoResult

from .plan import SORT_JOURNAL_FILENAME, UNIDENTIFIED_DIR_NAME, PlannedMove, SortPlan

__all__ = ["ApplyResult", "apply_plan", "journal_path", "has_journal", "undo_sort", "MAX_CONSECUTIVE_FAILURES"]

# Au-delà, la carte a très probablement été retirée : inutile d'échouer
# sur chacun des milliers de fichiers restants.
MAX_CONSECUTIVE_FAILURES = 20


@dataclass
class ApplyResult:
    moved_files: int = 0
    failures: List[Tuple[Path, str]] = field(default_factory=list)
    # Groupe non identifié dont un fichier existe déjà dans
    # `_non_identifies` (tri précédent) : laissé en place, jamais écrasé
    # ni renommé (renommer un `.bin` casserait son `.cue`).
    skipped_existing: List[PlannedMove] = field(default_factory=list)
    # Fichier disparu entre l'aperçu et le déplacement.
    missing_sources: List[Path] = field(default_factory=list)
    cancelled: bool = False
    aborted: bool = False


def journal_path(root: str) -> Path:
    return Path(root).resolve() / SORT_JOURNAL_FILENAME


def has_journal(root: str) -> bool:
    return bool(_read_entries(journal_path(root)))


def _append_entry(path: Path, source: Path, destination: Path) -> None:
    line = json.dumps(
        {"source": str(source), "destination": str(destination), "moved_at": datetime.now(timezone.utc).isoformat()},
        ensure_ascii=False,
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def _read_entries(path: Path) -> List[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            # Dernière ligne tronquée par une coupure brutale : ignorée,
            # le fichier correspondant n'a peut-être pas été déplacé.
            continue
        if isinstance(entry, dict) and "source" in entry and "destination" in entry:
            entries.append(entry)
    return entries


def _destinations(plan: SortPlan, move: PlannedMove) -> List[Path]:
    if move.folder == UNIDENTIFIED_DIR_NAME:
        return [plan.root / UNIDENTIFIED_DIR_NAME / member.relative_to(plan.root) for member in move.members]
    return [_unique_destination(plan.root / move.folder / member.name) for member in move.members]


def apply_plan(
    plan: SortPlan,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> ApplyResult:
    """Lève `DestinationNotWritable` (`doublons/move.py`) avant tout
    déplacement si le dossier n'est pas inscriptible. Ensuite, jamais
    d'exception pour un fichier précis : chaque échec est consigné dans
    le résultat et le tri continue avec le suivant."""
    _check_writable(plan.root)
    journal = journal_path(str(plan.root))
    units = plan.moves + plan.unidentified
    total = sum(len(unit.members) for unit in units)
    result = ApplyResult()
    consecutive_failures = 0

    for unit in units:
        if should_cancel is not None and should_cancel():
            result.cancelled = True
            return result
        missing = [member for member in unit.members if not member.exists()]
        if missing:
            result.missing_sources.extend(missing)
            continue
        destinations = _destinations(plan, unit)
        if unit.folder == UNIDENTIFIED_DIR_NAME and any(_path_exists_long(dest) for dest in destinations):
            result.skipped_existing.append(unit)
            continue
        for member, destination in zip(unit.members, destinations):
            try:
                _move_one_file(member, destination, None, cross_volume=False)
            except MoveFileFailed as exc:
                result.failures.append((member, exc.reason))
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    result.aborted = True
                    return result
                continue
            consecutive_failures = 0
            _append_entry(journal, member, destination)
            result.moved_files += 1
            if on_progress is not None:
                on_progress(result.moved_files, total)
    return result


def undo_sort(root: str) -> UndoResult:
    """Remet chaque fichier à sa place d'origine d'après le journal -- du
    plus récent au plus ancien. Jamais d'écrasement : un conflit (fichier
    d'origine recréé entre-temps, fichier rangé introuvable) est signalé
    et son entrée reste dans le journal pour un futur essai. Les dossiers
    créés par le tri restent en place (vides) : rien n'est supprimé."""
    path = journal_path(root)
    entries = _read_entries(path)
    if not entries:
        return UndoResult()
    remaining: List[dict] = []
    result = UndoResult()
    for entry in reversed(entries):
        source = Path(entry["source"])
        destination = Path(entry["destination"])
        if not destination.exists():
            result.conflicts.append(UndoConflict(str(source), str(destination), "destination_missing"))
            remaining.append(entry)
            continue
        if source.exists():
            result.conflicts.append(UndoConflict(str(source), str(destination), "source_occupied"))
            remaining.append(entry)
            continue
        try:
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
        except OSError:
            result.conflicts.append(UndoConflict(str(source), str(destination), "move_failed"))
            remaining.append(entry)
            continue
        result.restored += 1
    if remaining:
        text = "".join(json.dumps(entry, ensure_ascii=False) + "\n" for entry in reversed(remaining))
        path.write_text(text, encoding="utf-8")
    else:
        # Fichier propre à l'outil, entièrement consommé : le retirer
        # évite de le copier sur la carte avec les jeux.
        try:
            os.unlink(path)
        except OSError:
            pass
    return result
