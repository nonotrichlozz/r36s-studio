"""Les six écrans de l'assistant linéaire (§5). Chaque écran est un
`QWidget` autonome qui communique avec `main_window.py` uniquement par
signaux — aucun ne connaît les autres, ni l'orchestration du worker.

Vocabulaire : aucun terme technique dans les libellés visibles (§5) — le
chemin technique du périphérique n'apparaît que dans un panneau Détails
replié."""

from __future__ import annotations

import platform
from typing import Dict, List, Optional

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

from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.partitions.archives import parse_archive_timestamp

from . import build_info
from .reveal import reveal_label
from .strings import tr

_STATUS_TEXT_KEYS = {
    StepStatus.AVAILABLE: "status_available",
    StepStatus.DONE: "status_done",
    StepStatus.NOT_RELEVANT: "status_not_relevant",
}

# Les six étapes chronologiques fixes du workflow à deux cartes (§4.4/§4.5),
# dans l'ordre A à F. Clés identiques aux noms de job déjà utilisés par
# `partition_runner.py`/`__main__.py`.
_STEP_SPECS = [
    ("extract_boot", "home_step_a_title", "home_step_a_desc"),
    ("extract_easyroms", "home_step_b_title", "home_step_b_desc"),
    ("flash", "home_step_c_title", "home_step_c_desc"),
    ("inject_boot", "home_step_d_title", "home_step_d_desc"),
    ("copy_games", "home_step_e_title", "home_step_e_desc"),
    ("eject", "home_step_f_title", "home_step_f_desc"),
]


class HomeScreen(QWidget):
    """Accueil (§5 point 1). Les six étapes du workflow à deux cartes
    (§4.4/§4.5) restent **toujours toutes visibles et cliquables**, dans un
    ordre fixe : `detect.StepStatus` n'indique qu'un statut informatif par
    étape (faisable / déjà faite / non pertinente pour la carte branchée),
    jamais un verrou -- un utilisateur averti garde toujours la main. La
    sauvegarde complète de l'image disque est une opération de sécurité,
    volontairement en dehors de cette liste."""

    extract_boot_selected = Signal()
    extract_easyroms_selected = Signal()
    flash_selected = Signal()
    inject_boot_selected = Signal()
    copy_games_selected = Signal()
    eject_selected = Signal()
    backup_selected = Signal()
    refresh_requested = Signal()
    help_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        title = QLabel(tr("home_title"))
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        self._refresh_button = QPushButton(tr("home_refresh"))
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self._refresh_button)

        # Autorisation Accès complet au disque (§3) : seul macOS en a
        # besoin -- ne pas afficher ce bouton ailleurs éviterait de dérouter
        # les utilisateurs Windows/Linux avec une procédure qui ne les
        # concerne pas.
        if platform.system() == "Darwin":
            self._help_button = QPushButton(tr("home_help"))
            self._help_button.clicked.connect(self.help_requested.emit)
            layout.addWidget(self._help_button)

        step_signals = {
            "extract_boot": self.extract_boot_selected,
            "extract_easyroms": self.extract_easyroms_selected,
            "flash": self.flash_selected,
            "inject_boot": self.inject_boot_selected,
            "copy_games": self.copy_games_selected,
            "eject": self.eject_selected,
        }
        self._base_texts: Dict[str, str] = {}
        self._tiles: Dict[str, QPushButton] = {}
        for key, title_key, desc_key in _STEP_SPECS:
            base_text = f"{tr(title_key)}\n{tr(desc_key)}"
            tile = self._make_tile(base_text, step_signals[key])
            self._base_texts[key] = base_text
            self._tiles[key] = tile
            layout.addWidget(tile)

        separator = QLabel(tr("home_backup_separator"))
        separator.setStyleSheet("color: gray; margin-top: 8px;")
        layout.addWidget(separator)
        backup_tile = self._make_tile(
            f"{tr('home_tile_backup')}\n{tr('home_tile_backup_desc')}", self.backup_selected
        )
        layout.addWidget(backup_tile)

        layout.addStretch()

        # Numéro de version + horodatage de construction (§5, à la demande
        # explicite d'un utilisateur ayant perdu le fil entre plusieurs
        # reconstructions locales) : sans repère visible, impossible de
        # savoir si l'app en cours d'exécution contient les derniers
        # correctifs -- vrai en développement, vrai aussi pour un
        # utilisateur qui signale un bug plus tard.
        self._version_label = QLabel(build_info.version_label())
        self._version_label.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self._version_label)

        self.set_status({})

    def _make_tile(self, text: str, signal: Signal) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(56)
        button.clicked.connect(signal.emit)
        return button

    def set_status(self, status: Dict[str, StepStatus]) -> None:
        """`status` (voir `detect.detect_workflow_status`) annote chaque
        tuile d'un statut informatif — jamais de tuile masquée ni
        désactivée : une étape absente du dict (détection pas encore
        lancée) garde son texte de base, sans badge."""
        for key, tile in self._tiles.items():
            base = self._base_texts[key]
            step_status = status.get(key)
            if step_status is None:
                tile.setText(base)
            else:
                tile.setText(f"{base}\n{tr(_STATUS_TEXT_KEYS[step_status])}")


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


_FILE_TITLE_KEYS = {
    "backup": "file_title_backup",
    "flash": "file_title_flash",
    "extract_boot": "file_title_extract_boot",
    "extract_easyroms": "file_title_extract_easyroms",
    "inject_boot": "file_title_inject_boot",
    "copy_games": "file_title_copy_games",
}


_ARCHIVE_MODES = {"inject_boot", "copy_games"}  # étapes D/E : choix parmi les archives existantes
_DESTINATION_MODES = {"extract_boot", "extract_easyroms"}  # étapes A/B : dossier de destination, avec défaut

_FRENCH_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]  # fmt: skip


def format_archive_label(path) -> str:
    """Nom convivial (§5, pas de jargon) d'un dossier d'archive horodaté —
    ex. « 6 juillet 2026 à 00h21 » plutôt que le nom de dossier brut. Repli
    sur le nom du dossier si ce n'est pas une archive nommée par
    `archives.new_archive_path` (dossier choisi manuellement via
    Parcourir)."""
    from pathlib import Path as _Path

    path = _Path(path)
    timestamp = parse_archive_timestamp(path)
    if timestamp is None:
        return path.name
    month = _FRENCH_MONTHS[timestamp.month - 1]
    return f"{timestamp.day} {month} {timestamp.year} à {timestamp.hour:02d}h{timestamp.minute:02d}"


class FileScreen(QWidget):
    """Choix du fichier (§5 point 3) : fichier de sortie pour la
    sauvegarde, image source pour le flash, un dossier de destination pour
    l'extraction du BOOT/EASYROMS (§4.4, étapes A/B — un emplacement par
    défaut est proposé, jamais imposé), ou — pour l'injection sur la carte
    neuve (étapes D/E) — une sauvegarde parmi celles déjà extraites, avec
    un repli « Parcourir… » pour une source manuelle."""

    file_chosen = Signal(str)
    back_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "backup"

        layout = QVBoxLayout(self)
        self._title = QLabel()
        layout.addWidget(self._title)

        self._archive_list = QListWidget()
        self._archive_list.setSelectionMode(QListWidget.SingleSelection)
        self._archive_list.itemSelectionChanged.connect(self._on_archive_selected)
        layout.addWidget(self._archive_list)

        self._archive_empty_label = QLabel(tr("file_archive_empty"))
        self._archive_empty_label.setWordWrap(True)
        layout.addWidget(self._archive_empty_label)

        self._path_label = QLabel()
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)

        self._destination_hint_label = QLabel(tr("file_destination_hint"))
        self._destination_hint_label.setWordWrap(True)
        self._destination_hint_label.setStyleSheet("color: gray;")
        layout.addWidget(self._destination_hint_label)

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

    def set_mode(
        self, mode: str, archive_choices: Optional[List] = None, default_path: Optional[str] = None
    ) -> None:
        """`mode` : "backup" (choisir où enregistrer), "flash" (choisir
        l'image source), "extract_boot"/"extract_easyroms" (choisir un
        dossier de destination — `default_path` le pré-remplit, toujours
        remplaçable via Parcourir), ou "inject_boot"/"copy_games" (choisir
        une sauvegarde parmi `archive_choices`, ou en désigner une autre
        via Parcourir)."""
        self._mode = mode
        self._title.setText(tr(_FILE_TITLE_KEYS[mode]))
        self._path_label.setText(default_path or "")
        self._next_button.setEnabled(bool(default_path))

        is_archive_mode = mode in _ARCHIVE_MODES
        self._archive_list.clear()
        if is_archive_mode:
            for path in archive_choices or []:
                item = QListWidgetItem(format_archive_label(path))
                item.setData(Qt.UserRole, str(path))
                self._archive_list.addItem(item)
        self._archive_list.setVisible(is_archive_mode)
        self._archive_empty_label.setVisible(is_archive_mode and not archive_choices)
        self._destination_hint_label.setVisible(mode in _DESTINATION_MODES)

    def _on_archive_selected(self) -> None:
        items = self._archive_list.selectedItems()
        if items:
            self._path_label.setText(items[0].data(Qt.UserRole))
            self._next_button.setEnabled(True)

    def _browse(self) -> None:
        title = tr(_FILE_TITLE_KEYS[self._mode])
        if self._mode == "backup":
            path, _ = QFileDialog.getSaveFileName(self, title, "", "Image (*.img)")
        elif self._mode == "flash":
            path, _ = QFileDialog.getOpenFileName(self, title, "", "Image disque (*.img *.img.gz *.img.xz)")
        elif self._mode in _DESTINATION_MODES:
            # Démarre sur l'emplacement déjà affiché (le défaut proposé,
            # ou le dernier choisi) plutôt que de repartir de zéro.
            path = QFileDialog.getExistingDirectory(self, title, self._path_label.text())
        else:
            path = QFileDialog.getExistingDirectory(self, title)
        if path:
            self._archive_list.clearSelection()
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


_EXECUTE_TITLE_KEYS = {
    "backup": "execute_title_backup",
    "flash": "execute_title_flash",
    "extract_boot": "execute_title_extract_boot",
    "extract_easyroms": "execute_title_extract_easyroms",
    "inject_boot": "execute_title_inject_boot",
    "copy_games": "execute_title_copy_games",
}


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
        self._title.setText(tr(_EXECUTE_TITLE_KEYS[mode]))
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


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{int(size)} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} To"


class ResultScreen(QWidget):
    """Résultat (§5 point 6) : succès ou erreur lisible, bouton Éjecter.

    Le message principal d'erreur ne contient jamais de jargon technique
    (§5) — c'est à l'appelant (`main_window.py`,
    `strings.friendly_error_message`) de le garantir. Le message brut du
    backend (qui peut contenir un chemin, un nom de système de fichiers...)
    est replié dans un panneau « Détails », masqué par défaut.

    Après une extraction (étapes A/B, §4.4), affiche en plus le chemin
    complet de l'archive créée, sa taille, et un bouton pour la révéler
    dans le gestionnaire de fichiers (`reveal.reveal`). Après une injection
    (étapes D/E), la même zone indique plutôt quelle archive a servi de
    source."""

    eject_requested = Signal()
    home_requested = Signal()
    reveal_requested = Signal(str)  # chemin à révéler

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._title = QLabel()
        self._title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(self._title)

        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

        self._archive_info_label = QLabel()
        self._archive_info_label.setWordWrap(True)
        self._archive_info_label.setVisible(False)
        layout.addWidget(self._archive_info_label)

        self._details_toggle = QPushButton(tr("details_toggle"))
        self._details_toggle.setCheckable(True)
        self._details_toggle.setFlat(True)
        self._details_toggle.setVisible(False)
        self._details_toggle.toggled.connect(self._on_details_toggled)
        layout.addWidget(self._details_toggle)

        self._details_label = QLabel()
        self._details_label.setWordWrap(True)
        self._details_label.setStyleSheet("color: gray; font-family: monospace; font-size: 11px;")
        self._details_label.setVisible(False)
        layout.addWidget(self._details_label)

        layout.addStretch()

        buttons = QHBoxLayout()
        self._eject_button = QPushButton(tr("result_eject"))
        self._eject_button.clicked.connect(self.eject_requested.emit)
        self._reveal_button = QPushButton(reveal_label())
        self._reveal_button.setVisible(False)
        self._reveal_button.clicked.connect(lambda: self.reveal_requested.emit(self._reveal_path))
        home_button = QPushButton(tr("result_home"))
        home_button.clicked.connect(self.home_requested.emit)
        buttons.addWidget(self._eject_button)
        buttons.addWidget(self._reveal_button)
        buttons.addStretch()
        buttons.addWidget(home_button)
        layout.addLayout(buttons)

        self._reveal_path: Optional[str] = None

    def _on_details_toggled(self, checked: bool) -> None:
        self._details_label.setVisible(checked)

    def _set_details(self, details: str) -> None:
        has_details = bool(details)
        self._details_toggle.setChecked(False)
        self._details_toggle.setVisible(has_details)
        self._details_label.setText(details)
        self._details_label.setVisible(False)

    def _set_archive_info(self, archive_info: str, reveal_path: Optional[str]) -> None:
        self._archive_info_label.setText(archive_info)
        self._archive_info_label.setVisible(bool(archive_info))
        self._reveal_path = reveal_path
        self._reveal_button.setVisible(bool(reveal_path))

    def show_success(
        self,
        message: str,
        allow_eject: bool,
        archive_info: str = "",
        reveal_path: Optional[str] = None,
    ) -> None:
        self._title.setText(tr("result_success"))
        self._message.setText(message)
        self._eject_button.setVisible(allow_eject)
        self._set_details("")
        self._set_archive_info(archive_info, reveal_path)

    def show_error(self, message: str, cancelled: bool = False, details: str = "") -> None:
        self._title.setText(tr("result_cancelled") if cancelled else tr("result_error"))
        self._message.setText(message)
        self._eject_button.setVisible(False)
        self._set_details(details if details != message else "")
        self._set_archive_info("", None)


class HelpScreen(QWidget):
    """Aide (macOS uniquement, §3) : explique l'autorisation Accès complet
    au disque, que chaque utilisateur doit accorder une fois pour que
    R36S Studio accède à la carte SD. Accessible depuis l'accueil
    (`HomeScreen.help_requested`) et depuis l'écran Résultat quand
    `MACOS_TCC_BLOCKED` survient (le message d'erreur y renvoie).

    Contrairement au reste de l'interface (§5 : jamais de jargon), le texte
    ici nomme volontairement les vrais réglages système (« Réglages
    Système », « Accès complet au disque ») -- c'est une procédure système
    réelle à suivre, pas la description d'une action de l'app."""

    back_requested = Signal()
    open_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        title = QLabel(tr("help_title"))
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        layout.addWidget(title)

        body = QLabel(tr("help_body"))
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch()

        buttons = QHBoxLayout()
        self._back_button = QPushButton(tr("help_back"))
        self._back_button.clicked.connect(self.back_requested.emit)
        self._open_settings_button = QPushButton(tr("help_open_settings"))
        self._open_settings_button.clicked.connect(self.open_settings_requested.emit)
        buttons.addWidget(self._back_button)
        buttons.addStretch()
        buttons.addWidget(self._open_settings_button)
        layout.addLayout(buttons)
