# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""« Convertir des jeux » (docs/tri-roms.md) -- phase 1 : `.7z` → `.zip`.

Un jeu dans un format que le firmware ne lit pas s'affiche mais ne démarre
pas (TreeFrogUI : `picoarch` ne décompresse que le `.zip`, un `.7z` donne
un écran noir). L'analyse s'appuie sur la table des extensions acceptées
par dossier (`tables.py`, `accepted_extensions`) : un `.7z` est proposé à
la conversion sauf si son dossier est connu du firmware **et** l'accepte
(ArkOS, ROCKNIX, EmuELEC : laissé tel quel). Dossier inconnu ou liste
inconnue (TreeFrogUI) : proposé -- un `.zip` est lu partout où un `.7z`
l'est.

Conversion d'une archive : extraction dans un dossier temporaire caché à
côté d'elle (py7zr ; un ROM pèse au plus quelques centaines de Mo, pas
besoin de flux), `.zip` (deflate) écrit dans ce même dossier, puis
**vérifié** -- CRC et taille de chaque fichier comparés à ceux annoncés par
le `.7z`, relecture complète du `.zip` -- et seulement ensuite renommé à
côté de l'original. `SevenZipFile.test()` n'est pas utilisé : il renvoie
`None` même pour une archive corrompue (constaté, py7zr 1.1.4).
L'original part dans `<dossier>/_originaux/<chemin d'origine>` (jamais
supprimé, jamais écrasé), le journal `_conversion_journal.json` permet
d'annuler. Place vérifiée avant chaque archive (extraction + `.zip`)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, List, Optional

import py7zr

from r36s_studio.doublons.move import (
    InsufficientDiskSpace,
    MoveFileFailed,
    _check_disk_space,
    _check_writable,
    _move_one_file,
    _unique_destination,
)
from r36s_studio.doublons.safety import LARGE_FOLDER_FILE_THRESHOLD, is_filesystem_root, is_whole_user_folder
from r36s_studio.doublons.undo import UndoConflict, UndoResult

from .apply import MAX_CONSECUTIVE_FAILURES, ApplyResult, _read_entries, journal_path
from .filter import safe_card_volume
from .plan import (
    CONVERT_JOURNAL_FILENAME,
    ORIGINALS_DIR_NAME,
    PlannedMove,
    SortCancelled,
    SortPlan,
    SortRootRefused,
    TooManyFiles,
    _walk,
)
from .tables import load_firmware_tables

__all__ = ["ConversionFailed", "build_convert_plan", "convert_7z_to_zip", "apply_conversion", "undo_conversion"]


class ConversionFailed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        # "password" | "unsafe_entry" | "empty" | "corrupt" | "verify" | "io" | "zip_exists"
        self.reason = reason


def build_convert_plan(
    root: str,
    firmware_id: str,
    ignored_dirs: Iterable[str] = (),
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> SortPlan:
    """`moves` : `.7z` à convertir (`folder` = dossier d'origine, pour
    l'aperçu) ; `left_in_place` : `.7z` laissés tels quels, avec la raison.
    Même refus d'office que le filtre (racine d'un disque sauf une carte
    retenue par `safety`, dossier personnel entier)."""
    card_volume = safe_card_volume(root)
    if is_filesystem_root(root) and card_volume is None:
        raise SortRootRefused(root, "filesystem_root")
    if is_whole_user_folder(root):
        raise SortRootRefused(root, "user_folder")
    table = load_firmware_tables()[firmware_id]
    folder_systems = {name.lower(): system_id for system_id, name in table.folders.items()}
    root_path = Path(root).resolve()
    plan = SortPlan(root=root_path, firmware_id=firmware_id, card_volume=card_volume)
    ignored_lower = frozenset(name.lower() for name in ignored_dirs)

    def on_file() -> None:
        plan.files_seen += 1
        if should_cancel is not None and should_cancel():
            raise SortCancelled()
        if plan.files_seen > LARGE_FOLDER_FILE_THRESHOLD:
            raise TooManyFiles(LARGE_FOLDER_FILE_THRESHOLD)
        if on_progress is not None:
            on_progress(plan.files_seen)

    for path in _walk(root_path, ignored_lower, {}, plan, on_file):
        if path.suffix.lower() != ".7z":
            continue
        system_id = folder_systems.get(path.parent.name.lower())
        accepted = table.accepted_extensions.get(system_id) if system_id is not None else None
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        move = partial(PlannedMove, [path], system_id, path.parent.relative_to(root_path).as_posix(), size_bytes=size)
        if accepted is not None and ".7z" in accepted:
            plan.left_in_place.append(move("seven_zip_read"))
        elif accepted is not None and ".zip" not in accepted:
            plan.left_in_place.append(move("zip_not_read"))
        elif path.with_suffix(".zip").exists():
            plan.left_in_place.append(move("zip_exists"))
        else:
            plan.moves.append(move("convert"))
    return plan


def _safe_member(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(parts) and "\\" not in name and ":" not in name and not name.startswith("/") and ".." not in parts


def convert_7z_to_zip(source: Path, target: Path) -> None:
    """Écrit `target` (deflate) avec le contenu vérifié de `source`, qui
    reste en place. Lève `ConversionFailed` (rien n'est laissé derrière) ou
    `InsufficientDiskSpace` (rien n'est écrit)."""
    workdir: Optional[Path] = None
    try:
        with py7zr.SevenZipFile(source) as archive:
            if archive.needs_password():
                raise ConversionFailed("password")
            infos = [info for info in archive.list() if not info.is_directory]
            if not infos:
                raise ConversionFailed("empty")
            if any(info.is_symlink or not _safe_member(info.filename) for info in infos):
                raise ConversionFailed("unsafe_entry")
            # Extraction temporaire + `.zip` : au pire deux fois la taille.
            _check_disk_space(source.parent, 2 * sum(info.uncompressed for info in infos))
            workdir = Path(tempfile.mkdtemp(prefix=".r36s_conversion_", dir=source.parent))
            archive.extractall(path=workdir / "contenu")
        built = workdir / target.name
        with zipfile.ZipFile(built, "w", zipfile.ZIP_DEFLATED) as out:
            for info in infos:
                out.write(workdir / "contenu" / PurePosixPath(info.filename), info.filename)
        with zipfile.ZipFile(built) as check:
            written = {entry.filename: entry for entry in check.infolist()}
            for info in infos:
                entry = written.get(info.filename)
                if entry is None or entry.file_size != info.uncompressed:
                    raise ConversionFailed("verify")
                if info.crc32 is not None and entry.CRC != info.crc32:
                    raise ConversionFailed("verify")
            if check.testzip() is not None:
                raise ConversionFailed("verify")
        if target.exists():
            raise ConversionFailed("zip_exists")
        os.replace(built, target)
    except (ConversionFailed, InsufficientDiskSpace):
        raise
    except OSError as exc:
        raise ConversionFailed("io") from exc
    except Exception as exc:  # archive hors de notre contrôle : py7zr, lzma, zlib lèvent chacun les leurs
        raise ConversionFailed("corrupt") from exc
    finally:
        if workdir is not None:
            shutil.rmtree(workdir, ignore_errors=True)


def _append_entry(journal: Path, source: Path, original: Path, created: Path) -> None:
    line = json.dumps(
        {
            "source": str(source),
            "destination": str(original),
            "created": str(created),
            "created_size": created.stat().st_size,
            "converted_at": datetime.now(timezone.utc).isoformat(),
        },
        ensure_ascii=False,
    )
    with open(journal, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def apply_conversion(
    plan: SortPlan,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    journal_name: str = CONVERT_JOURNAL_FILENAME,
) -> ApplyResult:
    """Convertit `plan.moves` un par un (`moved_files` = archives
    converties). Un échec sur une archive est consigné et la suite
    continue ; `InsufficientDiskSpace` arrête tout (les archives déjà
    converties restent annulables)."""
    _check_writable(plan.root)
    journal = journal_path(str(plan.root), journal_name)
    total = len(plan.moves)
    result = ApplyResult()
    consecutive_failures = 0
    for move in plan.moves:
        if should_cancel is not None and should_cancel():
            result.cancelled = True
            return result
        source = move.members[0]
        if not source.exists():
            result.missing_sources.append(source)
            continue
        target = source.with_suffix(".zip")
        if target.exists():
            result.skipped_existing.append(move)
            continue
        try:
            convert_7z_to_zip(source, target)
            original = _unique_destination(plan.root / ORIGINALS_DIR_NAME / source.relative_to(plan.root))
            try:
                _move_one_file(source, original, None, cross_volume=False)
            except MoveFileFailed as exc:
                # Retour à l'état de départ : jamais un `.zip` et son `.7z`
                # côte à côte (la console afficherait le jeu deux fois).
                target.unlink()
                raise ConversionFailed("io") from exc
        except ConversionFailed as exc:
            result.failures.append((source, exc.reason))
            consecutive_failures += 1
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                result.aborted = True
                return result
            continue
        consecutive_failures = 0
        _append_entry(journal, source, original, target)
        result.moved_files += 1
        if on_progress is not None:
            on_progress(result.moved_files, total)
    return result


def undo_conversion(root: str, journal_name: str = CONVERT_JOURNAL_FILENAME) -> UndoResult:
    """Remet chaque `.7z` à sa place et retire le `.zip` créé -- seulement
    s'il a gardé la taille notée au journal (sinon quelqu'un l'a remplacé :
    conflit, rien n'est touché). Du plus récent au plus ancien ; une entrée
    en conflit reste au journal pour un futur essai."""
    path = journal_path(root, journal_name)
    entries = _read_entries(path)
    result = UndoResult()
    remaining: List[dict] = []
    for entry in reversed(entries):
        source, original = Path(entry["source"]), Path(entry["destination"])
        created = Path(entry.get("created", ""))
        conflict = None
        if not original.exists():
            conflict = "destination_missing"
        elif source.exists():
            conflict = "source_occupied"
        elif not created.is_file() or created.stat().st_size != entry.get("created_size"):
            conflict = "created_changed"
        if conflict is None:
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(original), str(source))
                created.unlink()
            except OSError:
                conflict = "move_failed"
        if conflict is not None:
            result.conflicts.append(UndoConflict(str(source), str(original), conflict))
            remaining.append(entry)
            continue
        result.restored += 1
    if remaining:
        path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in reversed(remaining)), encoding="utf-8")
    elif entries:
        try:
            os.unlink(path)
        except OSError:
            pass
    return result
