"""Fenêtre principale (§5, refonte navigation) : une seule vue permanente
(`MainView`, deux colonnes) plutôt qu'une succession d'écrans dans un
`QStackedWidget` -- la structure ne change jamais, quelle que soit
l'opération en cours. Les choix ponctuels (carte, fichier, confirmation,
aide) s'ouvrent en fenêtres modales par-dessus cette vue. Pilote le worker
élevé (`WorkerRunner`) pour `backup`/`flash`, et `PartitionJobRunner`
(aucune élévation nécessaire, §3) pour les extractions/injections --
progression et résultats s'affichent désormais dans le journal de bord
permanent (`LogPanel`), pas dans des écrans Exécution/Résultat séparés
(tous deux supprimés)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QMainWindow, QMessageBox

from r36s_studio.detect import detect_workflow_status
from r36s_studio.devices import Device, list_devices
from r36s_studio.partitions import BOOT_LABEL, EASYROMS_LABEL, archives
from r36s_studio.partitions.eject import eject as eject_device
from r36s_studio.safety import SafetyConfig, filter_devices

from .partition_runner import PartitionJobRunner
from .reveal import reveal
from .screens import (
    ConfirmDialog,
    DeviceDialog,
    FileDialog,
    HelpDialog,
    HomeScreen,
    LogPanel,
    MainView,
    _OPERATION_TITLE_KEYS,
    _format_size,
    build_console_stage,
)
from .strings import friendly_error_message, tr
from .worker_runner import WorkerRunner

# Pane "Accès complet au disque" de Réglages Système -- lien profond ouvert
# par la fenêtre Aide (§3, `HelpDialog`) pour éviter à l'utilisateur de
# naviguer les Réglages Système à la main.
_MACOS_FULL_DISK_ACCESS_SETTINGS_URL = "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"

_EXTRACTION_MODES = {"extract_boot", "extract_easyroms"}
_INJECTION_MODES = {"inject_boot", "copy_games"}

# Jobs qui écrivent sur la carte (ou l'éjectent) -- tous sauf "backup", qui
# n'écrit que dans un fichier (§5 point 6) -- proposent d'éjecter ensuite.
_ALLOW_EJECT_AFTER_MODES = {
    "flash",
    "inject_boot",
    "copy_games",
    "extract_boot",
    "extract_easyroms",
}
_PARTITION_JOB_MODES = {"extract_boot", "extract_easyroms", "inject_boot", "copy_games"}
_ARCHIVE_LABEL_BY_MODE = {
    "extract_boot": BOOT_LABEL,
    "extract_easyroms": EASYROMS_LABEL,
    "inject_boot": BOOT_LABEL,
    "copy_games": EASYROMS_LABEL,
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app_title"))
        self.resize(1120, 760)  # deux colonnes (§5, refonte navigation) : plus large qu'un seul écran

        self._mode: Optional[str] = None
        self._device: Optional[Device] = None
        self._file_path: Optional[str] = None
        self._runner: Optional[object] = None  # WorkerRunner | PartitionJobRunner
        self._last_error_code: Optional[str] = None
        self._last_error_msg: Optional[str] = None
        self._last_progress_bytes = 0  # taille de l'archive créée (étapes A/B, journal de bord)

        # Vue permanente, deux colonnes -- ne change plus jamais de
        # structure (§5, refonte navigation). `_home` (gauche) et
        # `_log_panel` (droite, bas) restent accessibles directement ;
        # `_console_stage` (droite, haut, purement décorative -- animations
        # mises en pause pendant une opération, §5) peut être `None` si
        # l'image source est absente.
        self._home = HomeScreen()
        self._log_panel = LogPanel()
        self._console_stage = build_console_stage()
        self._main_view = MainView(self._home, self._console_stage, self._log_panel)
        self.setCentralWidget(self._main_view)

        # Fenêtres modales (§5, refonte navigation) : construites une fois,
        # ouvertes (`open()`, non bloquant) et fermées par `MainWindow` au
        # fil du parcours -- jamais un écran de remplacement.
        self._device_dialog = DeviceDialog(self)
        self._file_dialog = FileDialog(self)
        self._confirm_dialog = ConfirmDialog(self)
        self._help_dialog = HelpDialog(self)

        self._wire_signals()
        self._refresh_home_state()

    def _wire_signals(self) -> None:
        self._home.extract_boot_selected.connect(lambda: self._start_flow("extract_boot"))
        self._home.extract_easyroms_selected.connect(lambda: self._start_flow("extract_easyroms"))
        self._home.flash_selected.connect(lambda: self._start_flow("flash"))
        self._home.inject_boot_selected.connect(lambda: self._start_flow("inject_boot"))
        self._home.copy_games_selected.connect(lambda: self._start_flow("copy_games"))
        self._home.eject_selected.connect(lambda: self._start_flow("eject"))
        self._home.backup_selected.connect(lambda: self._start_flow("backup"))
        self._home.refresh_requested.connect(self._refresh_home_state)
        self._home.help_requested.connect(self._help_dialog.open)

        self._help_dialog.open_settings_requested.connect(self._on_open_settings_requested)

        self._device_dialog.refresh_requested.connect(self._refresh_devices)
        self._device_dialog.device_chosen.connect(self._on_device_chosen)

        self._file_dialog.file_chosen.connect(self._on_file_chosen)

        self._confirm_dialog.confirmed.connect(self._on_confirmed)

        self._log_panel.cancel_requested.connect(self._on_cancel_requested)
        self._log_panel.eject_requested.connect(self._on_eject_requested)
        self._log_panel.reveal_requested.connect(self._on_reveal_requested)

    # --- colonne gauche, annotée par detect.detect_workflow_status (§4.5) --

    def _list_safe_devices(self) -> List[Device]:
        try:
            devices = list_devices()
        except NotImplementedError as exc:
            QMessageBox.critical(self, tr("app_title"), str(exc))
            return []
        return filter_devices(devices, SafetyConfig())

    def _refresh_home_state(self) -> None:
        """Une seule carte candidate : son contenu annote le statut des six
        étapes. Zéro ou plusieurs : `detect_workflow_status(None)` marque
        tout « non pertinent » sans qu'aucune ligne ne disparaisse pour
        autant (§4.5) — la fenêtre Choix de la carte guide dans tous les
        cas vers le bon geste (brancher une carte, ou choisir laquelle)."""
        devices = self._list_safe_devices()
        device = devices[0] if len(devices) == 1 else None
        self._home.set_status(detect_workflow_status(device), device)

    # --- déclenchement d'une étape -> fenêtre Choix de la carte -------------

    def _start_flow(self, mode: str) -> None:
        self._mode = mode
        self._device = None
        self._file_path = None
        self._refresh_devices()
        self._device_dialog.open()

    def _refresh_devices(self) -> None:
        self._device_dialog.set_devices(self._list_safe_devices())

    # --- carte choisie -> fenêtre Fichier, ou directement l'opération -------

    def _on_device_chosen(self, device: Device) -> None:
        self._device = device
        self._device_dialog.close()

        if self._mode == "eject":
            # Étape F : ni fichier ni opération suivie de progression,
            # l'éjection est immédiate (§4.5).
            self._perform_eject()
            return

        if self._mode in _EXTRACTION_MODES:
            # Étapes A/B : un emplacement par défaut est proposé
            # (~/Documents/R36S Studio), mais l'utilisateur choisit
            # toujours activement où son archive est enregistrée --
            # y compris un disque externe. Le nom horodaté, lui, reste
            # toujours généré automatiquement (§4.4), à l'intérieur de
            # l'emplacement retenu.
            self._file_dialog.set_mode(self._mode, default_path=str(archives.default_archives_dir()))
            self._file_dialog.open()
            return

        archive_choices = None
        if self._mode in _INJECTION_MODES:
            # Étapes D/E : proposer les sauvegardes déjà extraites plutôt
            # que de redemander un dossier à chaque fois.
            archive_choices = archives.list_archives(_ARCHIVE_LABEL_BY_MODE[self._mode])
        self._file_dialog.set_mode(self._mode, archive_choices=archive_choices)
        self._file_dialog.open()

    # --- fichier choisi -> fenêtre Confirmation (flash) ou opération --------

    def _on_file_chosen(self, path: str) -> None:
        if self._mode in _EXTRACTION_MODES:
            # `path` est l'emplacement choisi (défaut accepté ou remplacé) ;
            # le nom horodaté de l'archive est ajouté ici, à l'intérieur.
            label = _ARCHIVE_LABEL_BY_MODE[self._mode]
            self._file_path = str(archives.new_archive_path(label, base_dir=Path(path)))
        else:
            self._file_path = path
        self._file_dialog.close()

        if self._mode == "flash":
            # Le flash écrit sur le périphérique brut : confirmation
            # explicite obligatoire (règle §2 n°6). Les autres jobs
            # n'effacent rien (sauvegarde vers un fichier, ou copie de
            # fichiers sur une partition déjà en usage) — pas de fenêtre
            # rouge.
            self._confirm_dialog.set_device(self._device)
            self._confirm_dialog.open()
        else:
            self._start_worker()

    def _on_confirmed(self) -> None:
        self._confirm_dialog.close()
        self._start_worker()

    # --- opération : journal de bord permanent (§5, refonte navigation) ----

    def _start_worker(self) -> None:
        self._log_panel.start_operation(tr(_OPERATION_TITLE_KEYS[self._mode]))
        self._home.set_busy(True)
        if self._console_stage is not None:
            # Pas d'intérêt à faire tourner ces animations pour rien
            # pendant une opération longue (§5) -- le journal de bord
            # suffit comme signal d'activité.
            self._console_stage.pause()
        self._last_error_code = None
        self._last_error_msg = None
        self._last_progress_bytes = 0

        if self._mode in _PARTITION_JOB_MODES:
            # Écrit sur une partition déjà montée (ou lit une partition
            # pour extraire vers l'ordinateur), pas le périphérique brut
            # (§4.4) : aucune élévation nécessaire, donc pas de worker
            # séparé (§3) -- voir `partition_runner.py`.
            self._runner = PartitionJobRunner(self._mode, self._device, self._file_path, parent=self)
            self._runner.progress.connect(self._on_progress)
            self._runner.error.connect(self._on_worker_error)
            self._runner.finished_job.connect(self._on_worker_finished)
            self._runner.start()
            return

        if self._mode == "backup":
            argv = ["backup", "--device", self._device.path, "--output", self._file_path]
        else:
            argv = ["flash", "--image", self._file_path, "--device", self._device.path]

        self._runner = WorkerRunner(argv, parent=self)
        self._runner.progress.connect(self._on_progress)
        self._runner.log.connect(lambda level, msg: self._log_panel.append_log(msg))
        self._runner.error.connect(self._on_worker_error)
        self._runner.finished.connect(self._on_worker_finished)
        self._runner.start()

    # `@Slot` explicite sur ces trois méthodes : ce sont les seules qui
    # reçoivent un signal pouvant traverser une frontière de thread réelle
    # (`PartitionJobRunner`, un vrai `QThread`, §4.4) -- contrairement à
    # `WorkerRunner`, dont les signaux sont toujours émis sur le thread Qt
    # principal (`_poll()` via `QTimer`, jamais un thread séparé). Sans
    # cette annotation, PySide6 doit retomber sur une résolution plus
    # générique du slot Python pour une connexion mise en file d'attente ;
    # la déclarer explicitement lève toute ambiguïté sur la signature côté
    # méta-objet C++, quel que soit l'émetteur.
    #
    # "qint64", pas "int" : doit correspondre exactement à `Signal("qint64",
    # "qint64", float)` (`worker_runner.py`/`partition_runner.py`) -- un
    # `int` C++ (32 bits) déborde silencieusement au-delà de ~2 Go, ce qui
    # produisait `AttributeError: Slot '...(int,int,double)' not found`
    # (trompeur : le vrai problème était la conversion de l'argument, pas
    # l'absence du slot), constaté en conditions réelles au-delà de 2^31
    # octets (flash d'une carte de 32 Go).
    @Slot("qint64", "qint64", float)
    def _on_progress(self, done: int, total: int, speed: float) -> None:
        # `done` du tout dernier événement = le compte final exact (§2 n°5,
        # `copy_range`/`copy_tree`) -- utilisé comme taille de l'archive
        # créée par les étapes A/B (journal de bord).
        self._last_progress_bytes = done
        self._log_panel.update_progress(done, total, speed)

    def _on_cancel_requested(self) -> None:
        if self._runner is not None:
            self._log_panel.set_cancel_enabled(False)
            self._runner.cancel()

    @Slot(str, str)
    def _on_worker_error(self, code: str, msg: str) -> None:
        self._last_error_code = code
        self._last_error_msg = msg

    def _success_message(self) -> str:
        if self._mode == "backup":
            return f"{self._device.display} a été sauvegardée dans {self._file_path}."
        if self._mode == "extract_boot":
            return "L'écran et les réglages d'origine ont été copiés sur ton ordinateur."
        if self._mode == "extract_easyroms":
            return "Tes jeux et sauvegardes ont été copiés sur ton ordinateur."
        if self._mode == "inject_boot":
            return f"{self._device.display} a retrouvé son écran d'origine."
        if self._mode == "copy_games":
            return f"Les jeux ont été copiés sur {self._device.display}."
        return f"{self._device.display} est prête."  # flash

    def _archive_info(self) -> str:
        """Ligne supplémentaire du journal de bord précisant l'archive
        concernée (créée pour A/B, source pour D/E) -- jamais pour
        backup/flash, qui ne manipulent pas de dossier d'archive."""
        if self._mode in _EXTRACTION_MODES:
            return tr("result_archive_created", path=self._file_path, size=_format_size(self._last_progress_bytes))
        if self._mode in _INJECTION_MODES:
            return tr("result_archive_source", path=self._file_path)
        return ""

    @Slot(bool)
    def _on_worker_finished(self, ok: bool) -> None:
        self._home.set_busy(False)
        if self._console_stage is not None:
            self._console_stage.resume()
        if ok:
            allow_eject = self._mode in _ALLOW_EJECT_AFTER_MODES
            archive_info = self._archive_info()
            reveal_path = self._file_path if self._mode in (_EXTRACTION_MODES | _INJECTION_MODES) else None
            if archive_info:
                self._log_panel.append_log(archive_info)
            self._log_panel.finish_success(self._success_message(), allow_eject=allow_eject, reveal_path=reveal_path)
        else:
            # `friendly_error_message` mappe déjà "CANCELLED" sur le
            # message d'annulation adéquat (`strings._ERROR_MESSAGE_KEYS`)
            # -- pas besoin de le distinguer ici séparément, contrairement
            # à l'ancien écran Résultat qui en avait besoin pour choisir
            # entre deux titres différents.
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=self._last_error_msg or "")
        self._refresh_home_state()

    def _on_reveal_requested(self, path: str) -> None:
        try:
            reveal(path)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))

    # --- fenêtre Aide (macOS uniquement, §3) --------------------------------

    def _on_open_settings_requested(self) -> None:
        """Bouton "Ouvrir les réglages" de `HelpDialog` -- lien profond vers
        le panneau Accès complet au disque. Ce bouton n'existe que sur
        macOS (`HelpDialog` n'y est accessible que via `HomeScreen`, qui ne
        propose ce chemin que sur macOS, §5)."""
        try:
            subprocess.run(["open", _MACOS_FULL_DISK_ACCESS_SETTINGS_URL], check=True)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))

    # --- étape F : éjection, immédiate ou depuis le journal -----------------

    def _perform_eject(self) -> None:
        """Étape F : démonte toutes les partitions et éjecte, puis
        confirme explicitement que la carte peut être retirée (§4.5) --
        jamais un succès silencieux. Résultat affiché dans le journal de
        bord, pas un écran séparé (§5, refonte navigation)."""
        self._log_panel.append_log("Éjection de la carte…")
        try:
            eject_device(self._device.path)
        except Exception as exc:
            self._log_panel.append_log(friendly_error_message("EJECT_FAILED"))
            self._log_panel.append_log(str(exc))
        else:
            self._log_panel.append_log(f"{self._device.display} peut maintenant être retirée en toute sécurité.")
        self._refresh_home_state()

    def _on_eject_requested(self) -> None:
        """Bouton Éjecter du journal de bord, proposé après une opération
        qui a écrit sur la carte (§4.5) -- distinct de `_perform_eject`
        (l'étape F elle-même, immédiate, sans opération préalable)."""
        try:
            eject_device(self._device.path)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))
        else:
            self._log_panel.append_log(f"{self._device.display} peut maintenant être retirée en toute sécurité.")
