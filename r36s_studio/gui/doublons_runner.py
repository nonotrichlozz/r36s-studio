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

"""Threads Qt pour l'outil « Doublons de jeux » (docs/doublons.md) --
fichier séparé de `partition_runner.py` (jamais une dépendance vers
`Device`/`partitions/`, § architecture : l'outil est autonome, aucune
élévation de privilèges n'est jamais nécessaire ici)."""

from __future__ import annotations

import threading
from typing import Iterable, List, Optional

from PySide6.QtCore import QThread, Signal

from r36s_studio.doublons.move import (
    DestinationNotWritable,
    DuplicatesOutsideRoot,
    InsufficientDiskSpace,
    MoveCancelled,
    VolumeMismatch,
    move_duplicates,
)
from r36s_studio.doublons.scan import OperationCancelled, Unit, find_duplicates
from r36s_studio.doublons.undo import UndoResult, undo_all

__all__ = ["DoublonsScanRunner", "DoublonsMoveRunner", "DoublonsUndoRunner"]


class DoublonsScanRunner(QThread):
    """Analyse en lecture seule d'un dossier quelconque -- `progress`
    émis pour chaque fichier rencontré (pas seulement les candidats
    retenus, § interface : une barre de progression a besoin de savoir
    que l'analyse avance même sur un dossier presque vide de ROMs).

    `large_folder_confirmation_needed` (§ garde-fou 2, seuil de 200 000
    fichiers) bloque le thread d'analyse jusqu'à ce que
    `resume_after_large_folder_confirmation` soit appelée depuis le
    thread GUI -- un `threading.Event`, même principe coopératif que
    `should_cancel` déjà utilisé partout ailleurs dans ce projet, mais
    qui doit ici faire attendre le thread plutôt que simplement
    l'arrêter."""

    progress = Signal(int)  # fichiers vus
    large_folder_confirmation_needed = Signal()
    finished_scan = Signal(object)  # ScanResult
    cancelled = Signal()
    error = Signal(str, str)  # code, msg

    def __init__(self, root: str, ignored_dirs: Iterable[str], parent=None):
        super().__init__(parent)
        self._root = root
        self._ignored_dirs = list(ignored_dirs)
        self._cancel_requested = False
        self._large_folder_event = threading.Event()
        self._large_folder_continue = False

    def cancel(self) -> None:
        """Coopératif, comme les autres runners de ce projet -- débloque
        aussi une éventuelle pause en attente de confirmation, pour que
        Annuler reste toujours immédiat même à ce moment précis."""
        self._cancel_requested = True
        self._large_folder_event.set()

    def resume_after_large_folder_confirmation(self, should_continue: bool) -> None:
        self._large_folder_continue = should_continue
        self._large_folder_event.set()

    def run(self) -> None:
        def on_progress(count: int) -> None:
            self.progress.emit(count)

        def should_cancel() -> bool:
            return self._cancel_requested

        def confirm_large_folder() -> bool:
            self._large_folder_event.clear()
            self.large_folder_confirmation_needed.emit()
            self._large_folder_event.wait()
            return self._large_folder_continue

        try:
            result = find_duplicates(
                self._root,
                ignored_dirs=self._ignored_dirs,
                on_progress=on_progress,
                should_cancel=should_cancel,
                confirm_large_folder=confirm_large_folder,
            )
        except OperationCancelled:
            self.cancelled.emit()
            return
        except OSError as exc:
            self.error.emit("DOUBLONS_IO_ERROR", str(exc))
            return

        self.finished_scan.emit(result)


class DoublonsMoveRunner(QThread):
    """Écarte les unités choisies dans l'écran de résultats vers
    `_doublons/` (`dry_run` -- § garde-fou 1, mode simulation). Signal
    `progress` distinct de `PartitionJobRunner` (octets/débit) : compte
    des fichiers, généralement peu nombreux."""

    progress = Signal(int, int)  # fait, total
    error = Signal(str, str)
    finished_move = Signal(bool)

    def __init__(self, root: str, units: List[Unit], dry_run: bool, parent=None):
        super().__init__(parent)
        self._root = root
        self._units = units
        self._dry_run = dry_run
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        def on_progress(done: int, total: int) -> None:
            self.progress.emit(done, total)

        def should_cancel() -> bool:
            return self._cancel_requested

        try:
            move_duplicates(
                self._root,
                self._units,
                dry_run=self._dry_run,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )
        except MoveCancelled as exc:
            self.error.emit("CANCELLED", str(exc))
            self.finished_move.emit(False)
            return
        except DestinationNotWritable as exc:
            self.error.emit("DESTINATION_NOT_WRITABLE", str(exc))
            self.finished_move.emit(False)
            return
        except InsufficientDiskSpace as exc:
            self.error.emit("INSUFFICIENT_DISK_SPACE", str(exc))
            self.finished_move.emit(False)
            return
        except VolumeMismatch as exc:
            self.error.emit("VOLUME_MISMATCH", str(exc))
            self.finished_move.emit(False)
            return
        except DuplicatesOutsideRoot as exc:
            self.error.emit("PATH_OUTSIDE_ROOT", str(exc))
            self.finished_move.emit(False)
            return
        except OSError as exc:
            self.error.emit("DOUBLONS_IO_ERROR", str(exc))
            self.finished_move.emit(False)
            return

        self.finished_move.emit(True)


class DoublonsUndoRunner(QThread):
    """« Tout annuler » (§ garde-fou 5, journal au fil de l'eau) -- lit et
    restaure directement depuis `_doublons/journal.json`, aucun paramètre
    au-delà du dossier racine."""

    finished_undo = Signal(object)  # UndoResult
    error = Signal(str, str)

    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self._root = root

    def run(self) -> None:
        try:
            result: Optional[UndoResult] = undo_all(self._root)
        except OSError as exc:
            self.error.emit("DOUBLONS_IO_ERROR", str(exc))
            return
        self.finished_undo.emit(result)
