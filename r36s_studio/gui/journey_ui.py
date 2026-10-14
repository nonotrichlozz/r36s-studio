# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Parcours « Ma console ne démarre plus » / « Je veux préparer une carte
neuve » (docs/claude/assisted-wizard.md) : quelle console, quel système,
puis le fichier téléchargé. La suite (choix de la carte, confirmation,
flash, éjection) est le flash assisté existant ; l'écran figé ouvre
`boot_sets_ui.BootSetsDialog`. Cette fenêtre n'écrit rien : elle émet des
signaux, `main_window` agit."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.identify import IdentifyResult
from r36s_studio.identify import console_profile

from .screens import Dialog
from .strings import tr

IMAGE_FILTER = "*.img *.img.gz *.img.xz"


class ConsoleJourneyDialog(Dialog):
    identify_requested = Signal()
    screens_requested = Signal()
    open_url_requested = Signal(str)
    image_chosen = Signal(str, str, str)  # chemin, profil, référence tapée

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("journey_title"))
        self._profile = console_profile.UNKNOWN
        self._reference = ""

        layout = QVBoxLayout(self)
        self._title = QLabel()
        self._title.setProperty("role", "title")
        layout.addWidget(self._title)
        self._text = QLabel()
        self._text.setWordWrap(True)
        layout.addWidget(self._text)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setProperty("role", "secondary")
        layout.addWidget(self._status)

        self._pages = QStackedWidget()
        layout.addWidget(self._pages)
        self._start_page = self._buttons_page(
            (tr("journey_start_reinstall"), self._show_console_page),
            (tr("journey_start_frozen"), self.screens_requested.emit),
        )
        self._console_page = self._build_console_page()
        self._system_page = self._buttons_page(
            (tr("journey_system_open_page"), lambda: self.open_url_requested.emit(self.recommended_url())),
            (tr("journey_system_open_clone_page"), self._open_clone_page),
            (tr("journey_system_choose_file"), self._choose_file),
        )
        self.clone_page_button = self._system_page.buttons[1]
        for page in (self._start_page, self._console_page, self._system_page):
            self._pages.addWidget(page)

        close_row = QHBoxLayout()
        close_row.addStretch()
        self.close_button = QPushButton(tr("journey_close"))
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.close)
        close_row.addWidget(self.close_button)
        layout.addLayout(close_row)

    def _buttons_page(self, *buttons) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        page.buttons = []
        for label, slot in buttons:
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(slot)
            box.addWidget(button)
            page.buttons.append(button)
        return page

    def _build_console_page(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.read_card_button = QPushButton(tr("journey_console_read_card"))
        self.read_card_button.setAutoDefault(False)
        self.read_card_button.clicked.connect(self._on_read_card)
        box.addWidget(self.read_card_button)
        box.addWidget(QLabel(tr("journey_console_reference_label")))
        self.reference_edit = QLineEdit()
        self.reference_edit.setPlaceholderText(tr("journey_console_reference_example"))
        self.reference_edit.textChanged.connect(lambda text: self.reference_button.setEnabled(bool(text.strip())))
        box.addWidget(self.reference_edit)
        row = QHBoxLayout()
        self.reference_button = QPushButton(tr("journey_console_reference_continue"))
        self.reference_button.setEnabled(False)
        self.reference_button.clicked.connect(self._on_reference)
        self.unknown_button = QPushButton(tr("journey_console_unknown"))
        self.unknown_button.clicked.connect(lambda: self._show_system_page(console_profile.UNKNOWN))
        for button in (self.reference_button, self.unknown_button):
            button.setAutoDefault(False)
            row.addWidget(button)
        box.addLayout(row)
        return page

    # --- appelé par main_window ---------------------------------------------

    def start(self, not_booting: bool) -> None:
        self._profile, self._reference = console_profile.UNKNOWN, ""
        self.reference_edit.clear()
        self.read_card_button.setEnabled(True)
        if not_booting:
            self._title.setText(tr("journey_start_title"))
            self._text.setText(tr("journey_start_text"))
            self._status.setText("")
            self._pages.setCurrentWidget(self._start_page)
        else:
            self._show_console_page()

    def set_identify_result(self, result: IdentifyResult) -> None:
        self.read_card_button.setEnabled(True)
        profile = console_profile.profile_from_identify(result)
        if profile is None:
            self._status.setText(tr("journey_console_unreadable"))
            return
        self._show_system_page(profile)

    def recommended_url(self) -> str:
        return console_profile.recommended_releases_url(self._profile)

    # --- interne -------------------------------------------------------------

    def _show_console_page(self) -> None:
        self._title.setText(tr("journey_console_title"))
        self._text.setText(tr("journey_console_text"))
        self._status.setText("")
        self._pages.setCurrentWidget(self._console_page)

    def _on_read_card(self) -> None:
        self.read_card_button.setEnabled(False)
        self._status.setText(tr("journey_console_reading"))
        self.identify_requested.emit()

    def _on_reference(self) -> None:
        self._reference = self.reference_edit.text().strip()
        self._show_system_page(console_profile.profile_from_reference(self._reference))

    def _open_clone_page(self) -> None:
        url = console_profile.clone_fallback_url(self._profile)
        if url:
            self.open_url_requested.emit(url)

    def _show_system_page(self, profile: str) -> None:
        self._profile = profile
        self.clone_page_button.setVisible(console_profile.clone_fallback_url(profile) is not None)
        self._title.setText(tr("journey_system_title"))
        self._text.setText(tr(f"journey_system_{profile}"))
        self._status.setText("")
        self._pages.setCurrentWidget(self._system_page)

    def _choose_file(self) -> None:
        path = self._ask_file()
        if path:
            self.image_chosen.emit(path, self._profile, self._reference)

    def _ask_file(self) -> Optional[str]:
        path, _ = QFileDialog.getOpenFileName(self, tr("journey_system_choose_file"), "", f"{tr('journey_file_filter')} ({IMAGE_FILTER})")
        return path or None
