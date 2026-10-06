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

from r36s_studio.doublons.move import (
    MoveFileFailed,
    _check_disk_space,
    _check_writable,
    _move_one_file,
    _path_exists_long,
    _unique_destination,
    is_cross_volume_destination,
)
from r36s_studio.doublons.undo import UndoConflict, UndoResult

from .plan import SET_ASIDE_DIR_NAMES, SORT_JOURNAL_FILENAME, PlannedMove, SortPlan

__all__ = ["ApplyResult", "apply_plan", "journal_path", "has_journal", "undo_sort", "MAX_CONSECUTIVE_FAILURES"]

# Au-delà, la carte a très probablement été retirée : inutile d'échouer
# sur chacun des milliers de fichiers restants.
MAX_CONSECUTIVE_FAILURES = 20


@dataclass
class ApplyResult:
    moved_files: int = 0
    failures: List[Tuple[Path, str]] = field(default_factory=list)
    # Groupe non identifié (ou écarté par le filtre) dont un fichier existe
    # déjà dans `_non_identifies`/`_hors_filtre` (tri précédent) : laissé
    # en place, jamais écrasé ni renommé (renommer un `.bin` casserait son
    # `.cue`).
    skipped_existing: List[PlannedMove] = field(default_factory=list)
    # Fichier disparu entre l'aperçu et le déplacement.
    missing_sources: List[Path] = field(default_factory=list)
    cancelled: bool = False
    aborted: bool = False


def journal_path(root: str, name: str = SORT_JOURNAL_FILENAME) -> Path:
    """`name` : `SORT_JOURNAL_FILENAME` (tri) ou `FILTER_JOURNAL_FILENAME`
    (filtre) -- deux journaux, deux annulations indépendantes."""
    return Path(root).resolve() / name


def has_journal(root: str, name: str = SORT_JOURNAL_FILENAME) -> bool:
    return bool(_read_entries(journal_path(root, name)))


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


def _destination_root(plan: SortPlan) -> Path:
    return plan.destination if plan.destination is not None else plan.root


def _destinations(plan: SortPlan, move: PlannedMove) -> List[Path]:
    if move.folder in SET_ASIDE_DIR_NAMES:
        return [plan.root / move.folder / member.relative_to(plan.root) for member in move.members]
    return [_unique_destination(_destination_root(plan) / move.folder / member.name) for member in move.members]


def apply_plan(
    plan: SortPlan,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    journal_name: str = SORT_JOURNAL_FILENAME,
) -> ApplyResult:
    """Lève `DestinationNotWritable` (`doublons/move.py`) avant tout
    déplacement si le dossier ou la destination n'est pas inscriptible, et
    `InsufficientDiskSpace` si une destination sur un autre disque n'a pas
    la place pour les jeux rangés. Ensuite, jamais d'exception pour un
    fichier précis : chaque échec est consigné dans le résultat et le tri
    continue avec le suivant.

    Destination sur un autre disque (une carte, typiquement) : chaque jeu
    est copié, vérifié, puis seulement retiré de la source -- le chemin
    prudent de `_move_one_file`. Ce qui est mis de côté reste sur le même
    disque que la source."""
    _check_writable(plan.root)
    destination_root = _destination_root(plan)
    cross_volume = destination_root != plan.root and is_cross_volume_destination(str(plan.root), str(destination_root))
    if destination_root != plan.root:
        _check_writable(destination_root)
    if cross_volume:
        _check_disk_space(destination_root, sum(move.size_bytes for move in plan.moves))
    journal = journal_path(str(plan.root), journal_name)
    units = plan.moves + plan.unidentified + plan.filtered_out
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
        set_aside = unit.folder in SET_ASIDE_DIR_NAMES
        if set_aside and any(_path_exists_long(dest) for dest in destinations):
            result.skipped_existing.append(unit)
            continue
        for member, destination in zip(unit.members, destinations):
            try:
                _move_one_file(member, destination, None, cross_volume=cross_volume and not set_aside)
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


def undo_sort(root: str, journal_name: str = SORT_JOURNAL_FILENAME) -> UndoResult:
    """Remet chaque fichier à sa place d'origine d'après le journal -- du
    plus récent au plus ancien. Jamais d'écrasement : un conflit (fichier
    d'origine recréé entre-temps, fichier rangé introuvable) est signalé
    et son entrée reste dans le journal pour un futur essai. Les dossiers
    créés par le tri restent en place (vides) : rien n'est supprimé."""
    path = journal_path(root, journal_name)
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
