# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Fenêtre de réglages de la section « Consoles diverses » -- la clé de
licence seule (champ masqué). L'adresse du serveur n'y figure plus :
elle est en dur (`settings_store.adresse_serveur`), un client ne saurait
pas quoi y mettre. Suit le même contrat que les autres fenêtres modales
du projet (`gui/screens.py::Dialog`) : elle n'émet qu'un signal sur
l'action de l'utilisateur, jamais elle-même responsable d'enregistrer
quoi que ce soit -- c'est `MainWindow` qui décide (`config.json`)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from r36s_studio.gui.screens import Dialog

from .strings import tr


class ConsolesDiversesSettingsDialog(Dialog):
    """`set_values` doit être appelé avant chaque ouverture (`MainWindow`,
    depuis `AppConfig.consoles_diverses_licence_key`) pour préremplir le champ avec
    l'état actuel -- jamais de valeur imposée."""

    settings_saved = Signal(str)  # licence_key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))

        layout = QVBoxLayout(self)

        title = QLabel(tr("settings_title"))
        title.setTextFormat(Qt.PlainText)
        title.setProperty("role", "title")
        layout.addWidget(title)

        layout.addWidget(QLabel(tr("settings_licence_label")))
        self._licence_edit = QLineEdit()
        self._licence_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._licence_edit)

        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("settings_cancel_button"))
        cancel_button.clicked.connect(self.close)
        self._save_button = QPushButton(tr("settings_save_button"))
        self._save_button.setProperty("role", "primary")
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self._on_save)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(self._save_button)
        layout.addLayout(buttons)

        self.resize(420, 200)

    def set_values(self, licence_key: str) -> None:
        self._licence_edit.setText(licence_key or "")

    def _on_save(self) -> None:
        licence_key = self._licence_edit.text()
        self.close()
        self.settings_saved.emit(licence_key)


__all__ = ["ConsolesDiversesSettingsDialog"]
