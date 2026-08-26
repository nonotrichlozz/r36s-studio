"""Les six écrans de l'assistant linéaire (§5). Chaque écran est un
`QWidget` autonome qui communique avec `main_window.py` uniquement par
signaux — aucun ne connaît les autres, ni l'orchestration du worker.

Vocabulaire : aucun terme technique dans les libellés visibles (§5) — le
chemin technique du périphérique n'apparaît que dans un panneau Détails
replié."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.devices import Device

from .strings import tr


class HomeScreen(QWidget):
    """Accueil (§5 point 1). Seules `backup` et `flash` sont branchées en
    phase 4 — `inject_boot` et `copy_games` (phase 5) et le mode assisté
    (phase 6) restent grisés plutôt que simulés."""

    backup_selected = Signal()
    flash_selected = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        title = QLabel(tr("home_title"))
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        layout.addWidget(self._make_tile(tr("home_tile_backup"), tr("home_tile_backup_desc"), self.backup_selected))
        layout.addWidget(self._make_tile(tr("home_tile_flash"), tr("home_tile_flash_desc"), self.flash_selected))
        layout.addWidget(self._make_disabled_tile(tr("home_tile_inject_boot")))
        layout.addWidget(self._make_disabled_tile(tr("home_tile_copy_games")))
        layout.addStretch()

    def _make_tile(self, title: str, description: str, signal: Signal) -> QPushButton:
        button = QPushButton(f"{title}\n{description}")
        button.setMinimumHeight(64)
        button.clicked.connect(signal.emit)
        return button

    def _make_disabled_tile(self, title: str) -> QPushButton:
        button = QPushButton(f"{title}\n({tr('home_coming_soon')})")
        button.setMinimumHeight(64)
        button.setEnabled(False)
        return button


class DeviceScreen(QWidget):
    """Choix du périphérique (§5 point 2) : liste filtrée par `safety`
    (modèle, taille, bus), bouton Rafraîchir, aucune sélection par
    défaut."""

    device_chosen = Signal(object)  # Device
    back_requested = Signal()
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: List[Device] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("device_title")))

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.itemSelectionChanged.connect(self._update_next_enabled)
        layout.addWidget(self._list)

        self._empty_label = QLabel(tr("device_empty"))
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        buttons = QHBoxLayout()
        back_button = QPushButton(tr("device_back"))
        back_button.clicked.connect(self.back_requested.emit)
        refresh_button = QPushButton(tr("device_refresh"))
        refresh_button.clicked.connect(self.refresh_requested.emit)
        self._next_button = QPushButton(tr("device_next"))
        self._next_button.setEnabled(False)
        self._next_button.clicked.connect(self._emit_chosen)
        buttons.addWidget(back_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch()
        buttons.addWidget(self._next_button)
        layout.addLayout(buttons)

        self.set_devices([])

    def set_devices(self, devices: List[Device]) -> None:
        self._devices = devices
        self._list.clear()
        for device in devices:
            size_go = device.size_bytes / 1_000_000_000
            item = QListWidgetItem(f"{device.display} — {size_go:.1f} Go — {device.bus}")
            item.setData(Qt.UserRole, device)
            self._list.addItem(item)
        self._empty_label.setVisible(not devices)
        self._list.setVisible(bool(devices))
        self._update_next_enabled()

    def _update_next_enabled(self) -> None:
        self._next_button.setEnabled(bool(self._list.selectedItems()))

    def _emit_chosen(self) -> None:
        items = self._list.selectedItems()
        if items:
            self.device_chosen.emit(items[0].data(Qt.UserRole))


class FileScreen(QWidget):
    """Choix du fichier (§5 point 3) : fichier de sortie pour la
    sauvegarde, image source pour le flash."""

    file_chosen = Signal(str)
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "backup"

        layout = QVBoxLayout(self)
        self._title = QLabel()
        layout.addWidget(self._title)

        self._path_label = QLabel()
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)

        browse_button = QPushButton(tr("file_browse"))
        browse_button.clicked.connect(self._browse)
        layout.addWidget(browse_button)
        layout.addStretch()

        buttons = QHBoxLayout()
        back_button = QPushButton(tr("file_back"))
        back_button.clicked.connect(self.back_requested.emit)
        self._next_button = QPushButton(tr("file_next"))
        self._next_button.setEnabled(False)
        self._next_button.clicked.connect(lambda: self.file_chosen.emit(self._path_label.text()))
        buttons.addWidget(back_button)
        buttons.addStretch()
        buttons.addWidget(self._next_button)
        layout.addLayout(buttons)

    def set_mode(self, mode: str) -> None:
        """`mode` : "backup" (choisir où enregistrer) ou "flash" (choisir
        l'image source)."""
        self._mode = mode
        self._title.setText(tr("file_title_backup" if mode == "backup" else "file_title_flash"))
        self._path_label.setText("")
        self._next_button.setEnabled(False)

    def _browse(self) -> None:
        if self._mode == "backup":
            path, _ = QFileDialog.getSaveFileName(self, tr("file_title_backup"), "", "Image (*.img)")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self,
                tr("file_title_flash"),
                "",
                "Image disque (*.img *.img.gz *.img.xz)",
            )
        if path:
            self._path_label.setText(path)
            self._next_button.setEnabled(True)


class ConfirmScreen(QWidget):
    """Confirmation (§5 point 4) : écran rouge, récapitulatif explicite,
    case à cocher obligatoire — dernier rempart avant écriture (règle §2
    n°6). Uniquement pour le flash : la sauvegarde n'écrit jamais sur un
    périphérique."""

    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #4a1414; color: white;")

        layout = QVBoxLayout(self)
        title = QLabel(tr("confirm_title"))
        title.setStyleSheet("font-size: 22px; font-weight: bold;")
        layout.addWidget(title)

        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setStyleSheet("font-size: 16px;")
        layout.addWidget(self._message)

        self._checkbox = QCheckBox(tr("confirm_checkbox"))
        self._checkbox.stateChanged.connect(self._update_go_enabled)
        layout.addWidget(self._checkbox)
        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("confirm_cancel"))
        cancel_button.clicked.connect(self._cancel)
        self._go_button = QPushButton(tr("confirm_go"))
        self._go_button.setEnabled(False)
        self._go_button.clicked.connect(self.confirmed.emit)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(self._go_button)
        layout.addLayout(buttons)

    def set_device(self, device: Device) -> None:
        size_go = device.size_bytes / 1_000_000_000
        self._message.setText(tr("confirm_erase", display=device.display, size_go=size_go))
        self._checkbox.setChecked(False)

    def _update_go_enabled(self) -> None:
        self._go_button.setEnabled(self._checkbox.isChecked())

    def _cancel(self) -> None:
        self._checkbox.setChecked(False)
        self.cancelled.emit()


class ExecuteScreen(QWidget):
    """Exécution (§5 point 5) : progression réelle, débit, temps restant
    estimé, bouton Annuler actif."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._title = QLabel()
        self._title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(self._title)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        layout.addWidget(self._bar)

        self._speed_label = QLabel()
        layout.addWidget(self._speed_label)
        self._eta_label = QLabel(tr("execute_eta_unknown"))
        layout.addWidget(self._eta_label)

        self._log_label = QLabel()
        self._log_label.setWordWrap(True)
        layout.addWidget(self._log_label)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        self._cancel_button = QPushButton(tr("execute_cancel"))
        self._cancel_button.clicked.connect(self.cancel_requested.emit)
        buttons.addWidget(self._cancel_button)
        layout.addLayout(buttons)

    def reset(self, mode: str) -> None:
        self._title.setText(tr("execute_title_backup" if mode == "backup" else "execute_title_flash"))
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._speed_label.setText("")
        self._eta_label.setText(tr("execute_eta_unknown"))
        self._log_label.setText("")
        self._cancel_button.setEnabled(True)

    def update_progress(self, done: int, total: int, speed: float) -> None:
        if total > 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(int(done * 100 / total))
        else:
            # Taille inconnue (image .img.xz, §4.3) : pas de fausse
            # progression (règle §2 n°5) -- barre indéterminée.
            self._bar.setRange(0, 0)

        self._speed_label.setText(tr("execute_speed", speed=speed / 1_000_000))

        if total > 0 and speed > 0:
            remaining_seconds = max(0, (total - done)) / speed
            self._eta_label.setText(tr("execute_eta", eta=_format_duration(remaining_seconds)))
        else:
            self._eta_label.setText(tr("execute_eta_unknown"))

    def append_log(self, msg: str) -> None:
        self._log_label.setText(msg)

    def set_cancel_enabled(self, enabled: bool) -> None:
        self._cancel_button.setEnabled(enabled)


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {seconds:02d} s"
    return f"{seconds} s"


class ResultScreen(QWidget):
    """Résultat (§5 point 6) : succès ou erreur lisible, bouton Éjecter."""

    eject_requested = Signal()
    home_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._title = QLabel()
        self._title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(self._title)

        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        layout.addStretch()

        buttons = QHBoxLayout()
        self._eject_button = QPushButton(tr("result_eject"))
        self._eject_button.clicked.connect(self.eject_requested.emit)
        home_button = QPushButton(tr("result_home"))
        home_button.clicked.connect(self.home_requested.emit)
        buttons.addWidget(self._eject_button)
        buttons.addStretch()
        buttons.addWidget(home_button)
        layout.addLayout(buttons)

    def show_success(self, message: str, allow_eject: bool) -> None:
        self._title.setText(tr("result_success"))
        self._message.setText(message)
        self._eject_button.setVisible(allow_eject)

    def show_error(self, message: str, cancelled: bool = False) -> None:
        self._title.setText(tr("result_cancelled") if cancelled else tr("result_error"))
        self._message.setText(message)
        self._eject_button.setVisible(False)
