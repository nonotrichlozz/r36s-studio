# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Écran « Copier des jeux sur ma console (USB) » pour une console KNULLI
en mode ADB (docs/knulli-adb.md) -- autonome comme `tri_screen.py` : pages
(choix, analyse, résumé, copie, résultat) et threads gérés ici, un seul
point d'entrée (`start`) pour `main_window.py`.

Aucune fenêtre rouge : copie de fichiers, pas d'écriture sur le
périphérique brut (CLAUDE.md §5). Le résumé est la confirmation ; un
fichier déjà présent n'est remplacé qu'après une question explicite."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.android.knulli import CopyItem, CopyPlan, CopyResult
from r36s_studio.android.models import LinuxConsole

from .android_runner import KnulliCopyRunner, KnulliPlanRunner
from .screens import Screen, _format_size
from .strings import tr
from .tri_screen import _secondary, _title, _warning_frame

__all__ = ["KnulliCopyScreen"]

_MIB = 1024**2


def _reason(reason: str, detail: str = "") -> str:
    key = reason.split(":", 1)[0]
    return tr(f"knulli_reason_{key}", detail=detail)


class KnulliCopyScreen(Screen):
    back_requested = Signal()

    PAGE_CHOOSE, PAGE_SCAN, PAGE_SUMMARY, PAGE_COPY, PAGE_RESULT = range(5)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._adb_path = ""
        self._serial = ""
        self._plan: Optional[CopyPlan] = None
        self._plan_runner: Optional[KnulliPlanRunner] = None
        self._copy_runner: Optional[KnulliCopyRunner] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)
        for builder in (
            self._build_choose_page,
            self._build_scan_page,
            self._build_summary_page,
            self._build_copy_page,
            self._build_result_page,
        ):
            self._stack.addWidget(builder())

    # --- pages ------------------------------------------------------------

    def _header(self, root: QVBoxLayout, back: bool = True) -> None:
        header = QHBoxLayout()
        if back:
            back_button = QPushButton(tr("knulli_back_button"))
            back_button.setProperty("role", "flat")
            back_button.clicked.connect(self.back_requested.emit)
            header.addWidget(back_button)
        header.addWidget(_title(tr("knulli_title")), 1)
        root.addLayout(header)

    def _build_choose_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self._header(root)
        self._console_label = _secondary()
        root.addWidget(self._console_label)
        root.addWidget(_secondary(tr("knulli_hint")))
        choose = QPushButton(tr("knulli_choose_folder_button"))
        choose.setProperty("role", "primary")
        choose.clicked.connect(self._on_choose_folder_clicked)
        root.addWidget(choose, 0, Qt.AlignLeft)
        self._choose_error_label = _secondary()
        self._choose_error_frame = _warning_frame(self._choose_error_label)
        self._choose_error_frame.setVisible(False)
        root.addWidget(self._choose_error_frame)
        root.addStretch()
        return page

    def _build_scan_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self._header(root, back=False)
        root.addWidget(_secondary(tr("knulli_scanning")))
        bar = QProgressBar()
        bar.setRange(0, 0)
        root.addWidget(bar)
        root.addStretch()
        return page

    def _build_summary_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self._header(root)
        self._summary_label = _secondary()
        root.addWidget(self._summary_label)
        self._space_label = _secondary()
        self._space_frame = _warning_frame(self._space_label)
        root.addWidget(self._space_frame)
        self._folders_list = QListWidget()
        root.addWidget(self._folders_list, 2)
        self._skipped_title = _secondary()
        root.addWidget(self._skipped_title)
        self._skipped_list = QListWidget()
        root.addWidget(self._skipped_list, 1)
        buttons = QHBoxLayout()
        self._copy_button = QPushButton(tr("knulli_copy_button"))
        self._copy_button.setProperty("role", "primary")
        self._copy_button.clicked.connect(self._on_copy_clicked)
        buttons.addWidget(self._copy_button)
        other = QPushButton(tr("knulli_other_folder_button"))
        other.clicked.connect(self._on_choose_folder_clicked)
        buttons.addWidget(other)
        buttons.addStretch()
        root.addLayout(buttons)
        return page

    def _build_copy_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self._header(root, back=False)
        root.addWidget(_secondary(tr("knulli_copying")))
        self._copy_bar = QProgressBar()
        root.addWidget(self._copy_bar)
        self._copy_count_label = _secondary()
        root.addWidget(self._copy_count_label)
        self._copy_file_label = _secondary()
        root.addWidget(self._copy_file_label)
        self._cancel_button = QPushButton(tr("knulli_cancel_button"))
        self._cancel_button.clicked.connect(self._on_cancel_clicked)
        root.addWidget(self._cancel_button, 0, Qt.AlignLeft)
        root.addStretch()
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self._header(root)
        self._result_label = _secondary()
        root.addWidget(self._result_label)
        self._reload_label = _secondary()
        root.addWidget(self._reload_label)
        self._failures_list = QListWidget()
        root.addWidget(self._failures_list, 1)
        again = QPushButton(tr("knulli_again_button"))
        again.setProperty("role", "primary")
        again.clicked.connect(self._on_choose_folder_clicked)
        root.addWidget(again, 0, Qt.AlignLeft)
        return page

    # --- entrée -----------------------------------------------------------

    def start(self, adb_path: str, serial: str, console: LinuxConsole) -> None:
        self._adb_path, self._serial = adb_path, serial
        self._console_label.setText(tr("knulli_console_label", version=console.version or "?"))
        self._choose_error_frame.setVisible(False)
        self._stack.setCurrentIndex(self.PAGE_CHOOSE)

    def _on_choose_folder_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("knulli_choose_folder_button"))
        if path:
            self.analyse(path)

    def analyse(self, path: str) -> None:
        self._stack.setCurrentIndex(self.PAGE_SCAN)
        runner = KnulliPlanRunner(self._adb_path, self._serial, path, self)
        runner.finished_plan.connect(self._show_summary)
        runner.error.connect(self._on_console_error)
        runner.finished.connect(runner.deleteLater)
        self._plan_runner = runner
        runner.start()

    def _on_console_error(self, detail: str) -> None:
        print(f"[KNULLI] {detail}")
        self._choose_error_label.setText(tr("knulli_error_console"))
        self._choose_error_frame.setVisible(True)
        self._stack.setCurrentIndex(self.PAGE_CHOOSE)

    # --- résumé -----------------------------------------------------------

    def _show_summary(self, plan: CopyPlan) -> None:
        self._plan_runner = None
        self._plan = plan
        self._refresh_summary()
        self._stack.setCurrentIndex(self.PAGE_SUMMARY)

    def _refresh_summary(self) -> None:
        plan = self._plan
        free = plan.free_bytes or 0
        self._summary_label.setText(
            tr(
                "knulli_summary",
                count=len(plan.items),
                size=_format_size(plan.bytes_needed()),
                free=_format_size(free),
                after=_format_size(max(0, free - plan.bytes_needed())),
            )
            if plan.items
            else tr("knulli_summary_nothing")
        )
        missing = plan.missing_bytes()
        self._space_label.setText(tr("knulli_space_refused", missing=_format_size(missing)))
        self._space_frame.setVisible(missing > 0)
        self._copy_button.setEnabled(bool(plan.items) and missing == 0)

        self._folders_list.clear()
        for folder, (count, size) in plan.by_folder().items():
            self._folders_list.addItem(tr("knulli_folder_row", folder=folder, count=count, size=_format_size(size)))
        for item in plan.items:
            if item.renamed_from:
                self._folders_list.addItem(tr("knulli_renamed_row", old=item.renamed_from, new=item.remote))

        self._skipped_list.clear()
        for skipped in plan.skipped:
            self._skipped_list.addItem(f"{skipped.local.name} : {_reason(skipped.reason, skipped.detail)}")
        self._skipped_title.setText(tr("knulli_skipped_title", count=len(plan.skipped)))
        self._skipped_title.setVisible(bool(plan.skipped))
        self._skipped_list.setVisible(bool(plan.skipped))

    def _ask_conflict(self, item: CopyItem) -> str:
        """« skip », « replace » ou « skip_all »."""
        box = QMessageBox(self)
        box.setWindowTitle(tr("knulli_conflict_title"))
        box.setTextFormat(Qt.PlainText)
        box.setText(
            tr(
                "knulli_conflict_message",
                name=item.remote,
                old=_format_size(item.existing_size or 0),
                new=_format_size(item.size),
            )
        )
        skip = box.addButton(tr("knulli_conflict_skip"), QMessageBox.RejectRole)
        replace = box.addButton(tr("knulli_conflict_replace"), QMessageBox.AcceptRole)
        skip_all = box.addButton(tr("knulli_conflict_skip_all"), QMessageBox.RejectRole)
        box.setDefaultButton(skip)
        box.exec()
        clicked = box.clickedButton()
        return "replace" if clicked is replace else "skip_all" if clicked is skip_all else "skip"

    def _on_copy_clicked(self) -> None:
        plan = self._plan
        skip_all = False
        for item in list(plan.conflicts()):
            choice = "skip" if skip_all else self._ask_conflict(item)
            skip_all = skip_all or choice == "skip_all"
            if choice == "replace":
                item.replace = True
            else:
                plan.skip(item)
        self._refresh_summary()
        if not self._copy_button.isEnabled():
            return  # plus rien à copier, ou la place manque toujours : le résumé le dit
        self._copy_bar.setRange(0, max(1, sum(item.size for item in plan.items) // _MIB))
        self._copy_bar.setValue(0)
        self._copy_file_label.setText("")
        self._copy_count_label.setText("")
        self._cancel_button.setEnabled(True)
        self._stack.setCurrentIndex(self.PAGE_COPY)
        runner = KnulliCopyRunner(self._adb_path, self._serial, plan, self)
        runner.progress.connect(self._on_progress)
        runner.finished_copy.connect(self._show_result)
        runner.not_enough_space.connect(self._on_not_enough_space)
        runner.error.connect(self._on_console_error)
        runner.finished.connect(runner.deleteLater)
        self._copy_runner = runner
        runner.start()

    def _on_progress(self, done: int, total: int, name: str) -> None:
        self._copy_bar.setRange(0, max(1, total // _MIB))
        self._copy_bar.setValue(done // _MIB)
        self._copy_count_label.setText(tr("knulli_copy_count", done=done // _MIB, total=total // _MIB))
        self._copy_file_label.setText(name)

    def _on_cancel_clicked(self) -> None:
        if self._copy_runner is not None:
            self._cancel_button.setEnabled(False)
            self._copy_runner.cancel()

    def _on_not_enough_space(self, needed: int, free: int) -> None:
        self._copy_runner = None
        self._plan.free_bytes = free
        self._refresh_summary()
        self._stack.setCurrentIndex(self.PAGE_SUMMARY)

    # --- résultat ---------------------------------------------------------

    def _show_result(self, result: CopyResult, reload_status: str) -> None:
        self._copy_runner = None
        key = "knulli_result_cancelled" if result.cancelled else "knulli_result"
        self._result_label.setText(tr(key, copied=len(result.copied), failed=len(result.failures)))
        self._reload_label.setText("" if reload_status == "nothing_copied" else tr(f"knulli_reload_{reload_status}"))
        self._failures_list.clear()
        for item, reason in result.failures:
            self._failures_list.addItem(f"{item.local.name} : {_reason(reason, item.remote)}")
            print(f"[KNULLI] échec {item.local} -> {item.remote} : {reason}")
        self._failures_list.setVisible(bool(result.failures))
        self._stack.setCurrentIndex(self.PAGE_RESULT)

    def is_busy(self) -> bool:
        return self._plan_runner is not None or self._copy_runner is not None
