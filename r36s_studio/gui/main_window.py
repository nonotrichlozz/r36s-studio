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

import platform
import re
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget

from r36s_studio import config as app_config
from r36s_studio.detect import detect_workflow_status
from r36s_studio.devices import Device, list_devices
from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID
from r36s_studio.imaging import (
    SevenZipArchiveError,
    UnsupportedImageFormatError,
    check_image_format,
    estimate_total_bytes,
)
from r36s_studio.partitions import BOOT_LABEL, EASYROMS_LABEL, archives, set_privileged_mount_hook
from r36s_studio.partitions.eject import eject as eject_device
from r36s_studio.safety import SafetyConfig, describe_rejection, filter_devices
from r36s_studio.safety.card_fingerprint import is_same_card

from . import elevate
from .partition_runner import (
    PartitionJobRunner,
    RocknixDownloadRunner,
    RocknixListRunner,
    SystemBackupEstimate,
    SystemBackupEstimateRunner,
    WizardFingerprintRunner,
)
from .reveal import reveal
from .screens import (
    AssistedLandingScreen,
    BackupKindDialog,
    ConfirmDialog,
    DeviceDialog,
    FileDialog,
    FullDiskAccessScreen,
    HelpDialog,
    HomeScreen,
    LogPanel,
    MainView,
    RocknixVariantDialog,
    WizardStepPanel,
    _OPERATION_TITLE_KEYS,
    _format_size,
    build_console_stage,
)
from .strings import friendly_error_message, tr
from .wizard_flow import WizardFlow, WizardJob
from .worker_runner import WorkerRunner

_WIZARD_POLL_INTERVAL_MS = 1500

# Parcours de clonage (§5 mode assisté) : une étape, un job -- plus besoin
# qu'un même écran recouvre deux jobs indépendants comme l'ancien parcours
# à 7 étapes/8 jobs (identification DTB, extraction/injection BOOT-
# EASYROMS -- déplacées vers le mode expert, qui les a déjà indépendamment
# de ce parcours).
_WIZARD_STEP_STRINGS = {
    WizardJob.DETECT_SOURCE: ("wizard_step1_title", "wizard_step1_instruction"),
    WizardJob.CREATE_IMAGE: ("wizard_step2_title", "wizard_step2_instruction"),
    WizardJob.DETECT_TARGET: ("wizard_step3_title", "wizard_step3_instruction"),
    WizardJob.RESTORE_IMAGE: ("wizard_step4_title", "wizard_step4_instruction"),
    WizardJob.EJECT: ("wizard_step5_title", "wizard_step5_instruction"),
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

        # Sauvegarde système lancée depuis l'accueil assisté (§4.3), puis
        # éventuellement le flash qui la réutilise (« Préparer une carte
        # avec cette sauvegarde ») -- vrai tant que ce parcours ponctuel
        # (hors vrai parcours guidé, `_wizard_active`) est en cours,
        # jusqu'à ce que l'utilisateur revienne explicitement à l'accueil.
        # Décide, dans `_on_worker_finished`, d'afficher la proposition de
        # suite (`WizardStepPanel.show_next_step_choice`) plutôt que de
        # laisser l'utilisateur sur un écran sans issue (défaut de
        # parcours signalé -- correctif).
        self._assisted_ad_hoc_active = False
        # « Préparer une carte avec cette sauvegarde » : le fichier est
        # déjà connu (celui qu'on vient de créer), inutile de repasser par
        # la fenêtre Choix du fichier -- seule la carte cible reste à
        # choisir. Consommé (remis à False) dès que `_on_device_chosen` en
        # tient compte.
        self._skip_file_dialog_for_flash = False
        # Candidate détectée par le sondage automatique de cette même
        # étape (`_on_prepare_card_poll`, ci-dessous) -- `None` tant
        # qu'aucune carte unique n'a été trouvée (bouton Continuer
        # désactivé, même principe que les étapes 1/4 du vrai parcours
        # guidé, §4.3 : bug corrigé, ce bandeau de détection manquait).
        self._prepare_card_candidate: Optional[Device] = None

        # Une seule autorisation macOS pour toute l'application (§5 mode
        # assisté), créée au premier besoin (`_macos_auth_session`) plutôt
        # qu'ici : ne jamais demander l'invite mot de passe avant qu'une
        # opération élevée ne soit réellement lancée. Voir
        # `_get_or_create_macos_auth_session`.
        self._macos_auth_session: Optional[elevate.MacosAuthorizationSession] = None

        # Repli élevé pour le montage forcé d'une carte GPT/EFI
        # (`partitions/locate.py::_force_mount_macos`, §4.4) -- confirmé
        # sur du vrai matériel nécessiter les droits administrateur.
        # `locate.py` reste sans dépendance vers `gui/` (§3) : ce point
        # d'extension réutilise `_get_or_create_macos_auth_session` (même
        # autorisation qu'un `WorkerRunner`, jamais redemandée) sans que
        # `locate.py` en sache quoi que ce soit. Autres OS : `pkexec`/
        # `sudo` (Linux) et UAC (Windows) n'ont pas cet équivalent léger --
        # ce point d'extension n'y est donc pas installé, `locate.py`
        # retombe sur son comportement non élevé (comportement d'origine).
        if platform.system() == "Darwin":
            set_privileged_mount_hook(self._mount_boot_privileged)

        # Mode assisté (§5 mode assisté) : `WizardFlow` (testable sans Qt,
        # gui/wizard_flow.py) séquence les 5 étapes du parcours de clonage ;
        # l'état collecté au fil du parcours vit ici, à plat, même
        # convention que `_device`/`_file_path` ci-dessus plutôt qu'une
        # classe d'état séparée.
        self._app_config = app_config.load_config()
        self._wizard_active = False
        self._wizard_flow = WizardFlow()
        self._wizard_poll_timer = QTimer(self)
        self._wizard_poll_timer.setInterval(_WIZARD_POLL_INTERVAL_MS)
        self._wizard_poll_timer.timeout.connect(self._on_wizard_poll)
        # Sondage dédié à « Préparer une carte avec cette sauvegarde »
        # (§4.3) -- distinct de `_wizard_poll_timer` : ce parcours ponctuel
        # n'est jamais un vrai `WizardJob`, `_on_wizard_poll` ne doit donc
        # jamais être appelé pour lui (il opère sur `self._wizard_flow`).
        self._prepare_card_poll_timer = QTimer(self)
        self._prepare_card_poll_timer.setInterval(_WIZARD_POLL_INTERVAL_MS)
        self._prepare_card_poll_timer.timeout.connect(self._on_prepare_card_poll)
        self._wizard_source_device: Optional[Device] = None
        self._wizard_source_fingerprint: Optional[str] = None
        self._wizard_target_device: Optional[Device] = None
        # Choix fait à l'étape 2 (`BackupKindDialog`) -- "full" (copie
        # complète) ou "system" (système seul, sans les jeux) -- décide du
        # mode passé à `_start_worker` et du texte de fin de parcours.
        self._wizard_backup_kind: Optional[str] = None
        # Taille estimée retenue à l'étape 2, quelle que soit l'option
        # choisie -- `device.size_bytes` pour une copie complète (majorant
        # sûr, `backup_device` ne dépasse jamais la taille du périphérique
        # source), le résultat du pipeline d'estimation existant pour
        # système seul. Sert uniquement au pré-contrôle d'espace disque
        # libre (`_check_free_space_or_warn`) avant de lancer la copie.
        self._wizard_estimated_backup_bytes: Optional[int] = None
        self._wizard_last_poll_diagnostic: Optional[tuple] = None

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
        # Écran de bienvenue macOS uniquement (§3) : construit
        # inconditionnellement (même principe que `_help_dialog`, dont le
        # bouton déclencheur n'apparaît lui aussi que sur macOS), mais
        # n'est choisi comme écran de démarrage que sur macOS sans Accès
        # complet au disque -- voir plus bas.
        self._fda_screen = FullDiskAccessScreen()

        self._root_stack = QStackedWidget()
        self._root_stack.addWidget(self._assisted_landing)
        self._root_stack.addWidget(self._main_view)
        self._root_stack.addWidget(self._fda_screen)
        self.setCentralWidget(self._root_stack)

        # Fenêtres modales (§5, refonte navigation) : construites une fois,
        # ouvertes (`open()`, non bloquant) et fermées par `MainWindow` au
        # fil du parcours -- jamais un écran de remplacement.
        self._device_dialog = DeviceDialog(self)
        self._file_dialog = FileDialog(self)
        self._confirm_dialog = ConfirmDialog(self)
        self._help_dialog = HelpDialog(self)
        self._rocknix_variant_dialog = RocknixVariantDialog(self)
        self._backup_kind_dialog = BackupKindDialog(self)

        self._wire_signals()
        self._refresh_home_state()

        # Écran de bienvenue macOS (§3) : prioritaire sur `ui_mode`,
        # affiché tant que l'Accès complet au disque n'est pas détecté --
        # aucun des deux accueils habituels n'a de sens tant que cette
        # autorisation manque, puisque toute opération élevée échouerait
        # de toute façon. Jamais montré ailleurs que macOS (§3, ce
        # blocage lui est spécifique).
        if platform.system() == "Darwin" and not elevate.has_full_disk_access():
            self._root_stack.setCurrentWidget(self._fda_screen)
        else:
            self._show_startup_screen()

    def _show_startup_screen(self) -> None:
        """Accueil habituel (mode expert ou assisté, selon `ui_mode`) --
        factorisé pour être réutilisé aussi bien au démarrage qu'après un
        « J'ai terminé » réussi sur l'écran de bienvenue macOS
        (`_on_fda_recheck_requested`)."""
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
        self._home.backup_system_selected.connect(lambda: self._start_flow("backup_system"))
        self._home.refresh_requested.connect(self._refresh_home_state)
        self._home.help_requested.connect(self._help_dialog.open)
        self._home.assisted_mode_requested.connect(self._switch_to_assisted_mode)

        self._help_dialog.open_settings_requested.connect(self._on_open_settings_requested)
        self._fda_screen.open_settings_requested.connect(self._on_open_settings_requested)
        self._fda_screen.recheck_requested.connect(self._on_fda_recheck_requested)

        self._device_dialog.refresh_requested.connect(self._refresh_devices)
        self._device_dialog.device_chosen.connect(self._on_device_chosen)

        self._file_dialog.file_chosen.connect(self._on_file_chosen)
        self._file_dialog.releases_requested.connect(self._on_releases_requested)
        self._file_dialog.firmware_changed.connect(self._on_firmware_changed)
        self._file_dialog.rocknix_download_requested.connect(self._on_rocknix_download_requested)
        self._rocknix_variant_dialog.variant_chosen.connect(self._on_rocknix_variant_chosen)
        self._backup_kind_dialog.full_copy_requested.connect(lambda: self._on_backup_kind_chosen("full"))
        self._backup_kind_dialog.system_only_requested.connect(lambda: self._on_backup_kind_chosen("system"))
        self._backup_kind_dialog.cancelled.connect(self._cancel_wizard)

        self._confirm_dialog.confirmed.connect(self._on_confirmed)

        self._log_panel.cancel_requested.connect(self._on_cancel_requested)
        self._log_panel.eject_requested.connect(self._on_eject_requested)
        self._log_panel.reveal_requested.connect(self._on_reveal_requested)

        self._assisted_landing.prepare_requested.connect(self._start_wizard)
        self._assisted_landing.expert_mode_requested.connect(self._switch_to_expert_mode)
        self._assisted_landing.backup_system_requested.connect(self._start_backup_system_from_assisted_landing)

        self._wizard_panel.continue_requested.connect(self._on_wizard_continue)
        self._wizard_panel.cancel_requested.connect(self._cancel_wizard)
        self._wizard_panel.resume_requested.connect(self._resume_wizard)
        self._wizard_panel.expert_mode_requested.connect(self._switch_to_expert_mode)
        self._wizard_panel.refresh_requested.connect(self._on_wizard_refresh_requested)
        # Sauvegarde système depuis l'accueil assisté (§4.3) : signaux
        # dédiés, jamais continue_requested/cancel_requested (déjà câblés
        # ci-dessus à des gestionnaires qui supposent un parcours guidé
        # réellement actif).
        self._wizard_panel.prepare_card_requested.connect(self._on_prepare_card_requested)
        self._wizard_panel.return_to_home_requested.connect(self._on_assisted_ad_hoc_return_home)

    # --- colonne gauche, annotée par detect.detect_workflow_status (§4.5) --

    def _list_devices_with_diagnostics(self) -> Tuple[List[Device], List[str]]:
        """Un seul appel `list_devices`/`filter_devices` -- le mode expert
        (`_refresh_devices`/`_refresh_home_state`) et le mode assisté
        (`_on_wizard_poll`) voient donc toujours exactement la même chose
        au même instant : un écart apparent entre les deux n'est jamais dû
        à un filtre supplémentaire côté assisté. Retourne en plus une
        ligne de diagnostic par périphérique écarté (`safety.
        describe_rejection`), pour tracer dans le journal *pourquoi* --
        plutôt que de laisser deviner un écart entre les deux modes."""
        try:
            raw_devices = list_devices()
        except NotImplementedError as exc:
            QMessageBox.critical(self, tr("app_title"), str(exc))
            return [], []
        config = SafetyConfig()
        accepted = filter_devices(raw_devices, config)
        accepted_paths = {device.path for device in accepted}
        rejected_lines = []
        for device in raw_devices:
            if device.path in accepted_paths:
                continue
            reason = describe_rejection(device, config)
            if reason is not None:
                rejected_lines.append(f"{device.display} ({device.path}) : {reason}")
        return accepted, rejected_lines

    def _list_safe_devices(self) -> List[Device]:
        accepted, _ = self._list_devices_with_diagnostics()
        return accepted

    def _refresh_home_state(self) -> None:
        """Une seule carte candidate : son contenu annote le statut des six
        étapes. Zéro ou plusieurs : `detect_workflow_status(None)` marque
        tout « non pertinent » sans qu'aucune ligne ne disparaisse pour
        autant (§4.5) — la fenêtre Choix de la carte guide dans tous les
        cas vers le bon geste (brancher une carte, ou choisir laquelle)."""
        devices = self._list_safe_devices()
        device = devices[0] if len(devices) == 1 else None
        # `device` seul ne distingue pas "aucune carte" de "plusieurs
        # candidates" (les deux valent `None`, §4.5) -- `has_device`,
        # séparément, sert justement à cette distinction pour « Par
        # sécurité » (§4.3) : au moins une carte suffit, même ambiguë.
        self._home.set_status(detect_workflow_status(device), device, has_device=bool(devices))

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
        if self._wizard_active and self._wizard_flow.current_job() in (
            WizardJob.DETECT_SOURCE,
            WizardJob.DETECT_TARGET,
        ):
            # Choix fait dans la fenêtre Choix de la carte, ouverte parce
            # que plusieurs cartes candidates étaient présentes (§4.2) --
            # ne touche jamais `self._mode`/`self._device` (état du mode
            # expert) : reprend directement le même chemin qu'un candidat
            # unique auto-détecté.
            self._device_dialog.close()
            self._start_wizard_fingerprint_check(device)
            return

        self._device = device
        self._device_dialog.close()

        if self._mode == "flash" and self._skip_file_dialog_for_flash:
            # « Préparer une carte avec cette sauvegarde » (§4.3) : le
            # fichier est déjà connu, inutile de repasser par la fenêtre
            # Choix du fichier -- seule la fenêtre Confirmation habituelle
            # reste obligatoire avant d'écrire pour de vrai (§2 n°6).
            self._skip_file_dialog_for_flash = False
            self._proceed_to_flash_confirmation()
            return

        if self._mode == "eject":
            # Étape F : ni fichier ni opération suivie de progression,
            # l'éjection est immédiate (§4.5).
            self._perform_eject()
            return

        if self._mode == "backup_system":
            # Sauvegarde système sans les jeux (§4.3) : la fenêtre Choix du
            # fichier n'ouvre qu'une fois la taille estimée (et, en
            # best-effort, le modèle de console pour le nom suggéré) --
            # jamais avant, `_start_system_backup_estimate` s'en charge.
            self._start_system_backup_estimate(device)
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
        # Flash uniquement : initialise le choix du firmware depuis la
        # configuration persistée (`config.py`) plutôt que de toujours
        # reproposer ArkOS par défaut.
        firmware = self._app_config.firmware if self._mode == "flash" else None
        self._file_dialog.set_mode(self._mode, archive_choices=archive_choices, firmware=firmware)
        self._file_dialog.open()

    # --- sauvegarde système sans les jeux (§4.3) -----------------------------

    def _start_system_backup_estimate(self, device: Device) -> None:
        """Calcule la taille estimée (et, en best-effort, le modèle de
        console) sur un thread séparé -- lire la table de partitions est
        rapide, mais le montage du BOOT pour l'identification peut
        bloquer jusqu'à `MOUNT_WAIT_SECONDS` (§4.4), un gel de l'interface
        à ce stade se lirait comme un plantage. Marque aussi l'écran
        occupé (bug corrigé : sans ceci, cliquer une autre ligne -- y
        compris Éjecter -- pendant ce calcul pouvait démarrer une seconde
        opération en même temps, un scénario plausible derrière le
        rapport « la fonction est lançable sans carte »)."""
        self._log_panel.append_log(tr("system_backup_estimating"))
        self._home.set_busy(True)
        self._assisted_landing.set_busy(True)
        if self._console_stage is not None:
            self._console_stage.pause()
        self._estimate_runner = SystemBackupEstimateRunner(device.path, parent=self)
        self._estimate_runner.finished_estimate.connect(self._on_system_backup_estimate_ready)
        self._estimate_runner.start()

    def _on_system_backup_estimate_ready(self, estimate: SystemBackupEstimate) -> None:
        if estimate.needs_elevation:
            # Repli élevé (§4.3, confirmé sur du vrai matériel) : lire la
            # table de partitions brute exige les droits administrateur
            # sur macOS -- `list_partitions` (non élevé) n'a pas pu
            # exposer la taille d'au moins une partition à sommer. Reste
            # occupé (`set_busy` pas encore relâché) : l'opération n'est
            # pas terminée, seulement son premier temps.
            self._start_elevated_system_backup_estimate(estimate.board_compatible)
            return
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        if self._console_stage is not None:
            self._console_stage.resume()
        if estimate.error:
            # Le détail brut (message de l'exception d'origine) suit
            # toujours le message principal, comme pour toute autre
            # opération (§5 vocabulaire) -- bug corrigé : cette étape
            # n'affichait auparavant que le message générique, sans
            # aucune cause exploitable.
            message = friendly_error_message(estimate.error)
            self._log_panel.append_log(message)
            if estimate.detail and estimate.detail != message:
                self._log_panel.append_log(estimate.detail)
            # La carte a pu disparaître entre le lancement et cet échec
            # (bug rapporté) -- resynchronise le bandeau et les lignes
            # « Par sécurité » sur l'état réel plutôt que de les laisser
            # sur une détection périmée.
            self._refresh_home_state()
            return
        self._finish_system_backup_estimate(estimate.size_bytes, estimate.board_compatible)

    def _finish_system_backup_estimate(self, size_bytes: int, board_compatible: Optional[str]) -> None:
        # Sans effet hors parcours de clonage (§5 mode assisté) -- l'accueil
        # assisté ad-hoc « Sauvegarder mon système sans les jeux », qui
        # partage ce même chemin, ne lit jamais ce champ. Alimente le
        # pré-contrôle d'espace disque libre (`_check_free_space_or_warn`,
        # consulté dans `_on_file_chosen`) quand ce chemin est atteint
        # depuis l'étape 2 du parcours de clonage.
        self._wizard_estimated_backup_bytes = size_bytes
        size_text = _format_size(size_bytes)
        self._log_panel.append_log(tr("system_backup_estimate_result", size=size_text))
        self._file_dialog.set_mode(
            "backup_system", default_path=self._suggested_system_backup_path(board_compatible)
        )
        # Affichée directement sur la fenêtre (§4.3 : « affiche la taille
        # estimée et demande confirmation avant de lancer ») -- après
        # `set_mode`, qui masque systématiquement cette étiquette (§5,
        # `FileDialog.set_mode`).
        self._file_dialog.set_estimated_size(tr("file_system_backup_size", size=size_text))
        self._file_dialog.open()

    def _start_elevated_system_backup_estimate(self, board_compatible: Optional[str]) -> None:
        """Relance le calcul via le worker élevé (`backup --system-only
        --estimate-only`) en réutilisant la même session d'autorisation
        que `backup`/`flash` (`_get_or_create_macos_auth_session`) --
        jamais une invite mot de passe séparée pour cette étape."""
        self._pending_estimate_board_compatible = board_compatible
        self._pending_estimate_size_bytes = None
        argv = ["backup", "--device", self._device.path, "--system-only", "--estimate-only"]
        self._estimate_worker = WorkerRunner(
            argv, parent=self, macos_auth_session=self._get_or_create_macos_auth_session()
        )
        self._estimate_worker.estimate.connect(self._on_elevated_system_backup_estimate)
        self._estimate_worker.error.connect(self._on_worker_error)
        self._estimate_worker.finished.connect(self._on_elevated_system_backup_estimate_finished)
        self._estimate_worker.start()

    def _on_elevated_system_backup_estimate(self, size_bytes: int) -> None:
        self._pending_estimate_size_bytes = size_bytes

    def _on_elevated_system_backup_estimate_finished(self, ok: bool) -> None:
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        if self._console_stage is not None:
            self._console_stage.resume()
        if not ok or self._pending_estimate_size_bytes is None:
            message = friendly_error_message(self._last_error_code or "")
            self._log_panel.append_log(message)
            if self._last_error_msg and self._last_error_msg != message:
                self._log_panel.append_log(self._last_error_msg)
            self._refresh_home_state()
            return
        self._finish_system_backup_estimate(
            self._pending_estimate_size_bytes, self._pending_estimate_board_compatible
        )

    def _suggested_system_backup_path(self, board_compatible: Optional[str]) -> str:
        """Nom de fichier proposé (§4.3 : « propose un nom de fichier
        incluant le modèle de console identifié quand il est connu ») --
        toujours remplaçable via Parcourir, jamais imposé (même principe
        que le dossier proposé pour les archives BOOT/EASYROMS,
        `archives.py`). `board_compatible` vient d'une lecture best-effort
        du `.dtb` (`SystemBackupEstimateRunner`) : un identifiant de carte
        brut (ex. `rk3326-r35s`), pas un nom convivial -- rien de tel
        n'existe ailleurs dans ce projet pour ne pas en inventer un ici."""
        timestamp = datetime.now().strftime(archives.TIMESTAMP_FORMAT)
        model_part = f"_{re.sub(r'[^A-Za-z0-9_.-]+', '-', board_compatible)}" if board_compatible else ""
        filename = f"systeme{model_part}_{timestamp}.img"
        return str(archives.default_archives_dir() / filename)

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

        if self._wizard_active and self._mode in ("backup", "backup_system"):
            # Parcours de clonage, étape 2 (§5) : vérification rapide,
            # non élevée, avant de lancer le worker élevé pour une
            # opération vouée à l'échec après potentiellement deux heures
            # de copie -- le worker refait la même vérification
            # (`INSUFFICIENT_DISK_SPACE`, __main__.py), seule autorité
            # réelle si l'estimation locale manque (`required_bytes is
            # None`, `_check_free_space_or_warn` laisse alors passer).
            if not self._check_free_space_or_warn(self._file_path, self._wizard_estimated_backup_bytes):
                return

        if self._mode == "flash":
            self._proceed_to_flash_confirmation()
        else:
            self._start_worker()

    def _check_free_space_or_warn(self, output_path: str, required_bytes: Optional[int]) -> bool:
        """Vérification rapide, non élevée (`shutil.disk_usage`), de
        l'espace disque libre sur l'ordinateur avant de créer une image
        (§ pré-vol, parcours de clonage) -- ne jamais découvrir un espace
        insuffisant après une longue copie déjà lancée. `required_bytes=
        None` (taille non encore connue) laisse toujours passer : le
        worker élevé refait la même vérification (`INSUFFICIENT_DISK_
        SPACE`), seule autorité pour bloquer réellement dans ce cas."""
        if required_bytes is None:
            return True
        free_bytes = shutil.disk_usage(Path(output_path).resolve().parent).free
        if free_bytes < required_bytes:
            QMessageBox.warning(self, tr("app_title"), friendly_error_message("INSUFFICIENT_DISK_SPACE"))
            return False
        return True

    def _proceed_to_flash_confirmation(self) -> None:
        """Validation du format puis fenêtre Confirmation -- partagé entre
        le choix normal de fichier (`_on_file_chosen`) et « Préparer une
        carte avec cette sauvegarde » (`_on_prepare_card_requested`, §4.3),
        qui connaît déjà `self._file_path` et n'a donc pas besoin de
        repasser par la fenêtre Choix du fichier."""
        # Vérifié ici, avant toute élévation de privilèges (§3) : un
        # format invalide ne doit jamais coûter à l'utilisateur une
        # demande de mot de passe administrateur pour rien. Détection par
        # octets d'en-tête (`check_image_format`), pas seulement
        # l'extension -- un fichier .7z renommé en .img serait sinon
        # écrit tel quel sur la carte sans la moindre erreur.
        try:
            check_image_format(self._file_path)
        except SevenZipArchiveError:
            QMessageBox.warning(self, tr("app_title"), friendly_error_message("SEVEN_ZIP_ARCHIVE"))
            return
        except UnsupportedImageFormatError:
            QMessageBox.warning(self, tr("app_title"), friendly_error_message("UNSUPPORTED_IMAGE_FORMAT"))
            return
        # Le flash écrit sur le périphérique brut : confirmation explicite
        # obligatoire (règle §2 n°6). Les autres jobs n'effacent rien
        # (sauvegarde vers un fichier, ou copie de fichiers sur une
        # partition déjà en usage) — pas de fenêtre rouge.
        self._confirm_dialog.set_device(self._device)
        self._confirm_dialog.open()

    def _on_confirmed(self) -> None:
        self._confirm_dialog.close()
        self._start_worker()

    # --- opération : journal de bord permanent (§5, refonte navigation) ----

    def _start_worker(self) -> None:
        self._log_panel.start_operation(tr(_OPERATION_TITLE_KEYS[self._mode]))
        if self._mode in _EXTRACTION_MODES:
            # Annoncé dès le début de la copie, pas seulement à la fin
            # (§5 mode assisté) : un débutant qui ne voit le chemin
            # qu'au succès final n'a aucune idée d'où va sa sauvegarde
            # pendant que ça copie, ni où la retrouver si l'opération
            # échoue en cours de route.
            self._log_panel.append_log(tr("wizard_archive_destination_log", path=self._file_path))
        self._home.set_busy(True)
        # Changer de mode en plein flash ou en pleine copie laisserait un
        # job orphelin (§5 mode assisté) -- garde symétrique sur les deux
        # boutons de bascule, quel que soit l'écran effectivement visible.
        self._assisted_landing.set_busy(True)
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
        elif self._mode == "backup_system":
            argv = ["backup", "--device", self._device.path, "--output", self._file_path, "--system-only"]
        else:
            argv = ["flash", "--image", self._file_path, "--device", self._device.path]

        self._runner = WorkerRunner(argv, parent=self, macos_auth_session=self._get_or_create_macos_auth_session())
        self._runner.progress.connect(self._on_progress)
        self._runner.log.connect(lambda level, msg: self._log_panel.append_log(msg))
        self._runner.error.connect(self._on_worker_error)
        self._runner.finished.connect(self._on_worker_finished)
        self._runner.start()

    def _get_or_create_macos_auth_session(self) -> Optional["elevate.MacosAuthorizationSession"]:
        """Une seule `AuthorizationRef` pour toute l'application (§5 mode
        assisté) -- correctif d'un comportement observé en usage réel : le
        parcours guidé redemandait l'invite mot de passe à chaque étape
        élevée (chaque `WorkerRunner.start()` créait sa propre référence).
        Créée ici, au premier appel (jamais avant : ne jamais demander une
        permission avant qu'elle ne soit réellement nécessaire), puis
        réutilisée par tous les `WorkerRunner` suivants, expert comme
        assisté, jusqu'à la fermeture de l'application (`closeEvent`).

        Ne concerne que macOS packagé (`MacosAuthorizedProcess`,
        `elevate.py`) -- sur les autres chemins (macOS en développement,
        Linux, Windows), retourne `None` : `WorkerRunner`/`elevate.py` s'en
        accommodent déjà (comportement d'origine, une élévation par
        opération). Une session non créable (`OSError`, ex. Security.
        framework indisponible) retombe silencieusement sur ce même
        comportement d'origine plutôt que d'empêcher l'opération."""
        if platform.system() != "Darwin" or not getattr(sys, "frozen", False):
            return None
        if self._macos_auth_session is None:
            try:
                self._macos_auth_session = elevate.MacosAuthorizationSession()
            except OSError:
                return None
        return self._macos_auth_session

    def _mount_boot_privileged(self, device_path: str, mountpoint: str) -> bool:
        """Repli élevé installé auprès de `partitions/locate.py` (§4.4,
        cartes GPT/EFI) -- appelé uniquement quand le montage forcé non
        élevé a déjà échoué, jamais avant (même principe que
        `_get_or_create_macos_auth_session`, jamais d'invite tant qu'elle
        n'est pas réellement nécessaire). Sans session macOS packagée
        (développement, session non créable), `elevate.run_privileged_
        mount` retombe sur `osascript` avec sa propre autorisation
        ponctuelle -- `auth_ref=None` lui suffit, comme pour un
        `WorkerRunner` sans session partagée."""
        auth_session = self._get_or_create_macos_auth_session()
        auth_ref = auth_session.auth_ref if auth_session is not None else None
        return elevate.run_privileged_mount(device_path, mountpoint, auth_ref=auth_ref)

    def closeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        if self._macos_auth_session is not None:
            self._macos_auth_session.close()
        super().closeEvent(event)

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
        if self._mode == "backup_system":
            return f"Le système de {self._device.display} a été sauvegardé dans {self._file_path}."
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
        self._assisted_landing.set_busy(False)
        if self._console_stage is not None:
            self._console_stage.resume()
        if self._wizard_active:
            # Mode assisté (§5 mode assisté) : la suite (avancer/erreur)
            # est décidée par `WizardFlow`, pas par le mode expert
            # ci-dessous -- `_on_worker_finished` reste le seul point
            # d'arrivée des runners (`_start_worker`), réutilisé tel quel.
            self._on_wizard_job_finished(ok)
            return
        if self._assisted_ad_hoc_active:
            # Sauvegarde système depuis l'accueil assisté (§4.3), puis
            # éventuellement le flash qui la réutilise -- même point
            # d'arrivée que le mode expert ci-dessous, mais propose
            # toujours une suite explicite plutôt que de laisser
            # l'utilisateur sans issue (défaut de parcours signalé).
            self._on_assisted_ad_hoc_worker_finished(ok)
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

    def _on_assisted_ad_hoc_worker_finished(self, ok: bool) -> None:
        """Point d'arrivée dédié à la sauvegarde système lancée depuis
        l'accueil assisté (§4.3) et, le cas échéant, au flash qui la
        réutilise -- distinct de la version mode expert ci-dessus pour
        toujours proposer une suite sur `_wizard_panel`
        (`show_next_step_choice`) plutôt que de laisser l'utilisateur sur
        un écran sans issue une fois l'opération terminée (défaut de
        parcours signalé -- correctif). `_home` n'étant jamais visible ici,
        pas de `_refresh_home_state()`."""
        if ok:
            allow_eject = self._mode in _ALLOW_EJECT_AFTER_MODES
            reveal_path = self._file_path if self._mode in (_EXTRACTION_MODES | _INJECTION_MODES) else None
            self._log_panel.finish_success(self._success_message(), allow_eject=allow_eject, reveal_path=reveal_path)
        else:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=self._last_error_msg or "")

        if self._mode == "backup_system":
            self._wizard_panel.show_next_step_choice(
                tr("assisted_backup_system_done_title"),
                tr("assisted_backup_system_done_instruction"),
                show_prepare_card=ok,
            )
        else:
            # Étape « Préparer une carte » (flash) : plus rien à proposer
            # que revenir à l'accueil, succès ou échec.
            self._wizard_panel.show_next_step_choice(
                tr("assisted_prepare_card_done_title"),
                tr("assisted_prepare_card_done_instruction"),
                show_prepare_card=False,
            )

    def _on_prepare_card_requested(self) -> None:
        """« Préparer une carte avec cette sauvegarde » (§4.3) -- réutilise
        le fichier fraîchement créé comme source du flash, toujours dans
        le contexte assisté (jamais l'écran expert) : seule la carte
        cible reste à choisir. Bug corrigé, constaté en conditions
        réelles : la première version ouvrait directement la fenêtre
        modale Choix de la carte, sans jamais démarrer le moindre sondage
        -- aucun bandeau de détection (contrairement aux étapes 1/4 du
        vrai parcours guidé), bouton Continuer affiché mais jamais câblé à
        rien. Démarre désormais le même sondage automatique
        (`_prepare_card_poll_timer`/`_on_prepare_card_poll`) que les
        étapes 1/4, avec le même bandeau de détection -- `_device_dialog`
        ne sert plus que de repli pour plusieurs cartes candidates
        (`_skip_file_dialog_for_flash`, consommé par `_on_device_chosen`
        dans ce cas précis), puis la fenêtre Confirmation habituelle
        (§2 n°6, jamais sautée)."""
        backup_path = self._file_path
        self._mode = "flash"
        self._device = None
        self._file_path = backup_path
        self._skip_file_dialog_for_flash = True
        self._prepare_card_candidate = None
        self._wizard_panel.show_step(
            tr("assisted_prepare_card_choose_device_title"),
            tr("assisted_prepare_card_choose_device_instruction"),
            can_continue=False,
            show_refresh=True,
        )
        self._prepare_card_poll_timer.start()
        self._on_prepare_card_poll()

    def _on_prepare_card_poll(self) -> None:
        """Sondage automatique de la carte cible pour « Préparer une carte
        avec cette sauvegarde » (§4.3) -- même principe que
        `_on_wizard_poll` (étapes 1/4 : bandeau de détection, Continuer
        activé seulement une fois une carte trouvée), mais jamais
        `self._wizard_flow`/`_on_wizard_poll` lui-même : ce parcours
        ponctuel n'est pas un vrai `WizardJob`, le réutiliser corromprait
        l'état du vrai parcours guidé. Pas de vérification d'empreinte
        contrairement à l'étape 4 (rien à comparer : aucune « carte
        source » n'est suivie dans ce parcours ponctuel)."""
        devices, rejected_lines = self._list_devices_with_diagnostics()
        self._log_wizard_detection_diagnostic(len(devices), rejected_lines)

        if len(devices) > 1:
            # Plusieurs cartes candidates (§4.2) -- même repli que
            # `_on_wizard_poll` : la fenêtre Choix de la carte plutôt que
            # de deviner laquelle préparer.
            self._prepare_card_poll_timer.stop()
            self._wizard_panel.set_status(tr("wizard_status_multiple_candidates"))
            self._device_dialog.set_devices(devices)
            self._device_dialog.open()
            return

        if not devices:
            self._wizard_panel.set_status(tr("wizard_status_waiting"))
            self._wizard_panel.set_can_continue(False)
            return

        self._prepare_card_poll_timer.stop()
        device = devices[0]
        self._prepare_card_candidate = device
        self._wizard_panel.set_status(tr("wizard_status_device_found", display=device.display))
        self._wizard_panel.set_can_continue(True)

    def _on_assisted_ad_hoc_return_home(self) -> None:
        """« Revenir à l'accueil », proposé après la sauvegarde système
        (ou la préparation de carte qui la réutilise) -- jamais un
        changement de mode persisté (§4.3), même principe que
        `_start_backup_system_from_assisted_landing`."""
        if self._prepare_card_poll_timer.isActive():
            self._prepare_card_poll_timer.stop()
        self._prepare_card_candidate = None
        self._assisted_ad_hoc_active = False
        self._log_panel.set_idle()
        self._root_stack.setCurrentWidget(self._assisted_landing)

    def _on_reveal_requested(self, path: str) -> None:
        try:
            reveal(path)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))

    def _on_releases_requested(self, firmware: str) -> None:
        """Bouton « Voir les versions disponibles » de `FileDialog` (flash
        uniquement -- ROCKNIX a son propre téléchargement automatique,
        `_on_rocknix_download_requested`, et n'utilise jamais ce chemin).
        Catalogue-driven (`identify/firmware_catalog.py::FIRMWARE_BY_ID`)
        plutôt qu'un ternaire à deux choix codé en dur -- l'ancienne forme
        retombait silencieusement sur l'URL ArkOS pour tout id non
        reconnu, un bug qui ne peut plus se produire ici : un id absent du
        catalogue, ou une entrée à téléchargement automatique (ROCKNIX),
        n'ouvre rien plutôt que la mauvaise page. `firmware` est celui
        réellement sélectionné à l'instant du clic
        (`FileDialog._firmware`), pas une copie mémorisée séparément qui
        pourrait être périmée juste après une présélection programmatique
        (§4.6)."""
        entry = FIRMWARE_BY_ID.get(firmware)
        if entry is None or entry.releases_url is None:
            return
        try:
            webbrowser.open(entry.releases_url)
        except Exception as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))

    def _on_firmware_changed(self, firmware: str) -> None:
        """Choix de firmware (`FileDialog`, flash uniquement, §4.6) --
        mémorisé comme `ui_mode` (`config.py`), pour ne pas reproposer
        le même choix par défaut au prochain flash."""
        self._app_config.firmware = firmware
        app_config.save_config(self._app_config)

    def _on_rocknix_download_requested(self) -> None:
        """Bouton « Télécharger la dernière version » de `FileDialog`
        (flash, firmware ROCKNIX uniquement) -- contrairement à dArkOS
        (`_on_releases_requested` ci-dessus), les images ROCKNIX sont
        attachées directement aux releases GitHub (`identify/rocknix.py`).
        Une vraie release peut en publier plusieurs variantes à la fois
        (ex. `-a`/`-b`, CLAUDE.md) : recherche d'abord ce qui est
        disponible (`_on_rocknix_list_finished` ouvre ensuite
        `RocknixVariantDialog` pour que l'utilisateur choisisse) plutôt
        que de télécharger directement."""
        self._file_dialog.close()
        self._log_panel.start_operation(tr("execute_title_list_rocknix"))
        self._home.set_busy(True)
        self._assisted_landing.set_busy(True)
        if self._console_stage is not None:
            self._console_stage.pause()
        self._last_error_code = None
        self._last_error_msg = None
        self._runner = RocknixListRunner(parent=self)
        self._runner.error.connect(self._on_worker_error)
        self._runner.finished_list.connect(self._on_rocknix_list_finished)
        self._runner.start()

    def _on_rocknix_list_finished(self, variants) -> None:
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        if self._console_stage is not None:
            self._console_stage.resume()
        if not variants:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=self._last_error_msg or "")
            return
        self._log_panel.set_idle()
        self._rocknix_variant_dialog.set_variants(variants)
        self._rocknix_variant_dialog.open()

    def _on_rocknix_variant_chosen(self, asset, expected_sha256) -> None:
        """Variante choisie dans `RocknixVariantDialog` -- démarre le
        téléchargement proprement dit, avec progression réelle dans le
        journal de bord comme n'importe quelle autre opération longue
        (§5)."""
        self._rocknix_variant_dialog.close()
        self._log_panel.start_operation(tr("execute_title_download_rocknix"))
        self._home.set_busy(True)
        self._assisted_landing.set_busy(True)
        if self._console_stage is not None:
            self._console_stage.pause()
        self._last_error_code = None
        self._last_error_msg = None
        self._runner = RocknixDownloadRunner(asset, expected_sha256, parent=self)
        self._runner.progress.connect(self._on_progress)
        self._runner.error.connect(self._on_worker_error)
        self._runner.finished_download.connect(self._on_rocknix_download_finished)
        self._runner.start()

    @Slot(bool, str)
    def _on_rocknix_download_finished(self, ok: bool, path: str) -> None:
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        if self._console_stage is not None:
            self._console_stage.resume()
        if not ok:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=self._last_error_msg or "")
            return
        # Pas d'éjection proposée ici (`allow_eject=False`) : le
        # téléchargement n'a encore rien écrit sur la carte -- seule la
        # fenêtre Confirmation qui suit, puis le flash lui-même,
        # écriront réellement (règle §2 n°6).
        self._log_panel.finish_success(tr("rocknix_download_success", path=path), allow_eject=False, reveal_path=path)
        self._file_path = path
        self._confirm_dialog.set_device(self._device)
        self._confirm_dialog.open()

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

    # --- écran de bienvenue macOS (§3) ---------------------------------------

    def _on_fda_recheck_requested(self) -> None:
        """Bouton « J'ai terminé » de `FullDiskAccessScreen` -- revérifie
        l'autorisation. Détectée : passe à l'accueil habituel, cet écran ne
        réapparaît plus (jusqu'à la prochaine fois où l'autorisation
        manquera, ex. après une mise à jour, §3). Toujours absente : jamais
        un clic silencieusement ignoré (§5), le message dédié s'affiche."""
        if elevate.has_full_disk_access():
            self._fda_screen.set_still_not_detected(False)
            self._show_startup_screen()
        else:
            self._fda_screen.set_still_not_detected(True)

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

    def _start_backup_system_from_assisted_landing(self) -> None:
        """Bouton « Sauvegarder mon système sans les jeux » de l'accueil
        assisté (§4.3) -- réutilise `MainView`/`_log_panel` le temps de
        l'opération, pour bénéficier du journal de bord et des états
        occupé déjà en place, sans en faire un vrai changement de mode :
        contrairement à `_switch_to_expert_mode`, `ui_mode` n'est jamais
        modifié ni persisté ici. Reste dans l'habillage assisté
        (`WizardStepPanel`), jamais l'écran expert (`HomeScreen`) --
        correctif d'un défaut de parcours signalé : la version précédente
        montrait l'écran expert pendant l'opération et n'offrait ensuite
        aucune suite. `_on_worker_finished` consulte
        `_assisted_ad_hoc_active` pour proposer explicitement la suite
        (`WizardStepPanel.show_next_step_choice`) plutôt que de laisser
        l'utilisateur sans issue une fois l'opération terminée."""
        self._assisted_ad_hoc_active = True
        self._main_view.show_wizard_panel()
        self._wizard_panel.show_step(
            tr("assisted_backup_system_running_title"),
            tr("assisted_backup_system_running_instruction"),
            can_continue=False,
        )
        self._root_stack.setCurrentWidget(self._main_view)
        self._start_flow("backup_system")

    def _switch_to_assisted_mode(self) -> None:
        """Bouton « Mode assisté », symétrique de `_switch_to_expert_mode`
        -- sans lui, basculer en mode expert était un aller simple :
        `ui_mode` étant persisté (`config.py`), rien ne permettait de
        revenir au mode assisté, même après redémarrage. Ramène à
        l'accueil (pas à un parcours en cours : le mode expert n'a pas de
        notion de parcours guidé à reprendre)."""
        self._app_config.ui_mode = "assisted"
        app_config.save_config(self._app_config)
        self._root_stack.setCurrentWidget(self._assisted_landing)

    def _start_wizard(self) -> None:
        self._app_config.ui_mode = "assisted"
        app_config.save_config(self._app_config)
        self._wizard_flow.reset()
        self._wizard_active = True
        self._wizard_source_device = None
        self._wizard_source_fingerprint = None
        self._wizard_target_device = None
        self._wizard_backup_kind = None
        self._wizard_estimated_backup_bytes = None
        self._wizard_last_poll_diagnostic = None
        self._log_panel.set_idle()
        self._main_view.show_wizard_panel()
        self._root_stack.setCurrentWidget(self._main_view)
        self._enter_wizard_job(self._wizard_flow.current_job())

    def _cancel_wizard(self) -> None:
        """Annule le job en cours s'il y en a un, puis retour direct à
        l'accueil assisté (§5) -- aucune opération déjà terminée n'est
        défaite, seul le parcours guidé s'arrête. Câblé au même bouton
        Annuler du `WizardStepPanel` que la sauvegarde système lancée
        depuis l'accueil assisté (§4.3, `show_step` pendant l'opération et
        pendant le sondage de « Préparer une carte ») : fonctionne
        correctement dans les deux cas, `self._runner` étant le même
        mécanisme sous-jacent quel que soit le contexte."""
        if self._wizard_poll_timer.isActive():
            self._wizard_poll_timer.stop()
        if self._prepare_card_poll_timer.isActive():
            self._prepare_card_poll_timer.stop()
        self._prepare_card_candidate = None
        if self._runner is not None:
            self._runner.cancel()
        self._wizard_active = False
        self._assisted_ad_hoc_active = False
        self._root_stack.setCurrentWidget(self._assisted_landing)

    def _enter_wizard_job(self, job: Optional[WizardJob]) -> None:
        if job is None:
            self._finish_wizard()
            return

        if job == WizardJob.DETECT_TARGET:
            # La carte source reste montée pendant l'étape 2 (c'est de là
            # que l'image est lue) : ce n'est qu'en tout début de l'étape 3
            # qu'elle n'a plus d'usage et doit être éjectée, avant même
            # d'inviter à la retirer (`_run_wizard_source_eject`).
            self._run_wizard_source_eject()
            return

        title_key, instruction_key = _WIZARD_STEP_STRINGS[job]
        is_detect_step = job == WizardJob.DETECT_SOURCE
        self._wizard_panel.show_step(
            tr(title_key), tr(instruction_key), can_continue=False, show_refresh=is_detect_step
        )

        if is_detect_step:
            self._wizard_panel.set_status(tr("wizard_status_waiting"))
            self._wizard_poll_timer.start()
        elif job == WizardJob.CREATE_IMAGE:
            self._enter_wizard_create_image_step()
        elif job == WizardJob.RESTORE_IMAGE:
            self._enter_wizard_restore_image_step()
        elif job == WizardJob.EJECT:
            self._run_wizard_eject()

    def _run_wizard_source_eject(self) -> None:
        """Démonte et éjecte la carte source avant d'afficher la consigne
        d'insertion de la carte neuve (étape 3) -- la retirer alors
        qu'elle est encore montée risquerait de corrompre des données et
        déclenche un avertissement système. Le job DETECT_TARGET n'est
        jamais marqué fait ici : un échec (volume occupé, partition
        verrouillée) laisse `current_job()` sur DETECT_TARGET, donc
        Reprendre (`_resume_wizard`) relance cette même éjection plutôt
        que de laisser l'utilisateur retirer la carte sans savoir si
        c'est sûr. Le sondage de la carte neuve (`_wizard_poll_timer`) ne
        démarre qu'une fois l'éjection effectivement réussie, pour ne
        jamais détecter la carte source comme si c'était la neuve."""
        title_key, instruction_key = _WIZARD_STEP_STRINGS[WizardJob.DETECT_TARGET]
        self._wizard_panel.show_step(tr(title_key), tr("wizard_ejecting_source"), can_continue=False)
        self._log_panel.append_log(tr("wizard_ejecting_source"))
        try:
            eject_device(self._wizard_source_device.path)
        except Exception as exc:
            self._last_error_code = "EJECT_FAILED"
            self._last_error_msg = str(exc)
            self._log_panel.finish_error(friendly_error_message("EJECT_FAILED"), details=str(exc))
            self._wizard_panel.show_error()
            return
        self._log_panel.append_log(tr("wizard_source_ejected"))
        self._wizard_panel.show_step(tr(title_key), tr(instruction_key), can_continue=False, show_refresh=True)
        self._wizard_panel.set_status(tr("wizard_status_waiting"))
        self._wizard_poll_timer.start()

    def _enter_wizard_create_image_step(self) -> None:
        """Étape 2 (§5 mode assisté, parcours de clonage) : demande d'abord
        quoi sauvegarder (`BackupKindDialog`) avant de lancer quoi que ce
        soit -- même principe que l'ancien `ArchiveReuseDialog`, un job
        peut afficher un choix intermédiaire avant de démarrer un worker."""
        self._backup_kind_dialog.open()

    def _on_backup_kind_chosen(self, kind: str) -> None:
        """Réponse de `BackupKindDialog` -- "full" (copie complète, `backup
        --device`) ou "system" (système seul, `backup --device --system-
        only`, réutilise le pipeline d'estimation existant, inchangé). Les
        deux mènent à `FileDialog` pour choisir où enregistrer l'image,
        exactement comme aujourd'hui pour ces deux modes."""
        self._backup_kind_dialog.close()
        self._wizard_backup_kind = kind
        self._device = self._wizard_source_device
        if kind == "full":
            self._mode = "backup"
            # Majorant sûr, sans lecture supplémentaire : `backup_device`
            # ne dépasse jamais la taille du périphérique source (il
            # s'arrête à la fin de la dernière partition utilisée).
            self._wizard_estimated_backup_bytes = self._device.size_bytes
            self._log_panel.append_log(
                tr("wizard_create_image_size_hint", size=_format_size(self._device.size_bytes))
            )
            self._file_dialog.set_mode("backup")
            self._file_dialog.open()
        else:
            self._mode = "backup_system"
            self._wizard_estimated_backup_bytes = None  # renseigné par l'estimation ci-dessous
            self._start_system_backup_estimate(self._device)

    def _on_wizard_continue(self) -> None:
        """Continuer ne concerne que l'étape de détection (`DETECT_SOURCE`)
        -- toutes les autres étapes du parcours de clonage avancent
        d'elles-mêmes via `_on_wizard_job_finished` ou leurs propres
        boutons dédiés (`BackupKindDialog`).

        « Préparer une carte avec cette sauvegarde » (§4.3) partage ce
        même bouton/signal -- vérifié en tout premier, jamais
        `self._wizard_flow` pour ce cas précis (ce parcours ponctuel n'est
        pas un vrai `WizardJob`, y toucher corromprait le vrai parcours
        guidé)."""
        if self._prepare_card_candidate is not None:
            device = self._prepare_card_candidate
            self._prepare_card_candidate = None
            self._device = device
            self._proceed_to_flash_confirmation()
            return
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
        self._log_panel.finish_success(tr("wizard_finished"), allow_eject=False, reveal_path=None)
        self._wizard_panel.show_step(tr("wizard_step5_title"), tr("wizard_finished"), can_continue=False)
        self._refresh_home_state()

    # --- étapes 1/4 : détection, avec garde-fou d'empreinte à l'étape 4 -----

    def _on_wizard_poll(self) -> None:
        devices, rejected_lines = self._list_devices_with_diagnostics()
        self._log_wizard_detection_diagnostic(len(devices), rejected_lines)

        if len(devices) > 1:
            # Plusieurs cartes candidates (ex. un disque USB qui passe le
            # filtre en plus de la carte SD, §4.2) : avant ce correctif,
            # `candidate` retombait à `None`, indiscernable de « aucune
            # carte » -- proposer un choix plutôt que de rester bloqué en
            # silence, comme le mode expert le fait déjà via cette même
            # fenêtre.
            self._wizard_poll_timer.stop()
            self._wizard_panel.set_status(tr("wizard_status_multiple_candidates"))
            self._device_dialog.set_devices(devices)
            self._device_dialog.open()
            return

        if not devices:
            self._wizard_panel.set_status(tr("wizard_status_waiting"))
            self._wizard_panel.set_can_continue(False)
            return

        self._start_wizard_fingerprint_check(devices[0])

    def _log_wizard_detection_diagnostic(self, accepted_count: int, rejected_lines: List[str]) -> None:
        """Combien de cartes retenues et lesquelles écartées, avec la
        raison (§5 mode assisté) -- diagnosticable directement dans le
        journal plutôt que de laisser deviner un écart apparent avec le
        mode expert (qui appelle exactement la même détection,
        `_list_devices_with_diagnostics`). Ne journalise que si l'état
        diffère du dernier sondage, pour ne pas noyer le journal d'une
        ligne toutes les 1,5 s en attendant une carte."""
        signature = (accepted_count, tuple(rejected_lines))
        if signature == self._wizard_last_poll_diagnostic:
            return
        self._wizard_last_poll_diagnostic = signature
        if accepted_count == 1 and not rejected_lines:
            return  # cas normal, rien à signaler
        self._log_panel.append_log(
            tr("wizard_diagnostic_summary", accepted=accepted_count, rejected=len(rejected_lines))
        )
        for line in rejected_lines:
            self._log_panel.append_log(f"  — {line}")

    def _start_wizard_fingerprint_check(self, candidate: Device) -> None:
        # L'empreinte peut monter BOOT et bloquer jusqu'à
        # MOUNT_WAIT_SECONDS (§4.4) -- calculée sur un thread séparé
        # (`WizardFingerprintRunner`), jamais ici sur le thread Qt
        # principal (un gel de l'interface pendant ce montage se lit
        # comme un plantage, constaté en usage réel). Le sondage s'arrête
        # pendant ce calcul, pour ne pas en démarrer un deuxième en
        # parallèle au tick suivant -- `_on_wizard_fingerprint_ready` le
        # relance lui-même si la carte détectée à l'étape 4 s'avère être
        # la même qu'à l'étape 1.
        self._wizard_poll_timer.stop()
        self._wizard_panel.set_can_continue(False)
        job = self._wizard_flow.current_job()
        self._fingerprint_runner = WizardFingerprintRunner(candidate.path, parent=self)
        self._fingerprint_runner.finished_fingerprint.connect(
            lambda fingerprint: self._on_wizard_fingerprint_ready(job, candidate, fingerprint)
        )
        self._fingerprint_runner.start()

    def _on_wizard_refresh_requested(self) -> None:
        """Bouton Rafraîchir (étapes 1/4, §5 mode assisté, et « Préparer
        une carte avec cette sauvegarde », §4.3) -- relance la recherche
        manuellement, sans attendre le prochain tick (jusqu'à 1,5 s),
        utile quand le sondage automatique n'a rien trouvé ou reste
        bloqué après un choix annulé dans la fenêtre Choix de la carte
        (plusieurs candidates). `self._assisted_ad_hoc_active` route vers
        le bon sondage -- jamais `_on_wizard_poll` (qui opère sur
        `self._wizard_flow`, sans rapport avec ce parcours ponctuel) pour
        « Préparer une carte »."""
        if self._assisted_ad_hoc_active:
            if not self._prepare_card_poll_timer.isActive():
                self._prepare_card_poll_timer.start()
            self._on_prepare_card_poll()
            return
        if not self._wizard_poll_timer.isActive():
            self._wizard_poll_timer.start()
        self._on_wizard_poll()

    def _on_wizard_fingerprint_ready(
        self, job: WizardJob, candidate: Device, fingerprint: Optional[str]
    ) -> None:
        if job == WizardJob.DETECT_SOURCE:
            self._wizard_poll_timer.stop()  # trouvé -> plus besoin de reinterroger
            self._wizard_source_device = candidate
            self._wizard_source_fingerprint = fingerprint
            self._wizard_panel.set_status(tr("wizard_status_device_found", display=candidate.display))
            self._wizard_panel.set_can_continue(True)
        elif job == WizardJob.DETECT_TARGET:
            if is_same_card(self._wizard_source_fingerprint, fingerprint):
                self._wizard_panel.set_status(tr("wizard_status_same_card"))
                self._wizard_panel.set_can_continue(False)
                self._wizard_poll_timer.start()  # continue d'attendre une vraie carte différente
                return
            self._wizard_poll_timer.stop()
            self._wizard_target_device = candidate
            self._wizard_panel.set_status(tr("wizard_status_device_found", display=candidate.display))
            self._wizard_panel.set_can_continue(True)

    # --- étape 4 : restauration de l'image sur la carte neuve ---------------

    def _enter_wizard_restore_image_step(self) -> None:
        """Étape 4 (§5 mode assisté, parcours de clonage) : restaure
        directement l'image créée à l'étape 2 (`self._file_path`) sur la
        carte neuve -- aucun choix de firmware ici, contrairement au flash
        du mode expert : ce n'est pas une nouvelle image téléchargée, c'est
        la propre sauvegarde de l'utilisateur qu'on réinstalle telle
        quelle. Vérification de taille avant toute écriture (§ pré-vol) :
        une carte plus petite que l'image tronquerait la table GPT
        secondaire (déjà rencontré) -- `estimate_total_bytes` est exacte et
        non privilégiée pour `.img`/`.img.gz`/`.img.xz` (lue depuis le pied
        du fichier, sans décompression) ; `None` seulement pour un pied
        tronqué/non standard, cas résiduel où le blocage est laissé au
        worker élevé (`flash_device` échoue alors avec une vraie erreur
        d'écriture plutôt que de tronquer silencieusement)."""
        self._mode = "flash"
        self._device = self._wizard_target_device
        total_hint = estimate_total_bytes(self._file_path)
        if total_hint is not None and total_hint > self._device.size_bytes:
            self._last_error_code = "DESTINATION_TOO_SMALL"
            self._last_error_msg = f"{total_hint} > {self._device.size_bytes}"
            self._log_panel.finish_error(
                friendly_error_message("DESTINATION_TOO_SMALL"), details=self._last_error_msg
            )
            self._wizard_panel.show_error()
            return
        self._confirm_dialog.set_device(self._device)
        self._confirm_dialog.open()

    def _on_wizard_job_finished(self, ok: bool) -> None:
        job = self._wizard_flow.current_job()
        if not ok:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=self._last_error_msg or "")
            self._wizard_panel.show_error()
            return

        if job == WizardJob.CREATE_IMAGE:
            self._log_panel.append_log(tr("wizard_image_created_log", path=self._file_path))

        self._log_panel.finish_success(self._success_message(), allow_eject=False, reveal_path=None)

        self._wizard_flow.mark_done(job)
        self._enter_wizard_job(self._wizard_flow.current_job())

    # --- étape 5 : éjection, synchrone comme _perform_eject ------------------

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
