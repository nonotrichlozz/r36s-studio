"""Fenêtre principale : fait traverser à l'utilisateur les six écrans de
l'assistant (§5) via un `QStackedWidget`, et pilote le worker élevé
(`WorkerRunner`) pour les étapes `backup`/`flash`."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget, QWidget

from r36s_studio.devices import Device, list_devices
from r36s_studio.safety import SafetyConfig, filter_devices

from . import eject
from .screens import ConfirmScreen, DeviceScreen, ExecuteScreen, FileScreen, HomeScreen, ResultScreen
from .strings import tr
from .worker_runner import WorkerRunner


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app_title"))
        self.resize(560, 420)

        self._mode: Optional[str] = None  # "backup" | "flash"
        self._device: Optional[Device] = None
        self._file_path: Optional[str] = None
        self._runner: Optional[WorkerRunner] = None
        self._last_error_code: Optional[str] = None
        self._last_error_msg: Optional[str] = None

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
        self._show(self._home)

    # --- navigation ---------------------------------------------------

    def _show(self, screen: QWidget) -> None:
        self._stack.setCurrentWidget(screen)

    def _wire_signals(self) -> None:
        self._home.backup_selected.connect(lambda: self._start_flow("backup"))
        self._home.flash_selected.connect(lambda: self._start_flow("flash"))

        self._device_screen.back_requested.connect(lambda: self._show(self._home))
        self._device_screen.refresh_requested.connect(self._refresh_devices)
        self._device_screen.device_chosen.connect(self._on_device_chosen)

        self._file_screen.back_requested.connect(lambda: self._show(self._device_screen))
        self._file_screen.file_chosen.connect(self._on_file_chosen)

        self._confirm_screen.cancelled.connect(lambda: self._show(self._file_screen))
        self._confirm_screen.confirmed.connect(self._start_worker)

        self._execute_screen.cancel_requested.connect(self._on_cancel_requested)

        self._result_screen.eject_requested.connect(self._on_eject_requested)
        self._result_screen.home_requested.connect(lambda: self._show(self._home))

    # --- écran 1 (Accueil) -> 2 (Périphérique) -----------------------------

    def _start_flow(self, mode: str) -> None:
        self._mode = mode
        self._device = None
        self._file_path = None
        self._refresh_devices()
        self._show(self._device_screen)

    def _refresh_devices(self) -> None:
        try:
            devices = list_devices()
        except NotImplementedError as exc:
            QMessageBox.critical(self, tr("app_title"), str(exc))
            devices = []
        safe_devices = filter_devices(devices, SafetyConfig())
        self._device_screen.set_devices(safe_devices)

    # --- écran 2 -> 3 (Fichier) ---------------------------------------------

    def _on_device_chosen(self, device: Device) -> None:
        self._device = device
        self._file_screen.set_mode(self._mode)
        self._show(self._file_screen)

    # --- écran 3 -> 4 (Confirmation, flash uniquement) ou -> 5 (backup) ----

    def _on_file_chosen(self, path: str) -> None:
        self._file_path = path
        if self._mode == "flash":
            # Le flash écrit sur le périphérique : confirmation explicite
            # obligatoire (règle §2 n°6). La sauvegarde n'écrit que dans un
            # fichier, jamais sur le périphérique — pas d'écran rouge.
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

        if self._mode == "backup":
            argv = ["backup", "--device", self._device.path, "--output", self._file_path]
        else:
            argv = ["flash", "--image", self._file_path, "--device", self._device.path]

        self._runner = WorkerRunner(argv, parent=self)
        self._runner.progress.connect(self._execute_screen.update_progress)
        self._runner.log.connect(lambda level, msg: self._execute_screen.append_log(msg))
        self._runner.error.connect(self._on_worker_error)
        self._runner.finished.connect(self._on_worker_finished)
        self._runner.start()

    def _on_cancel_requested(self) -> None:
        if self._runner is not None:
            self._execute_screen.set_cancel_enabled(False)
            self._runner.cancel()

    def _on_worker_error(self, code: str, msg: str) -> None:
        self._last_error_code = code
        self._last_error_msg = msg

    def _on_worker_finished(self, ok: bool) -> None:
        if ok:
            message = (
                f"{self._device.display} a été sauvegardée dans {self._file_path}."
                if self._mode == "backup"
                else f"{self._device.display} est prête."
            )
            self._result_screen.show_success(message, allow_eject=(self._mode == "flash"))
        else:
            cancelled = self._last_error_code == "CANCELLED"
            self._result_screen.show_error(
                self._last_error_msg or "Une erreur inconnue est survenue.", cancelled=cancelled
            )
        self._show(self._result_screen)

    # --- écran 6 : Résultat --------------------------------------------------

    def _on_eject_requested(self) -> None:
        try:
            eject.eject(self._device.path)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))
