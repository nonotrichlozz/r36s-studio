"""Fenêtre principale : fait traverser à l'utilisateur les six écrans de
l'assistant (§5) via un `QStackedWidget`. Pilote le worker élevé
(`WorkerRunner`) pour `backup`/`flash`, et `PartitionJobRunner` (aucune
élévation nécessaire, §3) pour les extractions/injections. L'Accueil
affiche toujours les six étapes du workflow à deux cartes (§4.4/§4.5),
`detect.detect_workflow_status` ne servant qu'à les annoter d'un statut."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget, QWidget

from r36s_studio.detect import detect_workflow_status
from r36s_studio.devices import Device, list_devices
from r36s_studio.partitions import BOOT_LABEL, EASYROMS_LABEL, archives
from r36s_studio.partitions.eject import eject as eject_device
from r36s_studio.safety import SafetyConfig, filter_devices

from .partition_runner import PartitionJobRunner
from .reveal import reveal
from .screens import ConfirmScreen, DeviceScreen, ExecuteScreen, FileScreen, HomeScreen, ResultScreen, _format_size
from .strings import friendly_error_message, tr
from .worker_runner import WorkerRunner

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
        self.resize(560, 420)

        self._mode: Optional[str] = None
        self._device: Optional[Device] = None
        self._file_path: Optional[str] = None
        self._runner: Optional[object] = None  # WorkerRunner | PartitionJobRunner
        self._last_error_code: Optional[str] = None
        self._last_error_msg: Optional[str] = None
        self._last_progress_bytes = 0  # taille de l'archive créée (étapes A/B, écran Résultat)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._home = HomeScreen()
        self._device_screen = DeviceScreen()
        self._file_screen = FileScreen()
        self._confirm_screen = ConfirmScreen()
        self._execute_screen = ExecuteScreen()
        self._result_screen = ResultScreen()

        for screen in (
            self._home,
            self._device_screen,
            self._file_screen,
            self._confirm_screen,
            self._execute_screen,
            self._result_screen,
        ):
            self._stack.addWidget(screen)

        self._wire_signals()
        self._refresh_home_state()
        self._show(self._home)

    # --- navigation ---------------------------------------------------

    def _show(self, screen: QWidget) -> None:
        self._stack.setCurrentWidget(screen)

    def _wire_signals(self) -> None:
        self._home.extract_boot_selected.connect(lambda: self._start_flow("extract_boot"))
        self._home.extract_easyroms_selected.connect(lambda: self._start_flow("extract_easyroms"))
        self._home.flash_selected.connect(lambda: self._start_flow("flash"))
        self._home.inject_boot_selected.connect(lambda: self._start_flow("inject_boot"))
        self._home.copy_games_selected.connect(lambda: self._start_flow("copy_games"))
        self._home.eject_selected.connect(lambda: self._start_flow("eject"))
        self._home.backup_selected.connect(lambda: self._start_flow("backup"))
        self._home.refresh_requested.connect(self._refresh_home_state)

        self._device_screen.back_requested.connect(lambda: self._show(self._home))
        self._device_screen.refresh_requested.connect(self._refresh_devices)
        self._device_screen.device_chosen.connect(self._on_device_chosen)

        self._file_screen.back_requested.connect(lambda: self._show(self._device_screen))
        self._file_screen.file_chosen.connect(self._on_file_chosen)

        self._confirm_screen.cancelled.connect(lambda: self._show(self._file_screen))
        self._confirm_screen.confirmed.connect(self._start_worker)

        self._execute_screen.cancel_requested.connect(self._on_cancel_requested)

        self._result_screen.eject_requested.connect(self._on_eject_requested)
        self._result_screen.home_requested.connect(self._on_home_requested)
        self._result_screen.reveal_requested.connect(self._on_reveal_requested)

    # --- écran 1 : Accueil, annoté par detect.detect_workflow_status (§4.5) -

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
        tout « non pertinent » sans qu'aucune tuile ne disparaisse pour
        autant (§4.5) — l'écran Choix du périphérique guide dans tous les
        cas vers le bon geste (brancher une carte, ou choisir laquelle)."""
        devices = self._list_safe_devices()
        device = devices[0] if len(devices) == 1 else None
        self._home.set_status(detect_workflow_status(device))

    def _on_home_requested(self) -> None:
        self._refresh_home_state()
        self._show(self._home)

    # --- écran 1 (Accueil) -> 2 (Périphérique) -----------------------------

    def _start_flow(self, mode: str) -> None:
        self._mode = mode
        self._device = None
        self._file_path = None
        self._refresh_devices()
        self._show(self._device_screen)

    def _refresh_devices(self) -> None:
        self._device_screen.set_devices(self._list_safe_devices())

    # --- écran 2 -> 3 (Fichier), ou directement -> 5/6 selon l'étape --------

    def _on_device_chosen(self, device: Device) -> None:
        self._device = device

        if self._mode == "eject":
            # Étape F : ni fichier ni exécution suivie de progression,
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
            self._file_screen.set_mode(self._mode, default_path=str(archives.default_archives_dir()))
            self._show(self._file_screen)
            return

        archive_choices = None
        if self._mode in _INJECTION_MODES:
            # Étapes D/E : proposer les sauvegardes déjà extraites plutôt
            # que de redemander un dossier à chaque fois.
            archive_choices = archives.list_archives(_ARCHIVE_LABEL_BY_MODE[self._mode])
        self._file_screen.set_mode(self._mode, archive_choices=archive_choices)
        self._show(self._file_screen)

    # --- écran 3 -> 4 (Confirmation, flash uniquement) ou -> 5 (autres) ----

    def _on_file_chosen(self, path: str) -> None:
        if self._mode in _EXTRACTION_MODES:
            # `path` est l'emplacement choisi (défaut accepté ou remplacé) ;
            # le nom horodaté de l'archive est ajouté ici, à l'intérieur.
            label = _ARCHIVE_LABEL_BY_MODE[self._mode]
            self._file_path = str(archives.new_archive_path(label, base_dir=Path(path)))
        else:
            self._file_path = path

        if self._mode == "flash":
            # Le flash écrit sur le périphérique brut : confirmation
            # explicite obligatoire (règle §2 n°6). Les autres jobs
            # n'effacent rien (sauvegarde vers un fichier, ou copie de
            # fichiers sur une partition déjà en usage) — pas d'écran rouge.
            self._confirm_screen.set_device(self._device)
            self._show(self._confirm_screen)
        else:
            self._start_worker()

    # --- écran 5 : Exécution ------------------------------------------------

    def _start_worker(self) -> None:
        self._execute_screen.reset(self._mode)
        self._show(self._execute_screen)
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
        self._runner.log.connect(lambda level, msg: self._execute_screen.append_log(msg))
        self._runner.error.connect(self._on_worker_error)
        self._runner.finished.connect(self._on_worker_finished)
        self._runner.start()

    def _on_progress(self, done: int, total: int, speed: float) -> None:
        # `done` du tout dernier événement = le compte final exact (§2 n°5,
        # `copy_range`/`copy_tree`) -- utilisé comme taille de l'archive
        # créée par les étapes A/B (écran Résultat).
        self._last_progress_bytes = done
        self._execute_screen.update_progress(done, total, speed)

    def _on_cancel_requested(self) -> None:
        if self._runner is not None:
            self._execute_screen.set_cancel_enabled(False)
            self._runner.cancel()

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

    def _archive_info_and_reveal_path(self) -> tuple[str, Optional[str]]:
        """Complète l'écran Résultat avec le chemin de l'archive concernée
        (créée pour A/B, source pour D/E) -- jamais pour backup/flash, qui
        ne manipulent pas de dossier d'archive."""
        if self._mode in _EXTRACTION_MODES:
            info = tr("result_archive_created", path=self._file_path, size=_format_size(self._last_progress_bytes))
            return info, self._file_path
        if self._mode in _INJECTION_MODES:
            info = tr("result_archive_source", path=self._file_path)
            return info, self._file_path
        return "", None

    def _on_worker_finished(self, ok: bool) -> None:
        if ok:
            allow_eject = self._mode in _ALLOW_EJECT_AFTER_MODES
            archive_info, reveal_path = self._archive_info_and_reveal_path()
            self._result_screen.show_success(
                self._success_message(),
                allow_eject=allow_eject,
                archive_info=archive_info,
                reveal_path=reveal_path,
            )
        else:
            cancelled = self._last_error_code == "CANCELLED"
            friendly = friendly_error_message(self._last_error_code or "")
            self._result_screen.show_error(friendly, cancelled=cancelled, details=self._last_error_msg or "")
        self._show(self._result_screen)

    def _on_reveal_requested(self, path: str) -> None:
        try:
            reveal(path)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))

    # --- écran 6 : Résultat --------------------------------------------------

    def _perform_eject(self) -> None:
        """Étape F : démonte toutes les partitions et éjecte, puis
        confirme explicitement que la carte peut être retirée (§4.5) --
        jamais un succès silencieux."""
        try:
            eject_device(self._device.path)
        except Exception as exc:
            self._result_screen.show_error(friendly_error_message("EJECT_FAILED"), details=str(exc))
        else:
            self._result_screen.show_success(
                f"{self._device.display} peut maintenant être retirée en toute sécurité.",
                allow_eject=False,
            )
        self._show(self._result_screen)

    def _on_eject_requested(self) -> None:
        try:
            eject_device(self._device.path)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))
        else:
            QMessageBox.information(
                self,
                tr("app_title"),
                f"{self._device.display} peut maintenant être retirée en toute sécurité.",
            )
