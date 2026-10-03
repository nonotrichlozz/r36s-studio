# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Threads Qt de l'outil « Ranger mes jeux » (docs/tri-roms.md) -- même
principe que `doublons_runner.py` : l'analyse et le déplacement de
milliers de fichiers ne tournent jamais sur le thread Qt principal."""

from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QThread, Signal

from r36s_studio.doublons.move import DestinationNotWritable
from r36s_studio.tri.apply import apply_plan, undo_sort
from r36s_studio.tri.plan import SortCancelled, SortPlan, SortRootRefused, TooManyFiles, build_plan

__all__ = ["SortPlanRunner", "SortApplyRunner", "SortUndoRunner"]


class SortPlanRunner(QThread):
    progress = Signal(int)  # fichiers vus
    finished_plan = Signal(object)  # SortPlan
    cancelled = Signal()
    error = Signal(str, str)  # code, détail brut

    def __init__(self, root: str, firmware_id: str, ignored_dirs: Iterable[str], parent=None):
        super().__init__(parent)
        self._root = root
        self._firmware_id = firmware_id
        self._ignored_dirs = list(ignored_dirs)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            plan = build_plan(
                self._root,
                self._firmware_id,
                self._ignored_dirs,
                on_progress=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
            )
        except SortCancelled:
            self.cancelled.emit()
            return
        except SortRootRefused as exc:
            self.error.emit(f"ROOT_{exc.reason.upper()}", str(exc))
            return
        except TooManyFiles as exc:
            self.error.emit("TOO_MANY_FILES", str(exc))
            return
        except OSError as exc:
            self.error.emit("IO_ERROR", str(exc))
            return
        self.finished_plan.emit(plan)


class SortApplyRunner(QThread):
    progress = Signal(int, int)  # fait, total
    finished_apply = Signal(object)  # ApplyResult
    error = Signal(str, str)

    def __init__(self, plan: SortPlan, parent=None):
        super().__init__(parent)
        self._plan = plan
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = apply_plan(self._plan, on_progress=self.progress.emit, should_cancel=lambda: self._cancel_requested)
        except DestinationNotWritable as exc:
            self.error.emit("NOT_WRITABLE", str(exc))
            return
        except OSError as exc:
            self.error.emit("IO_ERROR", str(exc))
            return
        self.finished_apply.emit(result)


class SortUndoRunner(QThread):
    finished_undo = Signal(object)  # UndoResult
    error = Signal(str, str)

    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        self._root = root

    def run(self) -> None:
        try:
            result = undo_sort(self._root)
        except OSError as exc:
            self.error.emit("IO_ERROR", str(exc))
            return
        self.finished_undo.emit(result)

