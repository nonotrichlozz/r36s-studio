# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Écran « Choisir l'écran de la console » : interface de la brique
`partitions/boot_sets.py`. Essais barrés et datés (`config.json::
boot_set_trials`), confirmation simple avant d'écrire (pas la fenêtre
rouge : rien n'est détruit, l'origine est gardée sur la carte), question
« a-t-elle démarré ? » à la réouverture. Ne dit jamais qu'un écran est le
bon : seul un démarrage le dit."""

from __future__ import annotations

import subprocess
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.partitions import boot_sets
from r36s_studio.partitions.locate import BOOT_LABEL, PartitionNotFound, PartitionNotMounted, locate_mounted, unmount_forced

from .screens import Dialog
from .strings import tr

# (résultat boot_sets_result, code d'erreur) -- fourni par main_window sous Windows.
ElevatedBootSets = Callable[[List[str]], Tuple[Optional[dict], Optional[str]]]


def action_argv(apply: Optional[str] = None, restore: bool = False) -> List[str]:
    if apply is not None:
        return ["--apply", apply]
    return ["--restore"] if restore else []


class BootSetsRunner(QThread):
    """Lecture ou écriture du BOOT hors du thread Qt (montage bloquant).
    Sous Windows, un BOOT EFI refuse l'accès sans élévation : on repasse
    alors par le worker élevé (`elevated`), comme « Identifier ma console »."""

    finished_boot_sets = Signal(object, object)  # dict | None, clé d'erreur | None

    def __init__(self, device_path: str, action: List[str], elevated: Optional[ElevatedBootSets] = None, parent=None):
        super().__init__(parent)
        self._device_path = device_path
        self._action = action
        self._elevated = elevated

    def run(self) -> None:
        result, error = self._run()
        self.finished_boot_sets.emit(result, error)

    def _run(self) -> Tuple[Optional[dict], Optional[str]]:
        try:
            boot = locate_mounted(self._device_path, BOOT_LABEL)
        except (PartitionNotFound, PartitionNotMounted, OSError, subprocess.CalledProcessError):
            return None, "no_boot"
        denied = False
        try:
            return self._direct(boot.mountpoint), None
        except PermissionError:
            denied = True
        except boot_sets.UnknownBootSet:
            return None, "unknown_set"
        except boot_sets.OriginalsMissing:
            return None, "originals_missing"
        except (OSError, ValueError):
            return None, "io"
        finally:
            unmount_forced(boot)
        if not denied or self._elevated is None:
            return None, "access_denied"
        result, code = self._elevated(self._action)
        if result is not None:
            return result, None
        if code == "ELEVATION_REFUSED":
            return None, "elevation_refused"
        if code == "SOURCE_NOT_FOUND":
            return None, "unknown_set" if self._action[:1] == ["--apply"] else "originals_missing"
        return None, "io"

    def _direct(self, root: str) -> dict:
        if self._action[:1] == ["--apply"]:
            boot_sets.apply_set(root, self._action[1])
        elif self._action == ["--restore"]:
            boot_sets.restore_original(root)
        return boot_sets.describe(root)


def _short_date(iso: str) -> str:
    parts = iso.split("-")
    return f"{parts[2]}/{parts[1]}/{parts[0]}" if len(parts) == 3 else iso


class BootSetsDialog(Dialog):
    """Pages : liste, confirmation, après l'essai, question du démarrage.
    N'écrit rien elle-même : émet des signaux, `main_window` agit."""

    apply_requested = Signal(str)  # set_id
    restore_requested = Signal()
    outcome_answered = Signal(str, str)  # set_id, "booted" | "failed"
    eject_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("boot_sets_title"))
        self._result: dict = {}
        self._trials: Dict[str, dict] = {}
        self._pending_set: Optional[str] = None
        self._restore_pending = False

        layout = QVBoxLayout(self)
        title = QLabel(tr("boot_sets_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)
        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setProperty("role", "secondary")
        layout.addWidget(self._message)

        self._pages = QStackedWidget()
        layout.addWidget(self._pages)
        self._list_page = self._build_list_page()
        self._confirm_page, self._confirm_text = self._build_question_page(
            (tr("boot_sets_confirm_yes"), self._on_confirmed), (tr("boot_sets_cancel"), self._show_list)
        )
        self._done_page, self._done_text = self._build_question_page(
            (tr("boot_sets_eject"), self.eject_requested.emit), (tr("boot_sets_close"), self.close)
        )
        self._outcome_page, self._outcome_text = self._build_question_page(
            (tr("boot_sets_outcome_booted"), lambda: self._answer("booted")),
            (tr("boot_sets_outcome_failed"), lambda: self._answer("failed")),
            (tr("boot_sets_outcome_later"), self._show_list),
        )
        for page in (self._list_page, self._confirm_page, self._done_page, self._outcome_page):
            self._pages.addWidget(page)

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.itemSelectionChanged.connect(self._update_buttons)
        box.addWidget(self._list)
        row = QHBoxLayout()
        self.try_button = QPushButton(tr("boot_sets_try_button"))
        self.restore_button = QPushButton(tr("boot_sets_restore_button"))
        self.close_button = QPushButton(tr("boot_sets_close"))
        self.try_button.clicked.connect(self._on_try)
        self.restore_button.clicked.connect(self._on_restore)
        self.close_button.clicked.connect(self.close)
        for button in (self.try_button, self.restore_button, self.close_button):
            button.setAutoDefault(False)
            row.addWidget(button)
        box.addLayout(row)
        return page

    def _build_question_page(self, *buttons) -> Tuple[QWidget, QLabel]:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        text = QLabel()
        text.setWordWrap(True)
        box.addWidget(text)
        row = QHBoxLayout()
        for label, slot in buttons:
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(slot)
            row.addWidget(button)
        box.addLayout(row)
        return page, text

    # --- état reçu de main_window ------------------------------------------

    def set_busy(self, busy: bool) -> None:
        self._pages.setEnabled(not busy)
        if busy:
            self._message.setText(tr("boot_sets_busy"))

    def set_result(self, result: dict, trials: List[dict], just_applied: bool = False) -> None:
        self._result = result
        self._trials = {t["set_id"]: t for t in trials}
        self._pages.setEnabled(True)
        self._fill_list()
        applied = result.get("applied")
        if just_applied:
            self._message.setText("")
            self._done_text.setText(tr("boot_sets_done_text", name=self._name(applied)))
            self._pages.setCurrentWidget(self._done_page)
        elif applied and self._trials.get(applied, {}).get("outcome") == "tried":
            self._message.setText("")
            self._outcome_text.setText(tr("boot_sets_outcome_question", name=self._name(applied)))
            self._pages.setCurrentWidget(self._outcome_page)
        else:
            self._show_list()

    def set_error(self, error_key: str) -> None:
        self._pages.setEnabled(True)
        self._show_list()
        self._message.setText(tr(f"boot_sets_error_{error_key}"))

    # --- interne -----------------------------------------------------------

    def _name(self, set_id: Optional[str]) -> str:
        for entry in self._result.get("sets", []):
            if entry["set_id"] == set_id:
                return entry["name"]
        return self._trials.get(set_id, {}).get("name", set_id or "")

    def _fill_list(self) -> None:
        self._list.clear()
        applied = self._result.get("applied")
        for entry in self._result.get("sets", []):
            label = entry["name"]
            trial = self._trials.get(entry["set_id"])
            if trial is not None:
                label += " — " + tr(f"boot_sets_trial_{trial['outcome']}", date=_short_date(trial["date"]))
            if entry["set_id"] == applied:
                label += " — " + tr("boot_sets_current")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, entry["set_id"])
            if trial is not None and trial["outcome"] != "booted":
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)
            self._list.addItem(item)

    def _show_list(self) -> None:
        self._message.setText(tr("boot_sets_hint") if self._result.get("sets") else tr("boot_sets_empty"))
        self._pages.setCurrentWidget(self._list_page)
        self._update_buttons()

    def _selected(self) -> Optional[str]:
        items = self._list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _update_buttons(self) -> None:
        self.try_button.setEnabled(self._selected() is not None)
        self.restore_button.setEnabled(bool(self._result.get("can_restore")))

    def _on_try(self) -> None:
        self._pending_set, self._restore_pending = self._selected(), False
        self._confirm_text.setText(tr("boot_sets_confirm_text", name=self._name(self._pending_set)))
        self._message.setText("")
        self._pages.setCurrentWidget(self._confirm_page)

    def _on_restore(self) -> None:
        self._pending_set, self._restore_pending = None, True
        self._confirm_text.setText(tr("boot_sets_restore_confirm"))
        self._message.setText("")
        self._pages.setCurrentWidget(self._confirm_page)

    def _on_confirmed(self) -> None:
        if self._restore_pending:
            self.restore_requested.emit()
        elif self._pending_set is not None:
            self.apply_requested.emit(self._pending_set)

    def _answer(self, outcome: str) -> None:
        self.outcome_answered.emit(self._result.get("applied") or "", outcome)
