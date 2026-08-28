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

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget

from r36s_studio import config as app_config
from r36s_studio.detect import detect_workflow_status
from r36s_studio.devices import Device, list_devices
from r36s_studio.identify.dtb import DtbInfo
from r36s_studio.partitions import BOOT_LABEL, EASYROMS_LABEL, archives
from r36s_studio.partitions.eject import eject as eject_device
from r36s_studio.safety import SafetyConfig, filter_devices
from r36s_studio.safety.card_fingerprint import compute_boot_fingerprint, is_same_card

from .partition_runner import PartitionJobRunner, WizardIdentifyRunner
from .reveal import reveal
from .screens import (
    AssistedLandingScreen,
    ConfirmDialog,
    DeviceDialog,
    FileDialog,
    HelpDialog,
    HomeScreen,
    LogPanel,
    MainView,
    WizardStepPanel,
    _OPERATION_TITLE_KEYS,
    _format_size,
    build_console_stage,
)
from .strings import friendly_error_message, tr
from .wizard_flow import WizardFlow, WizardJob
from .worker_runner import WorkerRunner

_WIZARD_POLL_INTERVAL_MS = 1500

# Étape 3 (§5 mode assisté) recouvre deux jobs internes (EXTRACT_BOOT puis
# EXTRACT_EASYROMS, gui/wizard_flow.py) mais un seul écran -- même titre/
# consigne pour les deux.
_WIZARD_STEP_STRINGS = {
    WizardJob.DETECT_SOURCE: ("wizard_step1_title", "wizard_step1_instruction"),
    WizardJob.IDENTIFY: ("wizard_step2_title", "wizard_step2_instruction"),
    WizardJob.EXTRACT_BOOT: ("wizard_step3_title", "wizard_step3_instruction"),
    WizardJob.EXTRACT_EASYROMS: ("wizard_step3_title", "wizard_step3_instruction"),
    WizardJob.DETECT_TARGET: ("wizard_step4_title", "wizard_step4_instruction"),
    WizardJob.FLASH: ("wizard_step5_title", "wizard_step5_instruction"),
    WizardJob.INJECT_BOOT: ("wizard_step6_title", "wizard_step6_instruction"),
    WizardJob.EJECT: ("wizard_step7_title", "wizard_step7_instruction"),
}
_WIZARD_JOB_TO_EXPERT_MODE = {
    WizardJob.EXTRACT_BOOT: "extract_boot",
    WizardJob.EXTRACT_EASYROMS: "extract_easyroms",
    WizardJob.INJECT_BOOT: "inject_boot",
}

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

        # Mode assisté (§5 mode assisté) : `WizardFlow` (testable sans Qt,
        # gui/wizard_flow.py) séquence les 7 étapes ; l'état collecté au
        # fil du parcours vit ici, à plat, même convention que `_device`/
        # `_file_path` ci-dessus plutôt qu'une classe d'état séparée.
        self._app_config = app_config.load_config()
        self._wizard_active = False
        self._wizard_flow = WizardFlow()
        self._wizard_poll_timer = QTimer(self)
        self._wizard_poll_timer.setInterval(_WIZARD_POLL_INTERVAL_MS)
        self._wizard_poll_timer.timeout.connect(self._on_wizard_poll)
        self._wizard_source_device: Optional[Device] = None
        self._wizard_source_fingerprint: Optional[str] = None
        self._wizard_target_device: Optional[Device] = None
        self._wizard_boot_archive: Optional[str] = None
        self._wizard_easyroms_archive: Optional[str] = None

        # Vue permanente, deux colonnes -- ne change plus jamais de
        # structure (§5, refonte navigation). `_home` (gauche, mode
        # expert) et `_wizard_panel` (gauche, mode assisté en cours)
        # partagent la même `MainView` -- un `QStackedWidget` interne
        # bascule entre les deux (`MainView.show_home`/
        # `show_wizard_panel`). `_log_panel` (droite, bas) reste unique et
        # partagé entre les deux modes ; `_console_stage` (droite, haut,
        # purement décorative -- animations mises en pause pendant une
        # opération, §5) peut être `None` si l'image source est absente.
        # `_assisted_landing` a sa propre console, plus grande (§5 mode
        # assisté) -- MainView et AssistedLandingScreen ne sont jamais
        # affichés en même temps, donc pas de conflit de parent.
        self._home = HomeScreen()
        self._log_panel = LogPanel()
        self._console_stage = build_console_stage()
        self._wizard_panel = WizardStepPanel()
        self._main_view = MainView(self._home, self._console_stage, self._log_panel, wizard_panel=self._wizard_panel)
        self._assisted_landing = AssistedLandingScreen()

        self._root_stack = QStackedWidget()
        self._root_stack.addWidget(self._assisted_landing)
        self._root_stack.addWidget(self._main_view)
        self.setCentralWidget(self._root_stack)

        # Fenêtres modales (§5, refonte navigation) : construites une fois,
        # ouvertes (`open()`, non bloquant) et fermées par `MainWindow` au
        # fil du parcours -- jamais un écran de remplacement.
        self._device_dialog = DeviceDialog(self)
        self._file_dialog = FileDialog(self)
        self._confirm_dialog = ConfirmDialog(self)
        self._help_dialog = HelpDialog(self)

        self._wire_signals()
        self._refresh_home_state()

        if self._app_config.ui_mode == "expert":
            self._main_view.show_home()
            self._root_stack.setCurrentWidget(self._main_view)
        else:
            self._root_stack.setCurrentWidget(self._assisted_landing)

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

        self._assisted_landing.prepare_requested.connect(self._start_wizard)
        self._assisted_landing.expert_mode_requested.connect(self._switch_to_expert_mode)

        self._wizard_panel.continue_requested.connect(self._on_wizard_continue)
        self._wizard_panel.cancel_requested.connect(self._cancel_wizard)
        self._wizard_panel.resume_requested.connect(self._resume_wizard)
        self._wizard_panel.expert_mode_requested.connect(self._switch_to_expert_mode)

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
        if self._wizard_active:
            # Mode assisté (§5 mode assisté) : la suite (avancer/erreur)
            # est décidée par `WizardFlow`, pas par le mode expert
            # ci-dessous -- `_on_worker_finished` reste le seul point
            # d'arrivée des runners (`_start_worker`), réutilisé tel quel.
            self._on_wizard_job_finished(ok)
            return
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

    # --- mode assisté (§5 mode assisté) : 7 étapes, une carte puis l'autre --

    def _switch_to_expert_mode(self) -> None:
        """Bouton « Mode expert », depuis l'accueil assisté ou depuis une
        étape en erreur (§5) -- n'annule/ne défait aucune opération déjà
        réussie : une archive déjà extraite reste utilisable depuis
        l'étape D du mode expert."""
        if self._wizard_poll_timer.isActive():
            self._wizard_poll_timer.stop()
        self._wizard_active = False
        self._app_config.ui_mode = "expert"
        app_config.save_config(self._app_config)
        self._main_view.show_home()
        self._root_stack.setCurrentWidget(self._main_view)
        self._refresh_home_state()

    def _start_wizard(self) -> None:
        self._app_config.ui_mode = "assisted"
        app_config.save_config(self._app_config)
        self._wizard_flow.reset()
        self._wizard_active = True
        self._wizard_source_device = None
        self._wizard_source_fingerprint = None
        self._wizard_target_device = None
        self._wizard_boot_archive = None
        self._wizard_easyroms_archive = None
        self._log_panel.set_idle()
        self._main_view.show_wizard_panel()
        self._root_stack.setCurrentWidget(self._main_view)
        self._enter_wizard_job(self._wizard_flow.current_job())

    def _cancel_wizard(self) -> None:
        """Annule le job en cours s'il y en a un, puis retour direct à
        l'accueil assisté (§5) -- aucune opération déjà terminée n'est
        défaite, seul le parcours guidé s'arrête."""
        if self._wizard_poll_timer.isActive():
            self._wizard_poll_timer.stop()
        if self._runner is not None:
            self._runner.cancel()
        self._wizard_active = False
        self._root_stack.setCurrentWidget(self._assisted_landing)

    def _enter_wizard_job(self, job: Optional[WizardJob]) -> None:
        if job is None:
            self._finish_wizard()
            return

        title_key, instruction_key = _WIZARD_STEP_STRINGS[job]
        self._wizard_panel.show_step(tr(title_key), tr(instruction_key), can_continue=False)

        if job in (WizardJob.DETECT_SOURCE, WizardJob.DETECT_TARGET):
            self._wizard_panel.set_status(tr("wizard_status_waiting"))
            self._wizard_poll_timer.start()
        elif job == WizardJob.IDENTIFY:
            self._run_wizard_identify()
        elif job in (WizardJob.EXTRACT_BOOT, WizardJob.EXTRACT_EASYROMS):
            self._run_wizard_partition_job(job)
        elif job == WizardJob.FLASH:
            self._enter_wizard_flash()
        elif job == WizardJob.INJECT_BOOT:
            self._run_wizard_partition_job(job)
        elif job == WizardJob.EJECT:
            self._run_wizard_eject()

    def _on_wizard_continue(self) -> None:
        """Continuer ne concerne que les étapes qui l'activent elles-mêmes
        (détection de carte, identification) -- les jobs qui écrivent/
        copient avancent d'eux-mêmes via `_on_wizard_job_finished`."""
        job = self._wizard_flow.current_job()
        self._wizard_flow.mark_done(job)
        self._enter_wizard_job(self._wizard_flow.current_job())

    def _resume_wizard(self) -> None:
        """`current_job()` désigne toujours le job qui a réellement échoué
        -- un job déjà réussi reste marqué fait et n'est jamais rejoué
        (`WizardFlow`, voir son propre test de reprise partielle)."""
        self._enter_wizard_job(self._wizard_flow.current_job())

    def _finish_wizard(self) -> None:
        self._wizard_active = False
        self._log_panel.append_log(tr("wizard_finished"))
        self._wizard_panel.show_step(tr("wizard_step7_title"), tr("wizard_finished"), can_continue=False)
        self._refresh_home_state()

    # --- étapes 1/4 : détection, avec garde-fou d'empreinte à l'étape 4 -----

    def _on_wizard_poll(self) -> None:
        devices = self._list_safe_devices()
        candidate = devices[0] if len(devices) == 1 else None
        job = self._wizard_flow.current_job()

        if candidate is None:
            self._wizard_panel.set_status(tr("wizard_status_waiting"))
            self._wizard_panel.set_can_continue(False)
            return

        if job == WizardJob.DETECT_SOURCE:
            self._wizard_poll_timer.stop()
            self._wizard_source_device = candidate
            self._wizard_source_fingerprint = compute_boot_fingerprint(candidate.path)
            self._wizard_panel.set_status(tr("wizard_status_device_found", display=candidate.display))
            self._wizard_panel.set_can_continue(True)
        elif job == WizardJob.DETECT_TARGET:
            fingerprint = compute_boot_fingerprint(candidate.path)
            if is_same_card(self._wizard_source_fingerprint, fingerprint):
                self._wizard_panel.set_status(tr("wizard_status_same_card"))
                self._wizard_panel.set_can_continue(False)
                return
            self._wizard_poll_timer.stop()
            self._wizard_target_device = candidate
            self._wizard_panel.set_status(tr("wizard_status_device_found", display=candidate.display))
            self._wizard_panel.set_can_continue(True)

    # --- étape 2 : identification (thread séparé, §4.4) ---------------------

    def _run_wizard_identify(self) -> None:
        self._identify_runner = WizardIdentifyRunner(self._wizard_source_device.path, parent=self)
        self._identify_runner.finished_identify.connect(self._on_wizard_identify_finished)
        self._identify_runner.start()

    def _on_wizard_identify_finished(self, info: Optional[DtbInfo]) -> None:
        if info is None:
            self._log_panel.append_log(tr("wizard_identify_failed"))
            self._wizard_panel.set_status(tr("wizard_identify_failed"))
        else:
            message = tr("wizard_identify_result", board=info.board_compatible or "?", panel=info.panel_compatible or "?")
            self._log_panel.append_log(message)
            self._wizard_panel.set_status(message)
        self._wizard_panel.set_can_continue(True)

    # --- étapes 3/6 : extraction/injection, réutilise PartitionJobRunner ----

    def _run_wizard_partition_job(self, job: WizardJob) -> None:
        self._mode = _WIZARD_JOB_TO_EXPERT_MODE[job]
        if job == WizardJob.EXTRACT_BOOT:
            self._device = self._wizard_source_device
            self._file_path = str(archives.new_archive_path(BOOT_LABEL, base_dir=archives.default_archives_dir()))
        elif job == WizardJob.EXTRACT_EASYROMS:
            self._device = self._wizard_source_device
            self._file_path = str(
                archives.new_archive_path(EASYROMS_LABEL, base_dir=archives.default_archives_dir())
            )
        else:  # INJECT_BOOT
            self._device = self._wizard_target_device
            self._file_path = self._wizard_boot_archive
        self._start_worker()

    def _on_wizard_job_finished(self, ok: bool) -> None:
        job = self._wizard_flow.current_job()
        if not ok:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=self._last_error_msg or "")
            self._wizard_panel.show_error()
            return

        if job == WizardJob.EXTRACT_BOOT:
            self._wizard_boot_archive = self._file_path
        elif job == WizardJob.EXTRACT_EASYROMS:
            self._wizard_easyroms_archive = self._file_path

        archive_info = self._archive_info()
        if archive_info:
            self._log_panel.append_log(archive_info)
        self._log_panel.finish_success(self._success_message(), allow_eject=False, reveal_path=None)

        self._wizard_flow.mark_done(job)
        self._enter_wizard_job(self._wizard_flow.current_job())

    # --- étape 5 : flash -- fenêtre Fichier classique, en attendant le -------
    # --- téléchargement guidé (module identify/releases, URL en attente) ----

    def _enter_wizard_flash(self) -> None:
        self._mode = "flash"
        self._device = self._wizard_target_device
        self._file_dialog.set_mode("flash")
        self._file_dialog.open()

    # --- étape 7 : éjection, synchrone comme _perform_eject ------------------

    def _run_wizard_eject(self) -> None:
        self._log_panel.append_log("Éjection de la carte…")
        try:
            eject_device(self._wizard_target_device.path)
        except Exception as exc:
            self._last_error_code = "EJECT_FAILED"
            self._last_error_msg = str(exc)
            self._log_panel.finish_error(friendly_error_message("EJECT_FAILED"), details=str(exc))
            self._wizard_panel.show_error()
            return
        self._log_panel.append_log(
            f"{self._wizard_target_device.display} peut maintenant être retirée en toute sécurité."
        )
        self._wizard_flow.mark_done(WizardJob.EJECT)
        self._enter_wizard_job(self._wizard_flow.current_job())
