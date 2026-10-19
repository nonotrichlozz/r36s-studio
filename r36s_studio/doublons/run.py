# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Analyse et mise de côté des doublons, sans Qt : fonctions synchrones à
callback de progression et annulation coopérative (même forme que
`imaging/copy.py`), qui traduisent les exceptions de `scan.py`/`move.py`
en codes d'erreur (`gui/strings.py::_ERROR_MESSAGE_KEYS`). Appelées par
les threads Qt de la GUI (`gui/doublons_runner.py`) et par le bot Telegram
(`bot/`) -- jamais deux logiques parallèles.

Aussi la sélection par défaut de l'écran de résultats (docs/doublons-
selection.md) : groupe identique, tout sauf le premier ; groupe de
versions, tout sauf la version suggérée."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .move import (
    CopyVerificationFailed,
    DestinationInsideRootNotAllowed,
    DestinationIsFilesystemRoot,
    DestinationNotWritable,
    DuplicatesOutsideRoot,
    FatFileSizeLimitExceeded,
    InsufficientDiskSpace,
    MoveCancelled,
    MoveFileFailed,
    PartialMoveFailure,
    check_destination_allowed,
    default_destination,
    move_duplicates,
)
from .scan import ExactDuplicateGroup, HashCache, OperationCancelled, ScanResult, Unit, VersionGroup, find_duplicates

__all__ = [
    "AUTO_SKIP_AFTER",
    "MoveOutcome",
    "ScanOutcome",
    "default_units_to_move",
    "preferred_destination",
    "prune_moved",
    "run_move",
    "run_scan",
]

# Échecs de même raison déjà ignorés par l'utilisateur au-delà desquels on
# ne demande plus (signalé : touche Entrée bloquée sur un millier de fenêtres).
AUTO_SKIP_AFTER = 3


@dataclass
class ScanOutcome:
    result: Optional[ScanResult] = None
    cancelled: bool = False
    error_code: Optional[str] = None
    error_detail: str = ""


def run_scan(
    root: str,
    ignored_dirs: Iterable[str],
    hash_cache: HashCache,
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    confirm_large_folder: Optional[Callable[[], bool]] = None,
) -> ScanOutcome:
    """`hash_cache` est complété en place (à sauvegarder par l'appelant,
    `scan_cache.save_hash_cache`), y compris après une annulation."""
    try:
        result = find_duplicates(
            root,
            ignored_dirs=list(ignored_dirs),
            on_progress=on_progress,
            should_cancel=should_cancel,
            confirm_large_folder=confirm_large_folder,
            hash_cache=hash_cache,
        )
    except OperationCancelled:
        return ScanOutcome(cancelled=True)
    except OSError as exc:
        return ScanOutcome(error_code="DOUBLONS_IO_ERROR", error_detail=str(exc))
    return ScanOutcome(result=result)


# (ignorer ce fichier ?, appliquer ce choix aux suivants ?)
FileErrorAnswer = Tuple[bool, bool]


@dataclass
class MoveOutcome:
    ok: bool
    error_code: Optional[str] = None
    error_detail: str = ""
    # Ce qui a réellement bougé (à retirer du résultat affiché, jamais une
    # nouvelle analyse) et ce qui a été ignoré après confirmation.
    moved_units: List[Unit] = field(default_factory=list)
    skipped: List[Tuple[Unit, MoveFileFailed]] = field(default_factory=list)
    last_file_error: Optional[MoveFileFailed] = None


# Mêmes codes que les anciennes branches de `DoublonsMoveRunner` : rien n'a
# bougé (refus avant tout déplacement réel, dont la limite de taille FAT).
_REFUSAL_CODES = (
    (DestinationNotWritable, "DESTINATION_NOT_WRITABLE"),
    (InsufficientDiskSpace, "INSUFFICIENT_DISK_SPACE"),
    (DestinationInsideRootNotAllowed, "DESTINATION_INSIDE_ROOT"),
    (DestinationIsFilesystemRoot, "DESTINATION_FILESYSTEM_ROOT"),
    (FatFileSizeLimitExceeded, "FAT_FILE_SIZE_LIMIT"),
    (DuplicatesOutsideRoot, "PATH_OUTSIDE_ROOT"),
)


def run_move(
    root: str,
    units: List[Unit],
    dry_run: bool,
    destination: Optional[str] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    ask_file_error: Optional[Callable[[MoveFileFailed], FileErrorAnswer]] = None,
) -> MoveOutcome:
    """Met `units` de côté (`move.move_duplicates`). Un fichier qui échoue :
    `ask_file_error(exc)` -> (ignorer ?, pour les suivants aussi ?) ; plus
    de question après `AUTO_SKIP_AFTER` échecs de même raison déjà ignorés.
    Sans `ask_file_error`, le premier échec arrête tout (comme « Arrêter »)."""
    skipped_by_reason: Dict[str, int] = {}
    skip_all = False

    def on_file_error(exc: MoveFileFailed) -> bool:
        nonlocal skip_all
        already = skipped_by_reason.get(exc.reason, 0)
        if not (skip_all or already >= AUTO_SKIP_AFTER):
            if ask_file_error is None:
                return False
            skip, apply_to_following = ask_file_error(exc)
            if not skip:
                return False
            skip_all = apply_to_following
        skipped_by_reason[exc.reason] = already + 1
        return True

    try:
        move_duplicates(
            root,
            units,
            dry_run=dry_run,
            on_progress=on_progress,
            should_cancel=should_cancel,
            destination=destination,
            on_file_error=on_file_error,
        )
    except MoveCancelled as exc:
        return MoveOutcome(False, "CANCELLED", str(exc), moved_units=getattr(exc, "moved_units", []))
    except tuple(exc_type for exc_type, _ in _REFUSAL_CODES) as exc:
        code = next(code for exc_type, code in _REFUSAL_CODES if isinstance(exc, exc_type))
        return MoveOutcome(False, code, str(exc))
    except PartialMoveFailure as exc:
        # Au moins un fichier ignoré après confirmation : ni abandon complet,
        # ni succès total.
        return MoveOutcome(
            False, "PARTIAL_MOVE_COMPLETED", str(exc), moved_units=exc.moved_units, skipped=exc.skipped
        )
    except MoveFileFailed as exc:
        return MoveOutcome(
            False, "MOVE_FILE_FAILED", str(exc), moved_units=getattr(exc, "moved_units", []), last_file_error=exc
        )
    except CopyVerificationFailed as exc:
        return MoveOutcome(False, "COPY_VERIFICATION_FAILED", str(exc), moved_units=getattr(exc, "moved_units", []))
    except OSError as exc:
        return MoveOutcome(False, "DOUBLONS_IO_ERROR", str(exc), moved_units=getattr(exc, "moved_units", []))
    return MoveOutcome(True)


def exact_group_default(group: ExactDuplicateGroup) -> List[Unit]:
    """Contenu identique, donc « certain » : tout sauf le premier, gardé."""
    return group.units[1:]


def version_group_default(group: VersionGroup) -> List[Unit]:
    """Tout sauf la version suggérée -- une suggestion, jamais une garantie."""
    return [unit for unit in group.units if unit is not group.suggested_keep]


def default_units_to_move(result: ScanResult) -> List[Unit]:
    units: List[Unit] = []
    for group in result.exact_duplicate_groups:
        units += exact_group_default(group)
    for group in result.version_groups:
        units += version_group_default(group)
    return units


def prune_moved(result: ScanResult, moved_units: List[Unit]) -> ScanResult:
    """Résultat sans les unités déjà mises de côté (par identité d'objet,
    jamais par valeur) ; un groupe réduit à un seul exemplaire disparaît."""
    moved_ids = {id(unit) for unit in moved_units}

    def remaining(units: List[Unit]) -> List[Unit]:
        return [unit for unit in units if id(unit) not in moved_ids]

    exact_groups = [
        ExactDuplicateGroup(units=left, sha256=group.sha256)
        for group in result.exact_duplicate_groups
        if len(left := remaining(group.units)) >= 2
    ]
    version_groups = [
        VersionGroup(
            system_folder=group.system_folder,
            normalized_title=group.normalized_title,
            units=left,
            suggested_keep=group.suggested_keep if group.suggested_keep in left else left[0],
        )
        for group in result.version_groups
        if len(left := remaining(group.units)) >= 2
    ]
    return ScanResult(
        exact_duplicate_groups=exact_groups,
        version_groups=version_groups,
        excluded=result.excluded,
        files_scanned=result.files_scanned,
    )


def preferred_destination(root: str, remembered: Optional[str]) -> str:
    """Dernière destination choisie (`AppConfig.doublons_last_destination`)
    quand elle reste valable pour `root`, sinon `root/_doublons`."""
    if remembered:
        try:
            check_destination_allowed(root, remembered)
            return remembered
        except (DestinationInsideRootNotAllowed, DestinationIsFilesystemRoot, DestinationNotWritable):
            pass
    return default_destination(root)
