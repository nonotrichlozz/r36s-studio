# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Écran « Ranger mes jeux » (docs/tri-roms.md) -- autonome : gère lui-
même ses pages (choix, analyse, aperçu, confirmation, déplacement,
résultat) et ses threads, pour que `main_window.py` n'ait qu'un point
d'entrée à câbler (même principe d'isolation que `consoles_diverses/`).

Aucune fenêtre rouge (`ConfirmDialog`) : elle est réservée aux écritures
sur le périphérique brut (CLAUDE.md §5). Le tri ne fait que déplacer des
fichiers dans un dossier déjà accessible, annulable -- une page de
confirmation simple suffit, jamais sautée."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.config import DEFAULT_DOUBLONS_IGNORED_FOLDERS
from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID
from r36s_studio.tri.apply import ApplyResult, has_journal
from r36s_studio.tri.filter import build_filter_plan
from r36s_studio.tri.plan import FILTER_JOURNAL_FILENAME, SORT_JOURNAL_FILENAME, PlannedMove, SortPlan, build_plan
from r36s_studio.tri.regions import LANGUAGE_CHOICES, REGION_CHOICES, RegionFilter
from r36s_studio.tri.tables import SORT_FIRMWARE_IDS, load_firmware_tables, load_systems

from . import reveal as reveal_module
from .screens import Screen, _format_size
from .strings import STRINGS, tr
from .tri_runner import SortApplyRunner, SortPlanRunner, SortUndoRunner

__all__ = ["TriScreen", "FilterScreen", "firmware_display_name"]

DEFAULT_SORT_FIRMWARE = "rocknix"


def firmware_display_name(firmware_id: str) -> str:
    entry = FIRMWARE_BY_ID.get(firmware_id)
    if entry is not None:
        return tr(entry.title_key)
    return tr(f"tri_firmware_{firmware_id}")


def reason_text(move: PlannedMove) -> str:
    system_label = ""
    if move.system_id is not None:
        system = load_systems().get(move.system_id)
        system_label = system.label if system is not None else move.system_id
    return tr(f"tri_reason_{move.reason}", detail=move.detail, system=system_label)


def _verification_text(firmware_id: str) -> str:
    verified = load_firmware_tables()[firmware_id].verified_on_hardware
    return tr("tri_firmware_verified" if verified else "tri_firmware_unverified")


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "title")
    label.setWordWrap(True)
    return label


def _secondary(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "secondary")
    label.setWordWrap(True)
    return label


def _warning_frame(label: QLabel) -> QFrame:
    """Encadré orange (`role="warning"`, même teinte que les bandeaux de
    `consoles_diverses/screen.py`), mais texte courant plutôt que
    `dangerTitle` : ces messages font plusieurs lignes, en gras ils
    écrasaient la liste des dossiers de l'aperçu (constaté au rendu)."""
    frame = QFrame()
    frame.setProperty("role", "warning")
    layout = QVBoxLayout(frame)
    label.setWordWrap(True)
    layout.addWidget(label)
    return frame


class TriScreen(Screen):
    """« Ranger des jeux mélangés ». `FilterScreen` (plus bas) réutilise
    toutes les pages sauf le choix, en remplaçant seulement ce qui diffère
    (`_t`, `_build_choose_options`, `_plan_builder`, aperçu, journal)."""

    back_requested = Signal()

    PAGE_CHOOSE, PAGE_SCAN, PAGE_PREVIEW, PAGE_CONFIRM, PAGE_MOVE, PAGE_RESULT = range(6)
    TEXT_PREFIX = "tri_"
    JOURNAL_NAME = SORT_JOURNAL_FILENAME

    def _t(self, key: str, **kwargs) -> str:
        """Texte propre à cet écran (`<TEXT_PREFIX><key>`) s'il existe,
        sinon celui du tri (`tri_<key>`), commun aux deux."""
        specific = self.TEXT_PREFIX + key
        return tr(specific if specific in STRINGS else "tri_" + key, **kwargs)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._root: Optional[str] = None
        # Destination distincte du dossier analysé (`None` : rangé sur place).
        self._destination: Optional[str] = None
        self._plan: Optional[SortPlan] = None
        self._plan_runner: Optional[SortPlanRunner] = None
        self._apply_runner: Optional[SortApplyRunner] = None
        self._undo_runner: Optional[SortUndoRunner] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 24)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack)
        for builder in (
            self._build_choose_page,
            self._build_scan_page,
            self._build_preview_page,
            self._build_confirm_page,
            self._build_move_page,
            self._build_result_page,
        ):
            self._stack.addWidget(builder())

    # --- construction des pages -------------------------------------------

    def _build_choose_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        header = QHBoxLayout()
        back_button = QPushButton(self._t("back_button"))
        back_button.setProperty("role", "flat")
        back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(back_button)
        header.addWidget(_title(self._t("title")), 1)
        root.addLayout(header)
        root.addWidget(_secondary(self._t("hint")))
        self._build_choose_options(root)

        choose_button = QPushButton(self._t("choose_folder_button"))
        choose_button.setProperty("role", "primary")
        choose_button.clicked.connect(self._on_choose_folder_clicked)
        root.addWidget(choose_button, 0, Qt.AlignLeft)

        self._choose_error_label = _secondary()
        self._choose_error_frame = _warning_frame(self._choose_error_label)
        self._choose_error_frame.setVisible(False)
        root.addWidget(self._choose_error_frame)
        root.addStretch()
        return page

    def _build_choose_options(self, root: QVBoxLayout) -> None:
        """Tri : firmware cible (noms des dossiers) et destination."""
        firmware_row = QHBoxLayout()
        firmware_row.addWidget(QLabel(self._t("firmware_label")))
        self._firmware_combo = QComboBox()
        for firmware_id in SORT_FIRMWARE_IDS:
            self._firmware_combo.addItem(firmware_display_name(firmware_id), firmware_id)
        self._firmware_combo.currentIndexChanged.connect(self._update_verification_label)
        firmware_row.addWidget(self._firmware_combo)
        firmware_row.addStretch()
        root.addLayout(firmware_row)
        self._verification_label = _secondary()
        root.addWidget(self._verification_label)
        self._update_verification_label()

        destination_row = QHBoxLayout()
        destination_row.addWidget(QLabel(self._t("destination_label")))
        self._destination_label = QLabel(self._t("destination_same"))
        destination_row.addWidget(self._destination_label, 1)
        destination_button = QPushButton(self._t("destination_choose_button"))
        destination_button.clicked.connect(self._on_choose_destination_clicked)
        destination_row.addWidget(destination_button)
        self._destination_reset_button = QPushButton(self._t("destination_reset_button"))
        self._destination_reset_button.setProperty("role", "flat")
        self._destination_reset_button.clicked.connect(lambda: self.set_destination(None))
        self._destination_reset_button.setVisible(False)
        destination_row.addWidget(self._destination_reset_button)
        root.addLayout(destination_row)

    def set_destination(self, path: Optional[str]) -> None:
        self._destination = path or None
        self._destination_label.setText(path or self._t("destination_same"))
        self._destination_reset_button.setVisible(self._destination is not None)

    def _on_choose_destination_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self._t("destination_choose_button"))
        if path:
            self.set_destination(path)

    def _build_scan_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addStretch()
        title = _title(self._t("scan_title"))
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        self._scan_count_label = _secondary()
        self._scan_count_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._scan_count_label)
        bar = QProgressBar()
        bar.setRange(0, 0)
        root.addWidget(bar)
        cancel_button = QPushButton(self._t("cancel_button"))
        cancel_button.clicked.connect(self._on_scan_cancel_clicked)
        root.addWidget(cancel_button, 0, Qt.AlignCenter)
        root.addStretch()
        return page

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(_title(self._t("preview_title")))
        self._preview_summary_label = _secondary()
        root.addWidget(self._preview_summary_label)
        self._preview_verification_label = QLabel()
        self._preview_risk_frame = _warning_frame(self._preview_verification_label)
        root.addWidget(self._preview_risk_frame)
        self._case_warning_label = QLabel()
        self._case_warning_frame = _warning_frame(self._case_warning_label)
        root.addWidget(self._case_warning_frame)
        self._preview_tree = QTreeWidget()
        self._preview_tree.setHeaderHidden(True)
        root.addWidget(self._preview_tree, 1)

        buttons = QHBoxLayout()
        back_button = QPushButton(self._t("back_button"))
        back_button.clicked.connect(self.show_choose_page)
        buttons.addWidget(back_button)
        self._undo_previous_button = QPushButton(self._t("undo_previous_button"))
        self._undo_previous_button.clicked.connect(self._start_undo)
        buttons.addWidget(self._undo_previous_button)
        buttons.addStretch()
        self._sort_button = QPushButton(self._t("sort_button"))
        self._sort_button.setProperty("role", "primary")
        self._sort_button.clicked.connect(self._show_confirm_page)
        buttons.addWidget(self._sort_button)
        root.addLayout(buttons)
        return page

    def _build_confirm_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addWidget(_title(self._t("confirm_title")))
        self._confirm_message_label = QLabel()
        self._confirm_message_label.setWordWrap(True)
        root.addWidget(self._confirm_message_label)
        root.addStretch()
        buttons = QHBoxLayout()
        back_button = QPushButton(self._t("back_button"))
        back_button.clicked.connect(lambda: self._stack.setCurrentIndex(self.PAGE_PREVIEW))
        buttons.addWidget(back_button)
        buttons.addStretch()
        self._confirm_button = QPushButton(self._t("confirm_button"))
        self._confirm_button.setProperty("role", "primary")
        self._confirm_button.clicked.connect(self._start_apply)
        buttons.addWidget(self._confirm_button)
        root.addLayout(buttons)
        return page

    def _build_move_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.addStretch()
        title = _title(self._t("move_title"))
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)
        self._move_count_label = _secondary()
        self._move_count_label.setAlignment(Qt.AlignCenter)
        root.addWidget(self._move_count_label)
        self._move_bar = QProgressBar()
        root.addWidget(self._move_bar)
        cancel_button = QPushButton(self._t("cancel_button"))
        cancel_button.clicked.connect(self._on_move_cancel_clicked)
        root.addWidget(cancel_button, 0, Qt.AlignCenter)
        root.addStretch()
        return page

    def _build_result_page(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        self._result_title = _title("")
        root.addWidget(self._result_title)
        self._result_label = QLabel()
        self._result_label.setWordWrap(True)
        root.addWidget(self._result_label)
        self._result_list = QListWidget()
        root.addWidget(self._result_list, 1)
        buttons = QHBoxLayout()
        self._undo_button = QPushButton(self._t("undo_button"))
        self._undo_button.clicked.connect(self._start_undo)
        buttons.addWidget(self._undo_button)
        self._reveal_button = QPushButton(reveal_module.reveal_label())
        self._reveal_button.clicked.connect(self._on_reveal_clicked)
        buttons.addWidget(self._reveal_button)
        buttons.addStretch()
        done_button = QPushButton(self._t("done_button"))
        done_button.setProperty("role", "primary")
        done_button.clicked.connect(self._on_done_clicked)
        buttons.addWidget(done_button)
        root.addLayout(buttons)
        return page

    # --- entrée ------------------------------------------------------------

    def set_default_firmware(self, firmware_id: Optional[str]) -> None:
        """Proposition seulement, toujours remplaçable : le firmware choisi
        pour le flash s'il a une table de tri, ROCKNIX (défaut du
        catalogue) sinon."""
        if firmware_id not in SORT_FIRMWARE_IDS:
            firmware_id = DEFAULT_SORT_FIRMWARE
        self._firmware_combo.setCurrentIndex(self._firmware_combo.findData(firmware_id))

    def selected_firmware(self) -> str:
        return self._firmware_combo.currentData()

    def show_choose_page(self) -> None:
        self._choose_error_frame.setVisible(False)
        self._stack.setCurrentIndex(self.PAGE_CHOOSE)

    def current_page(self) -> int:
        return self._stack.currentIndex()

    def _update_verification_label(self) -> None:
        firmware_id = self._firmware_combo.currentData()
        if firmware_id is not None:
            self._verification_label.setText(_verification_text(firmware_id))

    def _on_choose_folder_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self._t("choose_folder_button"))
        if path:
            self.start_scan(path)

    # --- analyse -----------------------------------------------------------

    def start_scan(self, path: str) -> None:
        self._root = path
        self._scan_count_label.setText(self._t("scan_count", count=0))
        self._stack.setCurrentIndex(self.PAGE_SCAN)
        self._plan_runner = SortPlanRunner(self._plan_builder(path), parent=self)
        self._plan_runner.progress.connect(lambda count: self._scan_count_label.setText(self._t("scan_count", count=count)))
        self._plan_runner.finished_plan.connect(self._on_plan_ready)
        self._plan_runner.cancelled.connect(self.show_choose_page)
        self._plan_runner.error.connect(self._on_scan_error)
        self._plan_runner.start()

    def _plan_builder(self, path: str):
        return partial(
            build_plan, path, self.selected_firmware(), DEFAULT_DOUBLONS_IGNORED_FOLDERS, destination=self._destination
        )

    def _on_scan_cancel_clicked(self) -> None:
        if self._plan_runner is not None:
            self._plan_runner.cancel()

    def _on_scan_error(self, code: str, detail: str) -> None:
        self._stack.setCurrentIndex(self.PAGE_CHOOSE)
        self._choose_error_label.setText(self._t(f"error_{code.lower()}"))
        self._choose_error_frame.setVisible(True)

    def _on_plan_ready(self, plan: SortPlan) -> None:
        self._plan = plan
        self.show_preview(plan)

    # --- aperçu ------------------------------------------------------------

    def show_preview(self, plan: SortPlan) -> None:
        self._plan = plan
        self._root = str(plan.root)
        folders = plan.moves_by_folder()
        self._preview_summary_label.setText(self._preview_summary(plan))
        self._show_preview_risk(plan)
        case_lines = [self._t("case_warning", found=found, expected=expected) for found, expected in plan.case_warnings]
        self._case_warning_label.setText("\n\n".join(case_lines))
        self._case_warning_frame.setVisible(bool(case_lines))

        tree = self._preview_tree
        tree.clear()
        for folder, moves in folders.items():
            size = _format_size(sum(move.size_bytes for move in moves))
            group = QTreeWidgetItem([self._t("group_folder", folder=folder, count=len(moves), size=size)])
            for move in moves:
                QTreeWidgetItem(group, [move.members[0].name])
            tree.addTopLevelItem(group)
        self._add_reason_group(tree, "tri_group_filtered", plan.filtered_out)
        if plan.no_region:
            group = QTreeWidgetItem([self._t("group_no_region", count=len(plan.no_region))])
            for move in plan.no_region:
                QTreeWidgetItem(group, [move.members[0].name])
            tree.addTopLevelItem(group)
        self._add_reason_group(tree, "tri_group_unidentified", plan.unidentified)
        self._add_reason_group(tree, "tri_group_left_in_place", plan.left_in_place)
        if plan.kept_folders:
            kept = QTreeWidgetItem([self._t("group_kept_folders", count=len(plan.kept_folders))])
            for relative in sorted(plan.kept_folders):
                QTreeWidgetItem(kept, [relative])
            tree.addTopLevelItem(kept)

        self._sort_button.setEnabled(bool(plan.moves or plan.unidentified or plan.filtered_out))
        self._undo_previous_button.setVisible(has_journal(self._root, self.JOURNAL_NAME))
        self._stack.setCurrentIndex(self.PAGE_PREVIEW)

    def _preview_summary(self, plan: SortPlan) -> str:
        if not plan.moves and not plan.unidentified:
            return self._t("preview_nothing")
        lines = [
            self._t(
                "preview_summary",
                sorted=len(plan.moves),
                folders=len(plan.moves_by_folder()),
                unidentified=sum(len(move.members) for move in plan.unidentified),
            )
        ]
        if plan.destination is not None and plan.destination != plan.root:
            lines.append(self._t("preview_destination", path=str(plan.destination)))
        return "\n".join(lines)

    def _show_preview_risk(self, plan: SortPlan) -> None:
        self._preview_verification_label.setText(
            f"{firmware_display_name(plan.firmware_id)} : {_verification_text(plan.firmware_id)}\n{self._t('preview_risk')}"
        )

    def _add_reason_group(self, tree: QTreeWidget, title_key: str, moves: List[PlannedMove]) -> None:
        if not moves:
            return
        group = QTreeWidgetItem([tr(title_key, count=len(moves))])
        for move in moves:
            name = " + ".join(member.name for member in move.members)
            QTreeWidgetItem(group, [self._t("item_with_reason", name=name, reason=reason_text(move))])
        tree.addTopLevelItem(group)

    # --- confirmation et déplacement ----------------------------------------

    def _show_confirm_page(self) -> None:
        if self._plan is None:
            return
        self._confirm_message_label.setText(self._confirm_message(self._plan))
        self._stack.setCurrentIndex(self.PAGE_CONFIRM)

    def _confirm_message(self, plan: SortPlan) -> str:
        if plan.destination is not None and plan.destination != plan.root:
            message = self._t(
                "confirm_message_destination",
                count=plan.file_count(),
                destination=str(plan.destination),
                root=str(plan.root),
            )
        else:
            message = self._t("confirm_message", count=plan.file_count(), root=str(plan.root))
        return message

    def _start_apply(self) -> None:
        if self._plan is None:
            return
        self._move_bar.setRange(0, max(1, self._plan.file_count()))
        self._move_bar.setValue(0)
        self._move_count_label.setText(self._t("move_count", done=0, total=self._plan.file_count()))
        self._stack.setCurrentIndex(self.PAGE_MOVE)
        self._apply_runner = SortApplyRunner(self._plan, parent=self, journal_name=self.JOURNAL_NAME)
        self._apply_runner.progress.connect(self._on_move_progress)
        self._apply_runner.finished_apply.connect(self.show_apply_result)
        self._apply_runner.error.connect(self._on_apply_error)
        self._apply_runner.start()

    def _on_move_progress(self, done: int, total: int) -> None:
        self._move_bar.setRange(0, max(1, total))
        self._move_bar.setValue(done)
        self._move_count_label.setText(self._t("move_count", done=done, total=total))

    def _on_move_cancel_clicked(self) -> None:
        if self._apply_runner is not None:
            self._apply_runner.cancel()

    def _on_apply_error(self, code: str, detail: str) -> None:
        self._show_result(self._t("result_cancelled_title"), [self._t(f"error_{code.lower()}")], [detail])

    def show_apply_result(self, result: ApplyResult) -> None:
        interrupted = result.cancelled or result.aborted
        lines = [self._t("result_moved", count=result.moved_files)]
        details: List[str] = []
        if result.aborted:
            lines.append(self._t("result_aborted"))
        if result.failures:
            lines.append(self._t("result_failures", count=len(result.failures)))
            details.extend(str(path) for path, _reason in result.failures)
        if result.skipped_existing:
            lines.append(self._t("result_skipped_existing", count=len(result.skipped_existing)))
            details.extend(str(member) for move in result.skipped_existing for member in move.members)
        if result.missing_sources:
            lines.append(self._t("result_missing", count=len(result.missing_sources)))
        title = self._t("result_cancelled_title" if interrupted else "result_title")
        self._show_result(title, lines, details)

    # --- annulation ----------------------------------------------------------

    def _start_undo(self) -> None:
        if self._root is None:
            return
        self._undo_button.setEnabled(False)
        self._undo_previous_button.setEnabled(False)
        self._undo_runner = SortUndoRunner(self._root, parent=self, journal_name=self.JOURNAL_NAME)
        self._undo_runner.finished_undo.connect(self.show_undo_result)
        self._undo_runner.error.connect(self._on_apply_error)
        self._undo_runner.start()

    def show_undo_result(self, result) -> None:
        lines = [self._t("undo_done", count=result.restored)]
        details = []
        if result.conflicts:
            lines.append(self._t("undo_conflicts", count=len(result.conflicts)))
            details = [conflict.source for conflict in result.conflicts]
        self._undo_previous_button.setEnabled(True)
        self._show_result(self._t("result_title"), lines, details, allow_undo=False)

    # --- résultat ------------------------------------------------------------

    def _show_result(self, title: str, lines: List[str], details: List[str], allow_undo: bool = True) -> None:
        self._result_title.setText(title)
        self._result_label.setText("\n".join(lines))
        self._result_list.clear()
        self._result_list.addItems(details)
        self._result_list.setVisible(bool(details))
        self._undo_button.setEnabled(True)
        self._undo_button.setVisible(allow_undo and self._root is not None and has_journal(self._root, self.JOURNAL_NAME))
        self._stack.setCurrentIndex(self.PAGE_RESULT)

    def _on_reveal_clicked(self) -> None:
        if self._root is not None:
            reveal_module.reveal(self._root)

    def _on_done_clicked(self) -> None:
        self._plan = None
        self.show_choose_page()
        self.back_requested.emit()

    def root_path(self) -> Optional[Path]:
        return Path(self._root) if self._root is not None else None


class FilterScreen(TriScreen):
    """« Filtrer par région et par langue » (`tri/filter.py`) : n'importe
    quel dossier, rien n'est réorganisé, aucun firmware -- seuls les jeux
    hors critères partent dans `_hors_filtre`. Mêmes pages que le tri
    (aperçu, confirmation, déplacement, annulation), journal distinct."""

    TEXT_PREFIX = "filter_"
    JOURNAL_NAME = FILTER_JOURNAL_FILENAME

    def _build_choose_options(self, root: QVBoxLayout) -> None:
        self._region_checks = self._add_check_row(root, "filter_regions_label", "filter_region_", REGION_CHOICES)
        self._language_checks = self._add_check_row(root, "filter_languages_label", "filter_language_", LANGUAGE_CHOICES)

    @staticmethod
    def _add_check_row(layout: QVBoxLayout, label_key: str, text_prefix: str, choices) -> dict:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr(label_key)))
        checks = {}
        for choice in choices:
            check = QCheckBox(tr(text_prefix + choice.lower()))
            row.addWidget(check)
            checks[choice] = check
        row.addStretch()
        layout.addLayout(row)
        return checks

    def region_filter(self) -> RegionFilter:
        return RegionFilter(
            regions=frozenset(choice for choice, check in self._region_checks.items() if check.isChecked()),
            languages=frozenset(choice for choice, check in self._language_checks.items() if check.isChecked()),
        )

    def _on_choose_folder_clicked(self) -> None:
        # Sans critère, rien ne serait écarté : inutile de parcourir le dossier.
        if not self.region_filter().is_active():
            self._choose_error_label.setText(self._t("criteria_needed"))
            self._choose_error_frame.setVisible(True)
            return
        super()._on_choose_folder_clicked()

    def _plan_builder(self, path: str):
        return partial(build_filter_plan, path, self.region_filter(), DEFAULT_DOUBLONS_IGNORED_FOLDERS)

    @staticmethod
    def _game_count(plan: SortPlan) -> int:
        return plan.kept_count + len(plan.filtered_out)

    def _preview_summary(self, plan: SortPlan) -> str:
        if self._game_count(plan) == 0:
            summary = self._t("preview_no_games", files=plan.files_seen)
        elif not plan.filtered_out:
            summary = self._t("preview_nothing", kept=plan.kept_count, no_region=len(plan.no_region))
        else:
            summary = self._t(
                "preview_summary", filtered=len(plan.filtered_out), kept=plan.kept_count, no_region=len(plan.no_region)
            )
        if plan.card_volume is None:
            return summary
        # Racine d'une carte : dire sur quoi on agit, taille comprise --
        # « EASYROMS (E:), 71.5 Go — 1 437 jeu(x) » ; une carte expose souvent
        # plusieurs volumes et le nom seul ne dit pas toujours lequel.
        count = f"{self._game_count(plan):,}".replace(",", "\u202f")
        if plan.card_volume_bytes is None:
            line = self._t("preview_card", card=plan.card_volume, count=count)
        else:
            line = self._t(
                "preview_card_size", card=plan.card_volume, size=_format_size(plan.card_volume_bytes), count=count
            )
        return line + "\n" + summary

    def _show_preview_risk(self, plan: SortPlan) -> None:
        """Aucun jeu reconnu : prévenir plutôt qu'un aperçu vide sans
        explication (mauvais dossier, ou volume système d'une carte)."""
        no_games = self._game_count(plan) == 0
        if no_games:
            self._preview_verification_label.setText(self._t("no_games_warning"))
        self._preview_risk_frame.setVisible(no_games)

    def _confirm_message(self, plan: SortPlan) -> str:
        return self._t("confirm_message", count=plan.file_count(), root=str(plan.root))
