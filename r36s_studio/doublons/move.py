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

"""Déplacement des doublons écartés vers `_doublons/` (docs/doublons.md)
-- **jamais une suppression** : `shutil.move`, jamais `Path.unlink()`.

Garde-fous ajoutés après validation du plan, dans cet ordre, tous avant
le premier octet réellement déplacé :

1. Chaque fichier des unités à déplacer doit se trouver sous `root`
   (`DuplicatesOutsideRoot` sinon) -- cette liste ne doit structurellement
   contenir que des fichiers issus du scan de ce même dossier.
2. `_doublons/` doit être accessible en écriture (`DestinationNotWritable`).
3. `_doublons/` doit être sur le même volume que `root`
   (`VolumeMismatch`) -- sinon un déplacement devient une copie lente, et
   l'annulation ultérieure ne serait plus fiable.
4. L'espace disque disponible doit couvrir le total à déplacer
   (`InsufficientDiskSpace`) -- un déplacement reste normalement gratuit
   en espace sur un même volume, mais `shutil.move` retombe sur une
   copie+suppression dès qu'un cas limite l'empêche (point de montage
   imbriqué, ci-dessus) ; vérifié par prudence.

**Mode simulation** (`dry_run=True`) -- mêmes vérifications, mais aucun
fichier déplacé, aucune écriture dans le journal : rien à annuler
puisque rien n'a bougé.

**Journal au fil de l'eau** -- une entrée ajoutée et le fichier
`journal.json` réécrit sur disque immédiatement après *chaque* fichier
réellement déplacé, jamais accumulées en mémoire jusqu'à la fin du lot :
une interruption brutale (crash, coupure) laisse un journal qui reflète
exactement ce qui a réellement été déplacé, exploitable par
`undo.undo_all`."""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from .scan import DUPLICATES_DIR_NAME, Unit

__all__ = [
    "JOURNAL_FILENAME",
    "MoveProgressCallback",
    "MoveCancelled",
    "DestinationNotWritable",
    "InsufficientDiskSpace",
    "VolumeMismatch",
    "DuplicatesOutsideRoot",
    "move_duplicates",
    "has_pending_journal_entries",
]

JOURNAL_FILENAME = "journal.json"

MoveProgressCallback = Callable[[int, int], None]  # (fait, total)

_PROBE_FILENAME = ".r36s_studio_doublons_write_test"


class MoveCancelled(Exception):
    def __init__(self, files_moved: int):
        super().__init__(f"Déplacement annulé après {files_moved} fichier(s).")
        self.files_moved = files_moved


class DestinationNotWritable(Exception):
    def __init__(self, path: str, reason: str = ""):
        detail = f" ({reason})" if reason else ""
        super().__init__(f"Impossible d'écrire dans « {path} »{detail}.")
        self.path = path


class InsufficientDiskSpace(Exception):
    def __init__(self, path: str, needed_bytes: int, available_bytes: int):
        super().__init__(
            f"Espace insuffisant sur « {path} » : {needed_bytes} octets nécessaires, "
            f"{available_bytes} disponibles."
        )
        self.path = path
        self.needed_bytes = needed_bytes
        self.available_bytes = available_bytes


class VolumeMismatch(Exception):
    def __init__(self, root: str, doublons_dir: str):
        super().__init__(f"« {doublons_dir} » n'est pas sur le même volume que « {root} ».")
        self.root = root
        self.doublons_dir = doublons_dir


class DuplicatesOutsideRoot(Exception):
    def __init__(self, path: str, root: str):
        super().__init__(f"« {path} » n'est pas sous « {root} ».")
        self.path = path
        self.root = root


def _check_writable(directory: Path) -> None:
    """Même principe que `partitions/copy.py::_check_writable` (sonde
    d'écriture réelle, jamais les seuls bits de permission) -- non
    réutilisé directement pour ne pas introduire de dépendance vers
    `partitions/` (§ architecture, l'outil doit rester autonome)."""
    probe = directory / _PROBE_FILENAME
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with open(probe, "wb") as handle:
            handle.write(b"\0")
    except OSError as exc:
        raise DestinationNotWritable(str(directory), str(exc)) from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _check_same_volume(root: Path, doublons_dir: Path) -> None:
    try:
        if os.stat(root).st_dev != os.stat(doublons_dir).st_dev:
            raise VolumeMismatch(str(root), str(doublons_dir))
    except OSError:
        pass


def _check_disk_space(root: Path, needed_bytes: int) -> None:
    usage = shutil.disk_usage(root)
    if usage.free < needed_bytes:
        raise InsufficientDiskSpace(str(root), needed_bytes, usage.free)


def _unique_destination(dest: Path) -> Path:
    """`dest` existe déjà (un précédent passage a déjà déplacé un fichier
    au même chemin relatif) -- ajoute un suffixe numérique avant
    l'extension plutôt que d'écraser silencieusement."""
    if not dest.exists():
        return dest
    counter = 2
    while True:
        candidate = dest.with_name(f"{dest.stem}_{counter}{dest.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _read_journal(journal_path: Path) -> List[dict]:
    try:
        raw = journal_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    return data if isinstance(data, list) else []


def _write_journal(journal_path: Path, entries: List[dict]) -> None:
    journal_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_journal_entry(journal_path: Path, source: str, destination: str) -> None:
    entries = _read_journal(journal_path)
    entries.append(
        {
            "source": source,
            "destination": destination,
            "moved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _write_journal(journal_path, entries)


def move_duplicates(
    root: str,
    units: List[Unit],
    dry_run: bool = False,
    on_progress: Optional[MoveProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> int:
    """Déplace les fichiers de `units` (déjà exclues du/des fichier(s)
    gardé(s) -- construit ainsi par l'appelant, l'écran de résultats)
    vers `root/_doublons/<chemin relatif à root>`, un `Unit` entier ou
    rien (jamais un membre isolé d'un groupe lié). Retourne le nombre de
    fichiers déplacés (ou qui l'auraient été, en simulation)."""
    root_path = Path(root).resolve()
    doublons_dir = root_path / DUPLICATES_DIR_NAME

    all_members: List[Path] = [member for unit in units for member in unit.members]
    for member in all_members:
        try:
            member.resolve().relative_to(root_path)
        except ValueError:
            raise DuplicatesOutsideRoot(str(member), str(root_path)) from None

    total = len(all_members)

    if dry_run:
        if doublons_dir.exists():
            _check_writable(doublons_dir)
            _check_same_volume(root_path, doublons_dir)
        done = 0
        for unit in units:
            if should_cancel is not None and should_cancel():
                raise MoveCancelled(done)
            done += len(unit.members)
            if on_progress is not None:
                on_progress(done, total)
        return done

    total_bytes = sum(unit.total_size_bytes for unit in units)
    doublons_dir.mkdir(parents=True, exist_ok=True)
    _check_writable(doublons_dir)
    _check_same_volume(root_path, doublons_dir)
    _check_disk_space(root_path, total_bytes)

    journal_path = doublons_dir / JOURNAL_FILENAME
    done = 0
    for unit in units:
        if should_cancel is not None and should_cancel():
            raise MoveCancelled(done)
        for member in unit.members:
            relative = member.resolve().relative_to(root_path)
            destination = _unique_destination(doublons_dir / relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(member), str(destination))
            _append_journal_entry(journal_path, str(member), str(destination))
            done += 1
            if on_progress is not None:
                on_progress(done, total)
    return done


def has_pending_journal_entries(root: str) -> bool:
    """`True` si `_doublons/journal.json` contient au moins une entrée --
    sert à activer/désactiver le bouton « Tout annuler » côté GUI sans
    lui faire lire le journal directement."""
    journal_path = Path(root).resolve() / DUPLICATES_DIR_NAME / JOURNAL_FILENAME
    return bool(_read_journal(journal_path))
