# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Threads Qt de l'outil « Ranger mes jeux » (docs/tri-roms.md) -- même
principe que `doublons_runner.py` : l'analyse et le déplacement de
milliers de fichiers ne tournent jamais sur le thread Qt principal."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal

from r36s_studio.doublons.move import DestinationNotWritable, InsufficientDiskSpace
from r36s_studio.tri.apply import apply_plan, undo_sort
from r36s_studio.tri.plan import SORT_JOURNAL_FILENAME
from r36s_studio.tri.plan import SortCancelled, SortPlan, SortRootRefused, TooManyFiles

__all__ = ["SortPlanRunner", "SortApplyRunner", "SortUndoRunner"]


class SortPlanRunner(QThread):
    progress = Signal(int)  # fichiers vus
    finished_plan = Signal(object)  # SortPlan
    cancelled = Signal()
    error = Signal(str, str)  # code, détail brut

    def __init__(self, build: Callable[..., SortPlan], parent=None):
        """`build(on_progress=..., should_cancel=...)` : `tri.plan.build_plan`
        ou `tri.filter.build_filter_plan`, arguments déjà liés."""
        super().__init__(parent)
        self._build = build
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            plan = self._build(on_progress=self.progress.emit, should_cancel=lambda: self._cancel_requested)
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

    def __init__(self, plan: SortPlan, parent=None, journal_name: str = SORT_JOURNAL_FILENAME):
        super().__init__(parent)
        self._plan = plan
        self._journal_name = journal_name
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        try:
            result = apply_plan(
                self._plan,
                on_progress=self.progress.emit,
                should_cancel=lambda: self._cancel_requested,
                journal_name=self._journal_name,
            )
        except DestinationNotWritable as exc:
            self.error.emit("NOT_WRITABLE", str(exc))
            return
        except InsufficientDiskSpace as exc:
            self.error.emit("NO_SPACE", str(exc))
            return
        except OSError as exc:
            self.error.emit("IO_ERROR", str(exc))
            return
        self.finished_apply.emit(result)


class SortUndoRunner(QThread):
    finished_undo = Signal(object)  # UndoResult
    error = Signal(str, str)

    def __init__(self, root: str, parent=None, journal_name: str = SORT_JOURNAL_FILENAME):
        super().__init__(parent)
        self._root = root
        self._journal_name = journal_name

    def run(self) -> None:
        try:
            result = undo_sort(self._root, self._journal_name)
        except OSError as exc:
            self.error.emit("IO_ERROR", str(exc))
            return
        self.finished_undo.emit(result)

