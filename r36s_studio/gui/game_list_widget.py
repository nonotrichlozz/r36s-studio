# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Liste de jeux composée librement (`tri/selection.py::GameSelection`) :
« Ajouter des jeux… » (plusieurs fichiers), « Ajouter un dossier… »,
glisser-déposer de fichiers et de dossiers, retrait d'une ligne (bouton ou
Suppr), « Tout vider ». Une ligne par jeu (fichiers liés d'un `.cue`
regroupés) : nom, taille, système.

Aucune dépendance à ADB ni à une console : la colonne « Système » est
remplie par la fonction passée à `set_describer` (l'écran qui utilise la
liste sait vers quoi il copie). Réutilisable tel quel par « Copier des jeux
sur la carte »."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.tri.selection import GameSelection

from .screens import _format_size
from .strings import tr

__all__ = ["GameListWidget"]

# Fichier (premier de la ligne) -> texte de la colonne « Système ».
Describer = Callable[[GameSelection], Dict[Path, str]]


class GameListWidget(QWidget):
    changed = Signal()
    # Dossier à proposer la prochaine fois (config.json::last_games_folder).
    folder_used = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selection = GameSelection()
        self._describer: Optional[Describer] = None
        self._start_folder = ""
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels([tr("game_list_col_name"), tr("game_list_col_size"), tr("game_list_col_system")])
        self._tree.setRootIsDecorated(False)
        self._tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self._tree.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self._tree, 1)
        QShortcut(QKeySequence.Delete, self._tree, activated=self.remove_selected)

        buttons = QHBoxLayout()
        add_files = QPushButton(tr("game_list_add_files"))
        add_files.clicked.connect(self._on_add_files_clicked)
        buttons.addWidget(add_files)
        add_folder = QPushButton(tr("game_list_add_folder"))
        add_folder.clicked.connect(self._on_add_folder_clicked)
        buttons.addWidget(add_folder)
        self._remove_button = QPushButton(tr("game_list_remove"))
        self._remove_button.clicked.connect(self.remove_selected)
        buttons.addWidget(self._remove_button)
        self._clear_button = QPushButton(tr("game_list_clear"))
        self._clear_button.setProperty("role", "flat")
        self._clear_button.clicked.connect(self.clear)
        buttons.addWidget(self._clear_button)
        buttons.addStretch()
        self._total_label = QLabel()
        self._total_label.setProperty("role", "secondary")
        buttons.addWidget(self._total_label)
        layout.addLayout(buttons)
        self.refresh()

    # --- API ----------------------------------------------------------------

    def selection(self) -> GameSelection:
        return self._selection

    def set_start_folder(self, folder: str) -> None:
        self._start_folder = folder or ""

    def set_describer(self, describer: Optional[Describer]) -> None:
        self._describer = describer
        self.refresh()

    def add_paths(self, paths: Iterable[str]) -> None:
        """Fichiers et dossiers mélangés (sélecteurs et glisser-déposer)."""
        paths = [str(path) for path in paths]
        if not paths:
            return
        self._selection.add_paths(paths)
        first = Path(paths[0])
        self._remember(str(first.parent))
        self.refresh()

    def remove_selected(self) -> None:
        for item in self._tree.selectedItems():
            self._selection.remove(item.data(0, Qt.UserRole))
        self.refresh()

    def clear(self) -> None:
        self._selection.clear()
        self.refresh()

    def refresh(self) -> None:
        # ponytail: tout est recalculé à chaque changement (identification
        # comprise, sur le thread Qt) ; passer à un thread si une liste de
        # plusieurs milliers de jeux fige l'écran.
        described = self._describer(self._selection) if self._describer and len(self._selection) else {}
        self._tree.clear()
        total = 0
        for group in self._selection.groups():
            size = sum(_size(path) for path in group)
            total += size
            name = group[0].name if len(group) == 1 else tr("game_list_linked", name=group[0].name, count=len(group) - 1)
            item = QTreeWidgetItem([name, _format_size(size), described.get(group[0], "")])
            item.setData(0, Qt.UserRole, group[0])
            item.setToolTip(0, "\n".join(str(path) for path in group))
            self._tree.addTopLevelItem(item)
        if len(self._selection):
            self._total_label.setText(tr("game_list_total", count=self._tree.topLevelItemCount(), size=_format_size(total)))
        else:
            self._total_label.setText(tr("game_list_empty"))
        self._update_buttons()
        self.changed.emit()

    # --- sélecteurs, glisser-déposer ---------------------------------------

    def _remember(self, folder: str) -> None:
        self._start_folder = folder
        self.folder_used.emit(folder)

    def _on_add_files_clicked(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, tr("game_list_add_files"), self._start_folder)
        self.add_paths(paths)

    def _on_add_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("game_list_add_folder"), self._start_folder)
        if folder:
            self.add_paths([folder])

    def dragEnterEvent(self, event) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        self.add_paths(url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile())
        event.acceptProposedAction()

    def _update_buttons(self) -> None:
        self._remove_button.setEnabled(bool(self._tree.selectedItems()))
        self._clear_button.setEnabled(bool(len(self._selection)))


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
