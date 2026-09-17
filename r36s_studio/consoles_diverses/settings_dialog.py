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

"""Fenêtre de réglages de la section « Consoles diverses » -- adresse du
serveur et clé de licence (champ masqué). Suit le même contrat que les
autres fenêtres modales du projet (`gui/screens.py::Dialog`) : elle
n'émet qu'un signal sur l'action de l'utilisateur, jamais elle-même
responsable d'enregistrer quoi que ce soit -- c'est `MainWindow` qui
décide (persistance dans `AppConfig`, trousseau via `settings_store`)."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from r36s_studio.gui.screens import Dialog

from . import settings_store
from .strings import tr


class ConsolesDiversesSettingsDialog(Dialog):
    """`set_values` doit être appelé avant chaque ouverture (`MainWindow`,
    depuis `AppConfig`/`settings_store.lire_licence()`) pour préremplir les
    champs avec l'état actuel -- jamais de valeur imposée."""

    settings_saved = Signal(str, str)  # server_url, licence_key

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))

        layout = QVBoxLayout(self)

        title = QLabel(tr("settings_title"))
        title.setTextFormat(Qt.PlainText)
        title.setProperty("role", "title")
        layout.addWidget(title)

        layout.addWidget(QLabel(tr("settings_server_url_label")))
        self._server_url_edit = QLineEdit()
        layout.addWidget(self._server_url_edit)

        layout.addWidget(QLabel(tr("settings_licence_label")))
        self._licence_edit = QLineEdit()
        self._licence_edit.setEchoMode(QLineEdit.Password)
        layout.addWidget(self._licence_edit)

        self._keyring_warning_label = QLabel(tr("settings_no_keyring_warning"))
        self._keyring_warning_label.setTextFormat(Qt.PlainText)
        self._keyring_warning_label.setWordWrap(True)
        self._keyring_warning_label.setProperty("role", "secondary")
        self._keyring_warning_label.setVisible(False)
        layout.addWidget(self._keyring_warning_label)

        self._error_label = QLabel("")
        self._error_label.setTextFormat(Qt.PlainText)
        self._error_label.setWordWrap(True)
        self._error_label.setProperty("role", "dangerMessage")
        layout.addWidget(self._error_label)

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

        self.resize(420, 260)

    def set_values(self, server_url: str, licence_key: str) -> None:
        self._server_url_edit.setText(server_url)
        self._licence_edit.setText(licence_key or "")
        self._error_label.setText("")
        self._keyring_warning_label.setVisible(not settings_store.trousseau_disponible())

    def _on_save(self) -> None:
        server_url = self._server_url_edit.text().strip()
        erreur = settings_store.valider_adresse_serveur(server_url)
        if erreur:
            self._error_label.setText(erreur)
            return
        licence_key = self._licence_edit.text()
        self.close()
        self.settings_saved.emit(server_url, licence_key)


__all__ = ["ConsolesDiversesSettingsDialog"]
