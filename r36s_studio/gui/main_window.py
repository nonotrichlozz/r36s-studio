# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

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

import os
import platform
import re
import shutil
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtCore import QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QMainWindow, QMessageBox, QStackedWidget

from r36s_studio import config as app_config
from r36s_studio import update_check
from r36s_studio.android import adb as android_adb
from r36s_studio.android import emulators as android_emulators
from r36s_studio.android import platform_tools as android_platform_tools
from r36s_studio.android.models import DetectionResult
from r36s_studio.consoles_diverses import settings_store as consoles_diverses_settings_store
from r36s_studio.consoles_diverses.client import ResultatRecherche
from r36s_studio.consoles_diverses.screen import ConsolesDiversesScreen
from r36s_studio.consoles_diverses.search_runner import ConsoleSearchRunner
from r36s_studio.consoles_diverses.settings_dialog import ConsolesDiversesSettingsDialog
from r36s_studio.consoles_diverses.strings import friendly_error_message as consoles_diverses_friendly_error_message
from r36s_studio.detect import detect_workflow_status
from r36s_studio.devices import Device, list_devices
from r36s_studio.doublons import scan_cache as doublons_scan_cache
from r36s_studio.doublons.move import (
    DestinationInsideRootNotAllowed,
    DestinationIsFilesystemRoot,
    DestinationNotWritable,
    check_destination_allowed,
    default_destination as default_doublons_destination,
    destination_filesystem_kind,
    fat_oversized_members,
    free_space_at_destination,
    has_pending_journal_entries,
    is_cross_volume_destination,
    is_fat_filesystem,
)
from r36s_studio.doublons.report import build_report
from r36s_studio.doublons.safety import is_filesystem_root, is_whole_user_folder
from r36s_studio.doublons.scan import Unit
from r36s_studio.identify import IdentifyResult
from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID
from r36s_studio.imaging import (
    DEFAULT_RESET_LABEL,
    CardTooSmallForReset,
    SevenZipArchiveError,
    UnsupportedImageFormatError,
    check_fat32_feasible,
    check_image_format,
    estimate_total_bytes,
)
from r36s_studio.imaging import sf3000_clone
from r36s_studio.imaging.fat32 import Fat32VolumeTooSmall
from r36s_studio.partitions import BOOT_LABEL, EASYROMS_LABEL, archives, list_partitions, set_privileged_mount_hook
from r36s_studio.safety import SafetyConfig, describe_rejection, filter_devices
from r36s_studio.safety.card_fingerprint import is_same_card, size_proves_different_card

from . import elevate
from . import logs as gui_logs
from .android_runner import AndroidDetectRunner, AndroidPlatformToolsDownloadRunner, AndroidPlatformToolsSizeRunner
from .doublons_runner import DoublonsMoveRunner, DoublonsResumeRunner, DoublonsScanRunner, DoublonsUndoRunner
from .partition_runner import (
    IdentifyRunner,
    PartitionJobRunner,
    RocknixDownloadRunner,
    RocknixListRunner,
    SystemBackupEstimate,
    SystemBackupEstimateRunner,
    UpdateCheckRunner,
    WizardFingerprintRunner,
)
from .reveal import reveal
from .screens import (
    AboutDialog,
    AndroidScreen,
    AssistedLandingScreen,
    BackupKindDialog,
    ConfirmDialog,
    ConfirmMoveDoublonsDialog,
    ConfirmUndoDoublonsDialog,
    DeviceDialog,
    DoublonsFolderScreen,
    DoublonsMoveProgressScreen,
    DoublonsResultsScreen,
    DoublonsRiskConfirmDialog,
    DoublonsScanProgressScreen,
    FileDialog,
    FullDiskAccessScreen,
    HelpDialog,
    HomeScreen,
    IdentifyResultDialog,
    LogPanel,
    MainView,
    ResetCardLabelDialog,
    WholeCardChoiceDialog,
    RocknixVariantDialog,
    SameCardUnverifiedDialog,
    UpdateDialog,
    WizardStepPanel,
    _ASSISTED_CONTENT_SPACING,
    _ASSISTED_GRID_TOTAL_HEIGHT,
    _ASSISTED_GRID_TOTAL_WIDTH,
    _ASSISTED_PANEL_WIDTH,
    _OPERATION_TITLE_KEYS,
    _format_size,
    build_console_stage,
)
from .strings import (
    doublons_move_file_error_message,
    doublons_partial_move_message,
    error_log_detail,
    friendly_error_message,
    tr,
    tr_in,
)
from .tri_screen import TriScreen
from .wizard_flow import WizardFlow, WizardJob
from .worker_runner import WorkerRunner

_WIZARD_POLL_INTERVAL_MS = 1500
# Bug rapporté, non reproduit en isolation (voir _on_wizard_poll) : le
# sondage automatique de l'étape 1/4 semblerait parfois s'arrêter de
# lui-même après un retour à l'accueil puis un nouveau lancement du
# parcours, sans qu'aucun mécanisme de remise à zéro en défaut n'ait été
# trouvé en relisant `_start_wizard`/`_cancel_wizard` ni en le
# reproduisant par un test qui rejoue exactement ce scénario (démarrage,
# empreinte source prête, Continuer, annulation depuis `BackupKindDialog`,
# relance -- le minuteur redémarre et retrouve la carte correctement dans
# ce test). Seuil très au-dessus de l'intervalle normal (1,5 s) pour ne
# jamais confondre une latence normale de l'OS avec un arrêt réel du
# minuteur -- diagnostic ajouté en attendant une confirmation sur du vrai
# matériel, pas encore un correctif.
_WIZARD_POLL_STALL_THRESHOLD_SECONDS = 6.0

# `MainWindow.closeEvent` (§2, bug corrigé -- worker élevé orphelin à la
# fermeture) : délai laissé à l'annulation coopérative avant un arrêt forcé.
# Court délibérément -- jamais un blocage perceptible de la fermeture de
# l'app pour un worker qui ne répond pas, l'arrêt forcé (`force_kill`) reste
# le filet de sécurité qui compte vraiment.
_WORKER_SHUTDOWN_GRACE_SECONDS = 2.0

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
    # "reset_card" volontairement absent : § éjecte déjà automatiquement à
    # la fin (dernière étape suivie par la barre de progression, §4.3 bis)
    # -- un bouton en plus serait redondant, même principe qu'un flash
    # Android (`android_flash`, ci-dessous).
}
_PARTITION_JOB_MODES = {"extract_boot", "extract_easyroms", "inject_boot", "copy_games"}
_ARCHIVE_LABEL_BY_MODE = {
    "extract_boot": BOOT_LABEL,
    "extract_easyroms": EASYROMS_LABEL,
    "inject_boot": BOOT_LABEL,
    "copy_games": EASYROMS_LABEL,
}

# Mécanisme ad-hoc de l'accueil assisté (§5, refonte menu de tuiles) --
# `_start_assisted_ad_hoc_job` (titre/instruction affichés le temps de
# l'opération) et `_on_assisted_ad_hoc_worker_finished` (titre/instruction
# affichés une fois terminée, plus `show_prepare_card` : propose « Préparer
# une carte avec cette sauvegarde » uniquement après une vraie sauvegarde).
# Généralise l'ancien câblage en dur (`backup_system` et un `else` pensé
# pour `flash`) à tout job_key déclenchable depuis une tuile.
_ASSISTED_AD_HOC_RUNNING_STRINGS = {
    "backup": ("assisted_backup_running_title", "assisted_backup_running_instruction"),
    "backup_system": ("assisted_backup_system_running_title", "assisted_backup_system_running_instruction"),
    "flash": ("assisted_flash_running_title", "assisted_flash_running_instruction"),
    "copy_games": ("assisted_copy_games_running_title", "assisted_copy_games_running_instruction"),
    "reset_card": ("assisted_reset_card_running_title", "assisted_reset_card_running_instruction"),
    "eject": ("assisted_eject_running_title", "assisted_eject_running_instruction"),
}
_ASSISTED_AD_HOC_DONE_STRINGS = {
    "backup": ("assisted_backup_done_title", "assisted_backup_done_instruction", True),
    "backup_system": ("assisted_backup_system_done_title", "assisted_backup_system_done_instruction", True),
    "flash": ("assisted_prepare_card_done_title", "assisted_prepare_card_done_instruction", False),
    "copy_games": ("assisted_copy_games_done_title", "assisted_copy_games_done_instruction", False),
    "reset_card": ("assisted_reset_card_done_title", "assisted_reset_card_done_instruction", False),
    "eject": ("assisted_eject_done_title", "assisted_eject_done_instruction", False),
}


# Accueil assisté (§5, refonte menu de tuiles, correctif visuel) : la
# fenêtre doit toujours pouvoir afficher les trois rangées de la grille
# sans défiler (le `QScrollArea` de `AssistedLandingScreen` reste un
# filet de sécurité, pas le chemin normal), y compris sur un écran réel
# de 1366x768 -- barre de titre/tâches comprises, donc sans marge de
# confort inutile. `_ASSISTED_GRID_TOTAL_*`/`_ASSISTED_CONTENT_SPACING`/
# `_ASSISTED_PANEL_WIDTH` sont calculées une fois dans `screens.py`
# (taille/nombre de tuiles, gouttière, largeur du panneau), jamais
# dupliquées ici. Le supplément (96) correspond exactement à l'habillage
# resserré au-dessus de la grille dans `AssistedLandingScreen.__init__`
# (marges 10 haut/bas, en-tête, étiquette de section, gouttières) --
# mesuré directement sur l'écran construit, pas une estimation à la
# louche : un ancien supplément de 160 (jamais revérifié contre le
# contenu réel) ouvrait la fenêtre plus haute que nécessaire, plus haute
# même que l'écran de test 1366x768 une fois la barre de titre ajoutée --
# cause du bug signalé (dernière rangée coupée).
#
# Deuxième correctif (arithmétique, pas de réglage de marges) : même
# resserré, l'habillage ci-dessus plus trois rangées de tuiles à 200
# (`Tile.SIZE`, screens.py) ne tenait structurellement pas sur un écran
# réel 1366x728/768 -- 96 + 3*200 + 2*12 = 720, déjà supérieur à la zone
# client observée (~720-728). `Tile.SIZE` réduit à 160 (624 -> 504 pour
# `_ASSISTED_GRID_TOTAL_HEIGHT`, recalculé automatiquement ci-dessous) :
# 96 + 504 = 600, marge confortable cette fois. Le supplément de 96
# lui-même n'a pas changé -- lui n'a jamais été le problème, seule la
# taille des tuiles l'était.
_ASSISTED_MIN_WIDTH = _ASSISTED_GRID_TOTAL_WIDTH + _ASSISTED_CONTENT_SPACING + _ASSISTED_PANEL_WIDTH + 60
_ASSISTED_MIN_HEIGHT = _ASSISTED_GRID_TOTAL_HEIGHT + 96


def _android_catalog_search_url(server_url: str) -> str:
    """Même construction d'URL que `consoles_diverses/client.py::
    rechercher_console` (jamais réimportée : fonction privée de ce
    module-là) -- uniquement pour le diagnostic ci-dessous, ne remplace
    jamais l'URL réellement construite par le client lui-même."""
    return server_url.rstrip("/") + "/recherche"


def _journaliser_android_recherche(url: str, reference: str) -> None:
    """Diagnostic pour le signalement « Impossible de joindre le serveur
    depuis l'écran Console Android, alors que la recherche marche depuis
    Consoles diverses » -- les deux écrans utilisent pourtant exactement
    la même source de configuration (`consoles_diverses_settings_store.
    adresse_serveur()`/`AppConfig.consoles_diverses_licence_key`, voir `_on_
    android_search_catalog_requested` ci-dessous et le test dédié qui
    compare les deux chemins d'appel). Consigne l'URL réellement appelée,
    pour comparer d'une session à l'autre plutôt que de deviner --
    best-effort, un journal inaccessible ne doit jamais empêcher la
    recherche elle-même de continuer normalement."""
    try:
        chemin = gui_logs.android_log_path()
        horodatage = datetime.now().isoformat(timespec="seconds")
        with open(chemin, "a", encoding="utf-8") as fichier:
            fichier.write(f"{horodatage} recherche catalogue : url={url!r}, reference={reference!r}\n")
    except OSError:
        pass


def _journaliser_android_erreur_recherche(url: str, code: str, message: str) -> None:
    """Même journal que `_journaliser_android_recherche` ci-dessus, pour le
    code d'erreur reçu -- demandé explicitement (« journalise l'URL
    appelée et le code d'erreur »)."""
    try:
        chemin = gui_logs.android_log_path()
        horodatage = datetime.now().isoformat(timespec="seconds")
        with open(chemin, "a", encoding="utf-8") as fichier:
            fichier.write(
                f"{horodatage} erreur recherche catalogue : url={url!r}, code={code!r}, message={message!r}\n"
            )
    except OSError:
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("app_title"))
        # Le mode expert (deux colonnes, §5 refonte navigation) tient dans
        # 1120x690 (mesuré : `HomeScreen.minimumSizeHint().height()` vaut
        # 677) -- la taille minimale est désormais celle qui convient aux
        # deux modes, la plus grande des deux l'emportant ; plus le
        # plancher artificiel de 760 d'avant ce correctif, qui dépassait
        # déjà à lui seul un écran 1366x768 une fois la barre de titre
        # ajoutée, indépendamment du bug ci-dessus côté accueil assisté.
        min_width = max(1120, _ASSISTED_MIN_WIDTH)
        min_height = max(690, _ASSISTED_MIN_HEIGHT)
        self.setMinimumSize(min_width, min_height)
        self.resize(min_width, min_height)

        self._mode: Optional[str] = None
        self._device: Optional[Device] = None
        self._file_path: Optional[str] = None
        # Étiquette du volume pour « Remettre la carte à zéro » (§4.3 bis,
        # mode expert uniquement) -- choisie via `ResetCardLabelDialog`,
        # jamais utilisée en dehors de `self._mode == "reset_card"`.
        self._reset_card_label: str = DEFAULT_RESET_LABEL
        self._runner: Optional[object] = None  # WorkerRunner | PartitionJobRunner
        # Éjection (étape F/bouton du journal/automatique en mode assisté,
        # §4.4/§4.5) -- toujours un `WorkerRunner` dédié, distinct de
        # `self._runner` ci-dessus pour ne jamais interférer avec le
        # pipeline principal (`_start_worker`/`_on_worker_finished`, qui
        # décide de la suite selon `self._mode`) : bug corrigé, confirmé
        # sur du vrai matériel -- ouvrir `\\.\PhysicalDriveN` pour
        # `IOCTL_STORAGE_EJECT_MEDIA` exige l'élévation, exactement comme
        # l'écriture brute, mais l'éjection tournait jusqu'ici en
        # privilèges normaux dans le processus GUI (`ERROR_ACCESS_DENIED`).
        self._eject_runner: Optional[WorkerRunner] = None
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
        # « Utiliser toute la carte » pour une image SF3000 (`imaging/
        # sf3000_clone.py`) : choisi dans `WholeCardChoiceDialog` (mode
        # expert) ou automatiquement (mode assisté) -- remis à False avant
        # chaque flash, lu par `_start_worker`.
        self._whole_card = False
        self._whole_card_verify = True
        # Carte déjà signalée comme copie interrompue (une seule fois par carte).
        self._whole_card_marker_warned: Optional[str] = None
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
        # Système de fichiers pour « Remettre la carte à zéro » (§4.3 bis,
        # mode expert uniquement) -- mémorisé comme `firmware`/`ui_mode`,
        # choisi via `ResetCardLabelDialog`.
        self._reset_card_filesystem: str = self._app_config.reset_card_filesystem
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
        # Résultat de l'éjection de la carte source, chaînée dans le worker
        # de l'étape 2 (`backup --eject-after`, `_on_wizard_source_eject_
        # result`) -- `None` tant qu'aucun résultat n'est encore connu
        # (avant CREATE_IMAGE, ou si l'événement n'a jamais été reçu).
        # `_run_wizard_source_eject` s'en sert pour sauter un second worker
        # d'éjection dédié quand `True` (évite une invite UAC
        # supplémentaire dans le cas courant), et y retombe sur `False`/
        # `None` (échec de l'éjection chaînée, ou signal jamais reçu).
        self._wizard_source_ejected: Optional[bool] = None
        self._wizard_source_eject_error_msg: Optional[str] = None
        # Résultat de l'éjection chaînée dans un flash mode expert
        # (`flash --eject-after`, §4.6) -- même mécanisme que `_wizard_
        # source_ejected` ci-dessus, `None` tant qu'aucun résultat n'est
        # encore connu. `_on_worker_finished` ne masque le bouton Éjecter
        # de fin d'opération que si ce résultat confirme un succès, jamais
        # par défaut (bug corrigé, confirmé sur du vrai matériel : un échec
        # silencieux de cette éjection chaînée laissait la carte non
        # éjectée sans bouton visible pour réessayer, forçant à passer par
        # l'étape F séparée -- une invite UAC dédiée, minutes plus tard).
        self._flash_ejected: Optional[bool] = None
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
        # Horodatage du dernier sondage automatique réellement exécuté --
        # sert uniquement au diagnostic ci-dessus (`_on_wizard_poll`),
        # jamais à une logique métier.
        self._wizard_last_poll_monotonic: Optional[float] = None
        # Empêche `_check_wizard_poll_stall` de répéter la même ligne à
        # chaque tick tant qu'un même épisode de ralentissement persiste --
        # remis à `False` à chaque (re)démarrage réel du minuteur
        # (`_start_wizard_poll_timer`), donc dès qu'un sondage retrouve un
        # rythme normal.
        self._wizard_poll_stall_warned: bool = False
        # Carte détectée à l'étape 3 en attente de confirmation explicite
        # (`SameCardUnverifiedDialog`) -- ni son empreinte ni sa taille ne
        # prouvent qu'elle diffère de la carte source (§ pré-vol n°3).
        self._pending_target_candidate: Optional[Device] = None

        # Vue permanente, deux colonnes -- ne change plus jamais de
        # structure (§5, refonte navigation). `_home` (gauche, mode
        # expert) et `_wizard_panel` (gauche, mode assisté en cours)
        # partagent la même `MainView` -- un `QStackedWidget` interne
        # bascule entre les deux (`MainView.show_home`/
        # `show_wizard_panel`). `_log_panel` (droite, bas) reste unique et
        # partagé entre les deux modes ; `_console_stage` (droite, haut,
        # illustration de la console + terminal d'activité disque en
        # temps réel, §5) peut être `None` si l'image source est absente.
        # `_assisted_landing` a sa propre console, plus grande (§5 mode
        # assisté) -- MainView et AssistedLandingScreen ne sont jamais
        # affichés en même temps, donc pas de conflit de parent.
        self._home = HomeScreen()
        self._log_panel = LogPanel()
        self._console_stage = build_console_stage()
        self._wizard_panel = WizardStepPanel()
        self._main_view = MainView(self._home, self._console_stage, self._log_panel, wizard_panel=self._wizard_panel)
        self._assisted_landing = AssistedLandingScreen()
        # Tuile personnelle « Web » (config.py::personal_web_url) -- jamais
        # visible dans la version distribuée à un client : décidé une
        # seule fois ici, à la construction, à partir de la variable
        # d'environnement (stable pour toute la durée du processus,
        # jamais relue ensuite) -- les deux écrans ne lisent eux-mêmes ni
        # variable d'environnement ni config.
        web_tile_visible = app_config.personal_web_url() is not None
        self._home.set_web_tile_visible(web_tile_visible)
        # Écran de bienvenue macOS uniquement (§3) : construit
        # inconditionnellement (même principe que `_help_dialog`, dont le
        # bouton déclencheur n'apparaît lui aussi que sur macOS), mais
        # n'est choisi comme écran de démarrage que sur macOS sans Accès
        # complet au disque -- voir plus bas.
        self._fda_screen = FullDiskAccessScreen()
        # Section « Consoles diverses » (consoles_diverses/, étape 1) --
        # écran indépendant, isolé dans son propre package (règle
        # d'isolation, consoles_diverses/CLAUDE.md) : aucun rapport avec le
        # pipeline flash/backup/worker élevé ci-dessus, un simple appel
        # réseau en lecture. Construit une fois, comme les autres écrans.
        self._consoles_diverses_screen = ConsolesDiversesScreen()
        # Outil « Console Android » (android/, étape 1, docs/android-adb.md)
        # -- écran dédié, même principe que `_consoles_diverses_screen`
        # ci-dessus (pas un mode ad-hoc de `_main_view`) : détection en USB
        # via adb, indépendant du parcours carte SD, jamais d'élévation de
        # privilèges. Catalogue d'émulateurs local chargé une seule fois ici
        # -- best-effort, une erreur de packaging/données ne doit jamais
        # empêcher le reste de l'app de démarrer (même esprit que les
        # illustrations optionnelles, `asset_paths.py`).
        self._android_screen = AndroidScreen()
        try:
            self._android_screen.set_emulator_catalog(android_emulators.load_emulators())
        except (OSError, ValueError) as exc:
            print(f"[Android] Catalogue d'émulateurs indisponible : {exc}", file=sys.stderr)
        self._android_detect_runner: Optional[AndroidDetectRunner] = None
        # Outil « Ranger mes jeux » (docs/tri-roms.md) -- écran autonome qui
        # gère lui-même ses pages et ses threads : un seul point d'entrée ici.
        self._tri_screen = TriScreen()
        self._android_download_runner: Optional[AndroidPlatformToolsDownloadRunner] = None
        self._android_search_runner: Optional[ConsoleSearchRunner] = None
        # URL de la dernière recherche lancée depuis cet écran -- retenue
        # uniquement pour le diagnostic (`_journaliser_android_erreur_
        # recherche`, signal `error` du runner ne porte que code/message,
        # jamais l'URL elle-même).
        self._android_last_search_url: str = ""
        # Outil « Doublons de jeux » (docs/doublons.md, remplace l'ancien
        # flux carte-SD-uniquement de cette tuile) -- écrans autonomes,
        # même principe que `_consoles_diverses_screen` ci-dessus (pas un
        # mode ad-hoc de `_main_view`).
        self._doublons_folder_screen = DoublonsFolderScreen()
        self._doublons_scan_progress_screen = DoublonsScanProgressScreen()
        self._doublons_results_screen = DoublonsResultsScreen()
        self._doublons_move_progress_screen = DoublonsMoveProgressScreen()

        self._root_stack = QStackedWidget()
        self._root_stack.addWidget(self._assisted_landing)
        self._root_stack.addWidget(self._main_view)
        self._root_stack.addWidget(self._fda_screen)
        self._root_stack.addWidget(self._consoles_diverses_screen)
        self._root_stack.addWidget(self._android_screen)
        self._root_stack.addWidget(self._doublons_folder_screen)
        self._root_stack.addWidget(self._doublons_scan_progress_screen)
        self._root_stack.addWidget(self._doublons_results_screen)
        self._root_stack.addWidget(self._doublons_move_progress_screen)
        self._root_stack.addWidget(self._tri_screen)
        self.setCentralWidget(self._root_stack)

        # Fenêtres modales (§5, refonte navigation) : construites une fois,
        # ouvertes (`open()`, non bloquant) et fermées par `MainWindow` au
        # fil du parcours -- jamais un écran de remplacement.
        self._device_dialog = DeviceDialog(self)
        self._file_dialog = FileDialog(self)
        self._confirm_dialog = ConfirmDialog(self)
        self._help_dialog = HelpDialog(self)
        # Tuile Aide de l'accueil assisté sur Windows/Linux (§5, refonte
        # menu de tuiles) -- `_help_dialog` ci-dessus reste macOS (Accès
        # complet au disque, §3), sans rapport avec ces deux OS.
        self._about_dialog = AboutDialog(self)
        self._rocknix_variant_dialog = RocknixVariantDialog(self)
        self._backup_kind_dialog = BackupKindDialog(self)
        # Instance séparée pour la tuile 3 de l'accueil assisté (§5, refonte
        # menu de tuiles) -- `self._backup_kind_dialog` ci-dessus reste
        # câblé à `_on_backup_kind_chosen`/`_cancel_wizard`, tous deux
        # spécifiques au vrai parcours guidé (`self._wizard_source_device`,
        # `self._wizard_backup_kind`...) : partager la même instance ferait
        # tourner les deux jeux de gestionnaires à chaque clic, corrompant
        # l'un ou l'autre selon le contexte réellement actif.
        self._assisted_backup_kind_dialog = BackupKindDialog(self)
        # Tuile « Rechercher ma console » (§5, refonte menu de tuiles) --
        # instance dédiée de `DeviceDialog`, jamais `self._device_dialog`
        # (câblé à `_on_device_chosen`, le grand dispatcher qui suppose un
        # `self._mode` de flux normal/`_wizard_flow`/carte candidate ad-hoc
        # déjà en place -- même raison que `_assisted_backup_kind_dialog`
        # ci-dessus, une instance séparée par flux ponctuel plutôt qu'un
        # cas de plus dans ce dispatcher déjà chargé).
        self._identify_device_dialog = DeviceDialog(self)
        self._identify_result_dialog = IdentifyResultDialog(self)
        self._identify_runner: Optional[IdentifyRunner] = None
        # Outil « Doublons de jeux » -- deux instances de la même fenêtre
        # de confirmation, jamais une seule reconnectée dynamiquement
        # selon le contexte (source d'erreurs de câblage) : l'une pour la
        # confirmation avant analyse (racine de disque/dossier personnel
        # entier), l'autre dédiée au seuil des 200 000 fichiers rencontré
        # *pendant* l'analyse (doit débloquer le thread d'analyse même en
        # cas d'Annuler, contrairement à la première -- `cancelled`
        # câblée seulement ici).
        self._doublons_risk_confirm_dialog = DoublonsRiskConfirmDialog(self)
        self._doublons_large_folder_dialog = DoublonsRiskConfirmDialog(self)
        # Troisième réutilisation de cette même fenêtre (§ demandé
        # explicitement, point 4 : « proposer de continuer en ignorant ce
        # fichier ») -- titre propre (`set_title`), jamais celui par
        # défaut pensé pour une analyse à risque.
        self._doublons_file_error_dialog = DoublonsRiskConfirmDialog(self)
        self._confirm_move_doublons_dialog = ConfirmMoveDoublonsDialog(self)
        self._confirm_undo_doublons_dialog = ConfirmUndoDoublonsDialog(self)
        self._doublons_scan_runner: Optional[DoublonsScanRunner] = None
        self._doublons_move_runner: Optional[DoublonsMoveRunner] = None
        self._doublons_undo_runner: Optional[DoublonsUndoRunner] = None
        self._doublons_resume_runner: Optional[DoublonsResumeRunner] = None
        # Détails du dernier échec de déplacement (§ demandé explicitement,
        # points 1/3/4) -- lus dans `_on_doublons_move_error` (avant que
        # `_on_doublons_move_finished` ne remette `_doublons_move_runner`
        # à `None`), consommés dans `_on_doublons_move_finished` pour
        # retirer du résultat affiché ce qui a réellement bougé sans
        # jamais relancer une analyse, et construire un message précis.
        self._doublons_move_error_moved_units: List[Unit] = []
        self._doublons_move_error_file_failure = None
        self._doublons_move_error_skipped_count = 0
        # Dernier résultat en cache trouvé (§ demandé explicitement :
        # « ne jamais obliger à relancer une analyse ») -- rafraîchi à
        # chaque ouverture de l'écran de choix du dossier
        # (`_refresh_doublons_resume_button`), consommé par `_on_doublons_
        # resume_requested` sans jamais relire le disque une seconde fois
        # entre l'affichage du bouton et son clic.
        self._doublons_resume_cache: Optional[doublons_scan_cache.CachedScan] = None
        # Dossier sur lequel le scan en cours/le dernier scan a porté --
        # nécessaire pour relancer un déplacement puis un nouveau scan
        # sans redemander le dossier à chaque fois pendant cette session
        # de consultation de `_doublons_results_screen`.
        self._doublons_root: Optional[str] = None
        # Destination du déplacement pour la session en cours (signalé :
        # « permettre de choisir l'emplacement du dossier de destination »)
        # -- recalculée à chaque nouveau scan (`_on_doublons_scan_finished`),
        # jamais laissée à `None` tant qu'un dossier a été analysé.
        self._doublons_destination: Optional[str] = None
        self._doublons_scan_result = None
        self._pending_doublons_units: List[Unit] = []
        self._doublons_pending_risk_action = None
        self._same_card_unverified_dialog = SameCardUnverifiedDialog(self)
        self._reset_card_label_dialog = ResetCardLabelDialog(self)
        self._whole_card_dialog = WholeCardChoiceDialog(self)
        self._consoles_diverses_settings_dialog = ConsolesDiversesSettingsDialog(self)

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
        self._home.reset_card_selected.connect(lambda: self._start_flow("reset_card"))
        self._home.refresh_requested.connect(self._refresh_home_state)
        self._home.help_requested.connect(self._help_dialog.open)
        self._home.assisted_mode_requested.connect(self._switch_to_assisted_mode)
        self._home.consoles_diverses_requested.connect(self._open_consoles_diverses)
        self._home.android_requested.connect(self._open_android_screen)
        self._home.web_requested.connect(self._on_web_requested)
        # Accueil assisté (§5, refonte menu de tuiles) : plus de tuile «
        # Consoles diverses » séparée -- fusionnée dans « Identifier ma
        # console », l'accès au catalogue se fait depuis son écran de
        # résultat (`IdentifyResultDialog.catalog_requested`, câblé plus
        # bas avec les autres signaux de ce dialogue).
        self._consoles_diverses_screen.back_requested.connect(self._show_startup_screen)
        self._consoles_diverses_screen.settings_requested.connect(self._on_consoles_diverses_settings_requested)
        self._consoles_diverses_settings_dialog.settings_saved.connect(self._on_consoles_diverses_settings_saved)

        # Outil « Console Android » (android/, étape 1) -- même principe
        # que la section `consoles_diverses` ci-dessus : un écran
        # indépendant, jamais un mode ad-hoc de `_main_view`.
        self._android_screen.back_requested.connect(self._show_startup_screen)
        self._android_screen.refresh_requested.connect(self._start_android_detection)
        self._android_screen.consent_download_requested.connect(self._on_android_consent_download_requested)
        self._android_screen.cancel_download_requested.connect(self._on_android_cancel_download_requested)
        self._android_screen.search_catalog_requested.connect(self._on_android_search_catalog_requested)

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
        self._reset_card_label_dialog.label_chosen.connect(self._on_reset_card_label_chosen)
        self._whole_card_dialog.choice_made.connect(self._on_whole_card_chosen)

        self._confirm_dialog.confirmed.connect(self._on_confirmed)
        self._same_card_unverified_dialog.confirmed.connect(self._on_same_card_unverified_confirmed)

        self._log_panel.cancel_requested.connect(self._on_cancel_requested)
        self._log_panel.eject_requested.connect(self._on_eject_requested)
        self._log_panel.reveal_requested.connect(self._on_reveal_requested)

        self._assisted_landing.prepare_requested.connect(self._start_wizard)
        self._assisted_landing.expert_mode_requested.connect(self._switch_to_expert_mode)
        self._assisted_landing.refresh_requested.connect(self._refresh_home_state)
        self._assisted_landing.identify_requested.connect(self._start_assisted_identify)
        self._assisted_landing.backup_requested.connect(self._on_assisted_backup_tile_clicked)
        self._home.find_duplicates_requested.connect(self._start_doublons_tool)
        self._home.sort_games_requested.connect(self._open_tri_screen)
        self._home.language_selected.connect(self._on_language_selected)
        self._assisted_landing.language_selected.connect(self._on_language_selected)
        self._tri_screen.back_requested.connect(self._show_startup_screen)
        self._assisted_landing.eject_requested.connect(lambda: self._start_assisted_ad_hoc_job("eject"))
        self._assisted_landing.help_requested.connect(self._on_assisted_help_requested)
        self._assisted_backup_kind_dialog.full_copy_requested.connect(
            lambda: self._start_assisted_ad_hoc_job("backup")
        )
        self._assisted_backup_kind_dialog.system_only_requested.connect(
            lambda: self._start_assisted_ad_hoc_job("backup_system")
        )
        self._assisted_backup_kind_dialog.cancelled.connect(self._assisted_backup_kind_dialog.close)
        self._identify_device_dialog.device_chosen.connect(self._on_identify_device_chosen)
        self._identify_device_dialog.refresh_requested.connect(
            lambda: self._identify_device_dialog.set_devices(self._list_safe_devices())
        )
        # Tuile fusionnée « Identifier ma console » (§5, refonte menu de
        # tuiles) : accès au catalogue depuis l'écran de résultat.
        self._identify_result_dialog.catalog_requested.connect(self._open_consoles_diverses)

        self._doublons_folder_screen.back_requested.connect(self._show_startup_screen)
        self._doublons_folder_screen.refresh_requested.connect(self._refresh_doublons_shortcuts)
        self._doublons_folder_screen.folder_chosen.connect(self._on_doublons_folder_chosen)
        self._doublons_folder_screen.resume_requested.connect(self._on_doublons_resume_requested)
        self._doublons_risk_confirm_dialog.confirmed.connect(self._on_doublons_risk_confirmed)
        self._doublons_large_folder_dialog.confirmed.connect(self._on_doublons_large_folder_confirmed)
        self._doublons_large_folder_dialog.cancelled.connect(self._on_doublons_large_folder_cancelled)
        self._doublons_file_error_dialog.confirmed.connect(self._on_doublons_move_file_error_confirmed)
        self._doublons_file_error_dialog.cancelled.connect(self._on_doublons_move_file_error_cancelled)
        self._doublons_scan_progress_screen.cancel_requested.connect(self._on_doublons_scan_cancel_requested)
        self._doublons_results_screen.back_requested.connect(self._show_startup_screen)
        self._doublons_results_screen.move_requested.connect(self._on_doublons_move_requested)
        self._doublons_results_screen.export_requested.connect(self._on_doublons_export_requested)
        self._doublons_results_screen.undo_requested.connect(self._on_doublons_undo_requested)
        self._doublons_results_screen.destination_chosen.connect(self._on_doublons_destination_chosen)
        self._doublons_move_progress_screen.cancel_requested.connect(self._on_doublons_move_cancel_requested)
        self._confirm_move_doublons_dialog.confirmed.connect(self._on_doublons_move_confirmed)
        self._confirm_move_doublons_dialog.destination_chosen.connect(self._on_doublons_confirm_dialog_destination_chosen)
        self._confirm_undo_doublons_dialog.confirmed.connect(self._on_doublons_undo_confirmed)

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

        # (tag, notes) -- repris de config.json tant qu'APP_VERSION n'a pas
        # rattrapé la version mémorisée (badge persistant sans réseau).
        self._pending_update: Optional[tuple] = None
        if update_check.is_newer(self._app_config.latest_update_tag):
            self._pending_update = (self._app_config.latest_update_tag, self._app_config.latest_update_notes)
        for controls in (self._home.update_controls, self._assisted_landing.update_controls):
            controls.set_checked(self._app_config.check_updates)
            controls.check_toggled.connect(self._on_update_check_toggled)
            controls.badge_clicked.connect(self._open_update_dialog)
        self._show_update_badge_if_idle()

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
        status = detect_workflow_status(device)
        self._warn_if_interrupted_whole_card_copy(device)
        self._home.set_status(status, device, has_device=bool(devices))
        # Accueil assisté (§5, refonte menu de tuiles) : même dict déjà
        # calculé ci-dessus, un second récepteur -- jamais une seconde
        # détection dupliquée.
        self._assisted_landing.set_status(status, device, has_device=bool(devices))

    def _warn_if_interrupted_whole_card_copy(self, device: Optional[Device]) -> None:
        """Fichier témoin de `clone-sf3000` resté à la racine de la carte :
        la copie a été interrompue, la carte est incomplète -- dit une fois
        par carte dans le journal (lecture d'un fichier, sans élévation)."""
        if device is None:
            return
        try:
            interrupted = any(sf3000_clone.has_marker(mp) for mp in device.mountpoints)
        except OSError:
            return
        if interrupted and self._whole_card_marker_warned != device.path:
            self._whole_card_marker_warned = device.path
            self._log_panel.append_log(tr("whole_card_marker_found", display=device.display))

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

        if self._mode == "reset_card":
            # « Remettre la carte à zéro » (§4.3 bis, mode expert) : pas de
            # fichier à choisir -- l'étiquette du volume d'abord
            # (`ResetCardLabelDialog`), puis la fenêtre Confirmation
            # obligatoire (§2 n°6), jamais l'inverse.
            self._reset_card_label_dialog.set_default_label(self._reset_card_label)
            self._reset_card_label_dialog.set_default_filesystem(self._reset_card_filesystem)
            self._reset_card_label_dialog.open()
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
            self._console_stage.start_activity()
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
            self._console_stage.stop_activity()
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
            self._console_stage.stop_activity()
        if not ok or self._pending_estimate_size_bytes is None:
            message = friendly_error_message(self._last_error_code or "")
            self._log_panel.append_log(message)
            detail = error_log_detail(self._last_error_code, self._last_error_msg)
            if detail and detail != message:
                self._log_panel.append_log(detail)
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
        self._whole_card = False
        used_bytes = sf3000_clone.whole_card_used_bytes(self._file_path, self._device)
        if used_bytes is not None:
            if self._assisted_ad_hoc_active:
                # Mode assisté : pas de choix technique à faire, toute la carte.
                self._use_whole_card_automatically(used_bytes)
            else:
                self._whole_card_dialog.set_estimates(
                    self._device.size_bytes,
                    os.path.getsize(self._file_path),
                    sf3000_clone.extra_minutes_vs_raw(used_bytes, os.path.getsize(self._file_path)),
                    sf3000_clone.verify_minutes(used_bytes),
                )
                self._whole_card_dialog.open()
                return
        # Le flash écrit sur le périphérique brut : confirmation explicite
        # obligatoire (règle §2 n°6). Les autres jobs n'effacent rien
        # (sauvegarde vers un fichier, ou copie de fichiers sur une
        # partition déjà en usage) — pas de fenêtre rouge.
        self._confirm_dialog.set_device(self._device)
        self._confirm_dialog.open()

    def _use_whole_card_automatically(self, used_bytes: int) -> None:
        """Mode assisté, image SF3000 : toute la carte, vérification
        toujours faite -- décision journalisée avec sa durée estimée."""
        self._whole_card = True
        self._whole_card_verify = True
        self._log_panel.append_log(tr("whole_card_wizard_log", minutes=sf3000_clone.total_minutes(used_bytes)))

    def _on_whole_card_chosen(self, whole_card: bool, verify: bool) -> None:
        """Réponse de `WholeCardChoiceDialog`, puis la fenêtre Confirmation
        obligatoire (§2 n°6) dans les deux cas."""
        self._whole_card = whole_card
        self._whole_card_verify = verify
        self._confirm_dialog.set_device(self._device)
        self._confirm_dialog.open()

    def _on_reset_card_label_chosen(self, label: str, filesystem: str) -> None:
        """Réponse de `ResetCardLabelDialog` (§4.3 bis) -- mémorisées pour
        `_start_worker` (`--label`/`--filesystem`) et pour repré-remplir
        la fenêtre la prochaine fois, avant la fenêtre Confirmation
        obligatoire (§2 n°6, jamais sautée -- cette opération efface toute
        la carte, tout aussi destructrice qu'un flash). Le système de
        fichiers est mémorisé d'un lancement à l'autre comme `firmware`/
        `ui_mode` (`config.py`).

        Demande explicite : « si le FAT32 s'avère impossible sur une
        taille donnée, le dire clairement avant de lancer l'opération,
        jamais après » -- `check_fat32_feasible` (aucune élévation, pure
        lecture de `device.size_bytes` déjà connu) est vérifiée ici, avant
        même la fenêtre Confirmation, symétrique du même contrôle côté
        CLI (`__main__.py::cmd_reset_card`, autorité réelle -- celle-ci
        n'est qu'un filet côté GUI pour éviter une confirmation inutile).
        En pratique ne se déclenche jamais sur une vraie carte SD (§
        `imaging/reset_card.py::check_fat32_feasible`)."""
        if filesystem == "fat32":
            try:
                check_fat32_feasible(self._device)
            except (CardTooSmallForReset, Fat32VolumeTooSmall):
                QMessageBox.warning(self, tr("app_title"), tr("reset_card_fat32_impossible_warning"))
                return

        self._reset_card_label = label
        self._reset_card_filesystem = filesystem
        self._app_config.reset_card_filesystem = filesystem
        app_config.save_config(self._app_config)
        self._confirm_dialog.set_device(self._device)
        self._confirm_dialog.open()

    def _on_confirmed(self) -> None:
        self._confirm_dialog.close()
        self._start_worker()

    # --- opération : journal de bord permanent (§5, refonte navigation) ----

    def _start_worker(self) -> None:
        self._flash_ejected = None
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
            # Repart d'un terminal d'activité vierge pour cette nouvelle
            # opération (§5) -- `_on_progress` y ajoute une ligne par
            # événement de progression réel pendant qu'elle tourne.
            self._console_stage.start_activity()
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
        elif self._mode == "reset_card":
            argv = [
                "reset-card",
                "--device",
                self._device.path,
                "--label",
                self._reset_card_label,
                "--filesystem",
                self._reset_card_filesystem,
            ]
        elif self._whole_card:
            argv = ["clone-sf3000", "--image", self._file_path, "--device", self._device.path]
            if not self._whole_card_verify:
                argv.append("--no-verify")
            # Éjection en fin d'opération en mode expert, comme le flash
            # (ci-dessous) ; le parcours guidé éjecte à son étape 5.
            if self._flash_may_trigger_windows_format_prompt():
                argv.append("--eject-after")
        else:
            argv = ["flash", "--image", self._file_path, "--device", self._device.path]
            # Plus de drapeau `--create-games-partition` à construire ici
            # (§4.3) : la décision (recréer ou non une partition de jeux
            # sur l'espace laissé libre) est désormais entièrement
            # automatique, prise par le worker élevé lui-même *après*
            # l'écriture, à partir de la taille réelle de la carte -- la
            # GUI n'a plus besoin de deviner la provenance du fichier
            # choisi (comparaison de chemin, case à cocher : les deux
            # ont été retirées, remplacées par `imaging.games_partition
            # .create_and_format_games_partition_if_worthwhile`,
            # `__main__.py::cmd_flash`). Correct pour tout flash, dans les
            # deux modes : l'utilisateur ne peut de toute façon pas savoir
            # à l'avance si une image donnée laissera de l'espace libre
            # (§1 -- retour d'usage réel après une première version basée
            # sur une case à cocher, jugée déroutante y compris pour
            # quelqu'un qui connaît le logiciel).
            if self._flash_may_trigger_windows_format_prompt():
                # Au moins une de ses partitions est illisible pour Windows
                # (le système ext4 "Linux" de tout le catalogue, plusieurs
                # partitions en plus pour Android), qui propose de la
                # formater dès qu'il la découvre (§4.6) -- éjecter tout de
                # suite, dans ce même worker déjà élevé, réduit la fenêtre
                # pendant laquelle ça peut arriver (voir le message
                # explicite ajouté au journal par `_on_worker_finished`,
                # qui reste le vrai filet de sécurité si l'éjection ne
                # gagne pas la course).
                argv.append("--eject-after")
        if self._mode in ("backup", "backup_system") and self._wizard_active:
            # Chaîne l'éjection de la carte source dans ce même worker déjà
            # élevé (§5 mode assisté, `_run_wizard_source_eject`) plutôt que
            # d'en relancer un second dédié juste après -- évite une
            # seconde invite UAC dans le cas courant (les deux réussissent
            # ensemble). Un échec de cette éjection chaînée ne fait jamais
            # échouer la sauvegarde elle-même (voir `emit_eject_result`,
            # `protocol.py`) -- `_on_wizard_source_eject_result` (connecté
            # ci-dessous) et `_run_wizard_source_eject` retombent alors sur
            # le worker d'éjection dédié existant, sans jamais avoir à
            # refaire toute la copie pour ça.
            argv.append("--eject-after")

        # Journalise la ligne de commande complète au lancement de tout
        # worker élevé (backup/flash) -- signalé sur du vrai matériel :
        # sans ça, impossible de vérifier depuis les traces d'élévation
        # elles-mêmes ce que l'app a réellement lancé (ex. la présence ou
        # non d'un drapeau donné), sans devoir instrumenter le worker
        # élevé lui-même à chaque doute (§4.4 : jamais une décision
        # silencieuse). `join` plutôt que la liste Python brute -- se lit
        # comme la vraie ligne de commande qu'un utilisateur pourrait
        # retaper à la main.
        self._log_panel.append_log(f"[diagnostic] worker : {' '.join(argv)}")
        self._runner = WorkerRunner(argv, parent=self, macos_auth_session=self._get_or_create_macos_auth_session())
        self._runner.progress.connect(self._on_progress)
        self._runner.step_progress.connect(self._on_step_progress)
        self._runner.log.connect(lambda level, msg: self._log_panel.append_log(msg))
        self._runner.error.connect(self._on_worker_error)
        self._runner.finished.connect(self._on_worker_finished)
        if self._mode in ("backup", "backup_system") and self._wizard_active:
            self._runner.eject_result.connect(self._on_wizard_source_eject_result)
        elif "--eject-after" in argv:
            # Flash mode expert (`_flash_may_trigger_windows_format_
            # prompt`, ci-dessus) -- même mécanisme, `_on_flash_eject_
            # result` plutôt que `_on_wizard_source_eject_result` (mode
            # assisté) : les deux stockent un résultat distinct
            # (`_flash_ejected` vs `_wizard_source_ejected`), jamais
            # confondus.
            self._runner.eject_result.connect(self._on_flash_eject_result)
        self._runner.start()

    def _on_wizard_source_eject_result(self, ok: bool, msg: str) -> None:
        """Reçu avant `finished` (l'événement `eject_result` du worker de
        l'étape 2 est émis juste avant `done`, `__main__.py::cmd_backup`) --
        retenu ici pour que `_run_wizard_source_eject` sache, une fois
        `_on_wizard_job_finished` atteint, si la carte source a déjà été
        éjectée dans ce même worker ou si un worker d'éjection dédié reste
        nécessaire."""
        self._wizard_source_ejected = ok
        self._wizard_source_eject_error_msg = None if ok else msg

    def _on_flash_eject_result(self, ok: bool, msg: str) -> None:
        """Reçu avant `finished` (comme `_on_wizard_source_eject_result`
        ci-dessus, mais pour `flash --eject-after` en mode expert) --
        `_on_worker_finished` s'en sert pour décider si le bouton Éjecter
        de fin d'opération doit rester masqué (l'éjection chaînée a
        réellement réussi) ou réapparaître (elle a échoué -- bug corrigé,
        confirmé sur du vrai matériel : rester masqué inconditionnellement
        laissait la carte réellement non éjectée sans bouton visible pour
        réessayer)."""
        self._flash_ejected = ok

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
        """Bug corrigé, constaté sur du vrai matériel : fermer la fenêtre
        pendant qu'une opération élevée tournait encore laissait le worker
        orphelin -- PID survivant, verrous de fichiers maintenus (le
        binaire empaqueté lui-même, mais tout aussi bien un verrou sur la
        carte SD en cours d'écriture, §2 : un risque réel, pas seulement
        une gêne). `closeEvent` ne faisait jusqu'ici rien de tel que
        vérifier `self._runner` -- qui de toute façon ne redevient jamais
        `None` après une opération terminée (§ `_terminate_active_worker_
        before_close`, ci-dessous), d'où `LogPanel.is_operation_active()`
        plutôt qu'un simple `self._runner is not None`."""
        if self._log_panel.is_operation_active() and self._runner is not None:
            self._terminate_active_worker_before_close()
        if self._macos_auth_session is not None:
            self._macos_auth_session.close()
        super().closeEvent(event)

    def _terminate_active_worker_before_close(self) -> None:
        """Annulation coopérative d'abord (`cancel()`, via le fichier que
        le worker surveille lui-même -- laisse une chance de refermer
        proprement un handle d'écriture brute en cours plutôt que de le
        couper net) ; si le worker ne s'arrête pas de lui-même dans un délai
        court, arrêt forcé (`force_kill()`). Sur Windows, ce dernier tue
        désormais tout l'arbre de processus -- Job Object avec `JOB_OBJECT_
        LIMIT_KILL_ON_JOB_CLOSE`, `gui/elevate.py` -- pas seulement le
        worker principal : sans ça, un sous-processus PowerShell qu'il
        aurait lui-même lancé (`winprocess.py`) aurait survécu tout autant,
        exactement le symptôme rapporté (quatre `powershell.exe` restés
        après fermeture, en plus du worker). Délai volontairement court :
        jamais un blocage indéfini de la fermeture de l'app pour un worker
        qui ne répond pas."""
        runner = self._runner
        try:
            runner.cancel()
        except Exception:
            pass
        process = getattr(runner, "_process", None)
        if process is not None:
            deadline = time.monotonic() + _WORKER_SHUTDOWN_GRACE_SECONDS
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return
                time.sleep(0.05)
        try:
            runner.force_kill()
        except Exception:
            pass

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
        if self._console_stage is not None:
            # Terminal d'activité disque de l'écran de la console (§5) :
            # une ligne par événement de progression réellement émis par
            # `copy_range`/`copy_tree` -- jamais une ligne inventée sans
            # écriture correspondante (§2 règle 5). Le bloc affiché est le
            # delta depuis le dernier événement (les octets réellement
            # transférés dans cette fenêtre), pas une taille de bloc
            # interne supposée -- ce delta peut agréger plusieurs blocs de
            # 4 Mio de `copy_range` entre deux événements de progression.
            #
            # Correction de conception, confirmée sur du vrai matériel :
            # ce terminal a été accusé à tort d'un ralentissement de la
            # sauvegarde système d'un facteur dix (~85 Mo/s -> 6,7 Mo/s),
            # puis entièrement retiré -- la cause réelle, confirmée en
            # bissectant par mesure du débit CLI pur (donc sans ce
            # terminal), était une carte SD d'origine de console non
            # reconnue (~6 Mo/s en lecture contre ~88 Mo/s pour une
            # SanDisk sur le même port, capacité exposée très inférieure à
            # celle annoncée -- §8). Rétabli : ce code n'a jamais été la
            # cause du ralentissement rapporté.
            block = max(0, done - self._last_progress_bytes)
            self._console_stage.append_line(f"0x{done:010X}  +{_format_size(block)}  {_format_size(speed)}/s")
        # `done` du tout dernier événement = le compte final exact (§2 n°5,
        # `copy_range`/`copy_tree`) -- utilisé comme taille de l'archive
        # créée par les étapes A/B (journal de bord).
        self._last_progress_bytes = done
        self._log_panel.update_progress(done, total, speed)

    def _on_step_progress(self, step_index: int, step_count: int, step_name: str) -> None:
        """Progression par étapes réelles (§2 n°5, §4.3 bis « Remettre la
        carte à zéro ») -- distinct de `_on_progress` ci-dessus (bytes/
        débit), pour une opération qui n'a rien à copier."""
        self._log_panel.update_step_progress(step_index, step_count, step_name)

    def _on_cancel_requested(self) -> None:
        if self._runner is not None:
            self._log_panel.set_cancel_enabled(False)
            self._runner.cancel()

    @Slot(str, str)
    def _on_worker_error(self, code: str, msg: str) -> None:
        self._last_error_code = code
        self._last_error_msg = msg

    def _is_flashing_android_firmware(self) -> bool:
        """Vrai seulement pour un flash mode expert d'un firmware Android
        (§4.6, R36Droid/andr36oid) -- jamais pour le parcours de clonage du
        mode assisté, qui restaure la propre sauvegarde de l'utilisateur
        sans jamais choisir de firmware (`self._app_config.firmware` n'a
        alors aucun rapport avec ce qui est réellement écrit). Recalculée à
        chaque appel plutôt que mise en cache dans un attribut d'instance :
        appelée à la fois avant de lancer le worker (`_start_worker`, pour
        `--eject-after`) et à sa fin (`_on_worker_finished`, pour le
        message d'avertissement) -- les deux doivent s'accorder sur le
        même résultat sans dépendre de l'ordre d'appel."""
        if self._mode != "flash" or self._wizard_active:
            return False
        entry = FIRMWARE_BY_ID.get(self._app_config.firmware)
        return entry is not None and entry.is_android

    def _flash_post_log_key(self) -> Optional[str]:
        """Consigne du firmware flashé à journaliser après un flash réussi
        (`FirmwareEntry.post_flash_log_key`) -- mêmes conditions que
        `_is_flashing_android_firmware` : jamais pour le parcours de
        clonage du mode assisté, qui n'a pas choisi de firmware."""
        if self._mode != "flash" or self._wizard_active:
            return None
        entry = FIRMWARE_BY_ID.get(self._app_config.firmware)
        return entry.post_flash_log_key if entry is not None else None

    def _flash_may_trigger_windows_format_prompt(self) -> bool:
        """Vrai pour tout flash mode expert, quel que soit le firmware
        choisi -- constaté en usage réel : Windows propose de formater la
        carte après le flash d'un firmware "Linux" (ArkOS/ROCKNIX/EmuELEC/
        AmberELEC/MinUI, une seule boîte pour leur partition ext4 illisible)
        exactement comme pour un firmware Android (§4.6, plusieurs boîtes) --
        pas seulement pour Android comme le supposait le premier correctif.
        Aucune entrée du catalogue (`identify/firmware_catalog.py`) n'est
        entièrement lisible par Windows (BOOT en FAT mis à part), donc pas
        besoin de filtrer par firmware ici, contrairement à `_is_flashing_
        android_firmware` (qui reste nécessaire pour choisir le message
        détaillé propre à Android, ci-dessous, plutôt que le message
        générique). Jamais pour le parcours de clonage du mode assisté :
        celui-ci éjecte déjà automatiquement la carte neuve à l'étape 5
        (`_run_wizard_eject`), immédiatement après la restauration -- une
        seconde éjection ferait double emploi."""
        return self._mode == "flash" and not self._wizard_active

    def _success_message(self) -> str:
        if self._mode == "backup":
            return tr("success_backup", display=self._device.display, path=self._file_path)
        if self._mode == "backup_system":
            return tr("success_backup_system", display=self._device.display, path=self._file_path)
        if self._mode == "extract_boot":
            return tr("success_extract_boot")
        if self._mode == "extract_easyroms":
            return tr("success_extract_easyroms")
        if self._mode == "inject_boot":
            return tr("success_inject_boot", display=self._device.display)
        if self._mode == "copy_games":
            return tr("success_copy_games", display=self._device.display)
        if self._mode == "reset_card":
            return tr("success_reset_card", display=self._device.display)
        return tr("success_ready", display=self._device.display)  # flash

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
        QTimer.singleShot(0, self._show_update_badge_if_idle)
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        if self._console_stage is not None:
            self._console_stage.stop_activity()
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
            android_flash = self._is_flashing_android_firmware() and not self._whole_card
            format_prompt_flash = self._flash_may_trigger_windows_format_prompt()
            # Déjà éjectée par le worker lui-même dans le cas courant
            # (`--eject-after`, ajouté dans `_start_worker` dès que
            # `format_prompt_flash` est vrai, donc pour tout flash mode
            # expert désormais -- plus seulement Android) -- proposer de
            # l'éjecter à nouveau serait redondant, voire une erreur si la
            # carte n'est déjà plus vue par l'OS. Bug corrigé, confirmé sur
            # du vrai matériel : masquer le bouton inconditionnellement dès
            # que ce drapeau était posé, sans jamais vérifier si l'éjection
            # chaînée avait réellement réussi, laissait un échec silencieux
            # (best-effort, `emit_eject_result`) sans aucun moyen évident de
            # réessayer -- l'utilisateur devait alors passer par l'étape F
            # séparée, une invite UAC dédiée en plus, minutes plus tard.
            # `self._flash_ejected is False` (résultat connu et négatif)
            # réaffiche donc le bouton ; `True` ou `None` (succès, ou signal
            # jamais reçu -- comportement par défaut inchangé) le laissent
            # masqué comme avant.
            allow_eject = self._mode in _ALLOW_EJECT_AFTER_MODES and (
                not format_prompt_flash or self._flash_ejected is False
            )
            archive_info = self._archive_info()
            reveal_path = self._file_path if self._mode in (_EXTRACTION_MODES | _INJECTION_MODES) else None
            if archive_info:
                self._log_panel.append_log(archive_info)
            self._log_panel.finish_success(self._success_message(), allow_eject=allow_eject, reveal_path=reveal_path)
            if android_flash:
                # Windows ne sait lire aucune partition Android (boot/
                # system/vendor/userdata...) et propose de les formater dès
                # qu'il les découvre -- une boîte par partition illisible,
                # qu'un débutant risque d'accepter et de détruire ce qui
                # vient d'être écrit (§4.6). L'éjection automatique
                # ci-dessus réduit le risque immédiat sans l'éliminer (ni
                # garantie de gagner la course contre Windows, ni protection
                # si la carte est un jour rebranchée ailleurs) -- ce message
                # explicite est le vrai filet de sécurité, jamais retiré
                # même quand l'éjection automatique a réussi.
                self._log_panel.append_log(tr("flash_android_format_prompt_warning"))
                # Constaté en usage réel : une image Android flashée peut
                # démarrer sur un écran figé si l'écran ne correspond pas --
                # le mécanisme de rechange (dossier "Panels" du BOOT, un
                # sous-dossier par écran) existe déjà côté firmware, mais
                # rien ne l'indiquait dans l'app avant cette ligne. Ne
                # promet jamais que ça marchera (§4.6, ci-dessous : sur la
                # console de test, les trois écrans compatibles essayés ont
                # tous échoué) -- une piste à essayer, pas une garantie.
                self._log_panel.append_log(tr("flash_android_panel_mismatch_warning"))
            elif format_prompt_flash and not self._whole_card:
                # (Jamais après « utiliser toute la carte » : un seul
                # volume exFAT, lisible par Windows.)
                # Constaté en usage réel : le même genre de boîte « Vous
                # devez formater le disque » apparaît aussi après un flash
                # non-Android (ArkOS/ROCKNIX/EmuELEC/AmberELEC/MinUI, une
                # seule boîte pour leur partition ext4, §4.6) -- message
                # générique plutôt que le message Android détaillé
                # ci-dessus (pas de partitions multiples ni de mécanisme
                # d'écran de rechange à expliquer ici).
                self._log_panel.append_log(tr("flash_format_prompt_warning_generic"))
            post_flash_key = self._flash_post_log_key()
            if post_flash_key:
                # Consigne propre au firmware (dArkOSen : choisir le modèle
                # de la console), après les avertissements de formatage --
                # la description lue avant le flash est oubliée plusieurs
                # minutes après (`FirmwareEntry.post_flash_log_key`).
                self._log_panel.append_log(tr(post_flash_key))
        else:
            # `friendly_error_message` mappe déjà "CANCELLED" sur le
            # message d'annulation adéquat (`strings._ERROR_MESSAGE_KEYS`)
            # -- pas besoin de le distinguer ici séparément, contrairement
            # à l'ancien écran Résultat qui en avait besoin pour choisir
            # entre deux titres différents.
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=error_log_detail(self._last_error_code, self._last_error_msg))
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
            self._log_panel.finish_error(friendly, details=error_log_detail(self._last_error_code, self._last_error_msg))

        # Table généralisée (§5, refonte menu de tuiles) -- remplace l'ancien
        # `if self._mode == "backup_system": ... else: ...` écrit pour
        # exactement 2 cas (le second étant du texte flash en dur, valable
        # uniquement pour « Préparer une carte avec cette sauvegarde »).
        # `show_prepare_card` n'a de sens (et n'est `True`) que pour
        # "backup"/"backup_system" -- et seulement si l'opération a réussi.
        title_key, instruction_key, offers_prepare_card = _ASSISTED_AD_HOC_DONE_STRINGS.get(
            self._mode, ("assisted_prepare_card_done_title", "assisted_prepare_card_done_instruction", False)
        )
        self._wizard_panel.show_next_step_choice(
            tr(title_key), tr(instruction_key), show_prepare_card=offers_prepare_card and ok
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
            self._console_stage.start_activity()
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
            self._console_stage.stop_activity()
        if not variants:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=error_log_detail(self._last_error_code, self._last_error_msg))
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
            self._console_stage.start_activity()
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
            self._console_stage.stop_activity()
        if not ok:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=error_log_detail(self._last_error_code, self._last_error_msg))
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

    def _start_eject(self, device: Device, on_finished) -> None:
        """Lance l'éjection de `device` via un worker élevé dédié -- bug
        corrigé, confirmé sur du vrai matériel : ouvrir `\\\\.\\
        PhysicalDriveN` pour `IOCTL_STORAGE_EJECT_MEDIA` (Windows) exige
        l'élévation, exactement comme l'écriture brute (§4.3) -- appeler
        `partitions.eject.eject` directement dans le processus GUI, à
        privilèges normaux, échouait systématiquement avec `ERROR_ACCESS_
        DENIED` (erreur 5), silencieusement pour l'éjection automatique de
        l'étape 3 (aucun `emit_error`/`emit_log` n'atteignait jamais le
        journal, l'exception étant levée avant même que le protocole JSON
        Lines n'ait quoi que ce soit à relayer) et via une simple boîte de
        dialogue jamais journalisée pour le bouton (§4.4 : jamais un succès
        -- ni un échec -- silencieux).

        Réutilise `WorkerRunner` (`["eject", "--device", device.path]`,
        même mécanisme que `backup`/`flash`) plutôt qu'un appel synchrone :
        une invite d'élévation (UAC/`osascript`/`pkexec`) est de toute
        façon nécessaire à chaque nouveau worker sur Windows (aucun
        équivalent de `MacosAuthorizationSession` n'existe pour cet OS,
        §3) -- accepté ici comme ailleurs dans ce projet, plutôt que de
        chaîner l'éjection dans le worker qui vient d'écrire/de lire (ce
        qui économiserait cette invite dans certains cas, mais ferait
        perdre la distinction entre « l'opération a réussi » et « l'
        éjection qui a suivi a échoué » si un échec de cette dernière
        faisait échouer tout le worker). `macOS`/Linux ne sont pas
        concernés par cette limitation d'origine (une élévation non
        privilégiée y fonctionnait déjà), mais passent désormais par le
        même chemin pour rester cohérents et testables uniformément.

        **Exception notable : l'éjection de la carte source (étape 3,
        `_run_wizard_source_eject`) est bien chaînée dans le worker de
        sauvegarde de l'étape 2** (`backup --eject-after`,
        `emit_eject_result` -- distinct du canal `on_finished` ci-dessous,
        propre à ce worker d'éjection *dédié*) -- sans le compromis
        ci-dessus, puisque son résultat est rapporté sur un canal séparé
        qui ne fait jamais échouer la sauvegarde elle-même. Ce worker
        dédié (`_start_eject`) reste le chemin normal pour l'éjection de
        la carte cible (étape 5) et pour un repli si l'éjection chaînée de
        l'étape 3 a échoué -- voir `_run_wizard_source_eject`.

        `on_finished(ok, code, msg)` est appelé une fois le worker
        terminé -- jamais silencieusement : chaque appelant journalise
        explicitement le résultat, succès comme échec (§4.4). Ceci inclut
        désormais un refus d'élévation lui-même (`runner.start()`, voir
        ci-dessous) : `on_finished` est le seul point d'arrivée, qu'un
        appelant n'a donc plus besoin d'entourer de son propre `try/except`
        pour ce cas précis (`_run_wizard_source_eject` en gardait un pour
        d'autres causes, ex. `self._wizard_source_device` valant `None`).

        ⚠️ Bug corrigé, confirmé sur du vrai matériel : une invite UAC
        refusée pendant l'éjection affichait « Impossible d'éjecter la
        carte. Ferme les fichiers ouverts dessus » -- sans rapport avec la
        cause réelle. `runner.start()` (Windows, `ShellExecuteExW` verbe
        `runas`) peut lever `elevate.ElevationRefusedError` de façon
        *synchrone*, avant même que le protocole JSON Lines n'ait quoi que
        ce soit à relayer -- resté non intercepté ici, cette exception se
        propageait telle quelle jusqu'à l'appelant, dont le `try/except`
        générique (`_run_wizard_source_eject`) la retombait alors
        systématiquement sur le code `EJECT_FAILED` codé en dur, quelle
        que soit la cause réelle. Distinguée maintenant à la source : un
        refus d'élévation devient le code dédié `ELEVATION_REFUSED`
        (message « L'autorisation Windows a été refusée. Réessaie et
        accepte l'invite. »), toute autre exception au démarrage restant
        `EJECT_FAILED` comme avant."""
        self._home.set_busy(True)
        self._assisted_landing.set_busy(True)
        eject_argv = ["eject", "--device", device.path]
        self._log_panel.append_log(f"[diagnostic] worker : {' '.join(eject_argv)}")
        try:
            runner = WorkerRunner(
                eject_argv,
                parent=self,
                macos_auth_session=self._get_or_create_macos_auth_session(),
            )
        except Exception:
            # Ne jamais laisser l'interface bloquée « occupée » sans issue
            # si la construction du worker échoue avant même son démarrage
            # (ex. `device` invalide) -- l'appelant journalise l'exception
            # qu'on relève (§4.4).
            self._home.set_busy(False)
            self._assisted_landing.set_busy(False)
            raise
        self._eject_runner = runner
        state = {"code": None, "msg": None}

        def _on_error(code: str, msg: str) -> None:
            state["code"] = code
            state["msg"] = msg

        def _on_runner_finished(ok: bool) -> None:
            self._home.set_busy(False)
            self._assisted_landing.set_busy(False)
            self._eject_runner = None
            on_finished(ok, state["code"], state["msg"])

        runner.error.connect(_on_error)
        runner.finished.connect(_on_runner_finished)
        try:
            runner.start()
        except elevate.ElevationRefusedError as exc:
            self._home.set_busy(False)
            self._assisted_landing.set_busy(False)
            self._eject_runner = None
            on_finished(False, "ELEVATION_REFUSED", str(exc))
        except Exception as exc:
            self._home.set_busy(False)
            self._assisted_landing.set_busy(False)
            self._eject_runner = None
            on_finished(False, "EJECT_FAILED", str(exc))

    def _perform_eject(self) -> None:
        """Étape F : démonte toutes les partitions et éjecte, puis
        confirme explicitement que la carte peut être retirée (§4.5) --
        jamais un succès silencieux. Résultat affiché dans le journal de
        bord, pas un écran séparé (§5, refonte navigation)."""
        self._log_panel.append_log("Éjection de la carte…")
        self._start_eject(self._device, self._on_perform_eject_finished)

    def _on_perform_eject_finished(self, ok: bool, code: Optional[str], msg: Optional[str]) -> None:
        if ok:
            self._log_panel.append_log(f"{self._device.display} peut maintenant être retirée en toute sécurité.")
        else:
            self._log_panel.append_log(friendly_error_message(code or "EJECT_FAILED"))
            if msg:
                self._log_panel.append_log(msg)
        if self._assisted_ad_hoc_active:
            # Tuile « Éjecter la carte » (§5, refonte menu de tuiles) --
            # même principe que `_on_assisted_ad_hoc_worker_finished` :
            # propose toujours une suite explicite plutôt qu'un retour
            # silencieux à `_home` (jamais visible dans ce contexte,
            # contrairement au mode expert où `_refresh_home_state()` a un
            # sens) -- correctif du même défaut de parcours déjà corrigé
            # pour les autres tuiles-job.
            title_key, instruction_key, _ = _ASSISTED_AD_HOC_DONE_STRINGS["eject"]
            self._wizard_panel.show_next_step_choice(tr(title_key), tr(instruction_key), show_prepare_card=False)
            return
        self._refresh_home_state()

    def _on_eject_requested(self) -> None:
        """Bouton Éjecter du journal de bord, proposé après une opération
        qui a écrit sur la carte (§4.5) -- distinct de `_perform_eject`
        (l'étape F elle-même, immédiate, sans opération préalable). Bug
        corrigé au passage : le résultat n'était auparavant journalisé
        qu'en cas de succès, une `QMessageBox` isolée (jamais dans le
        journal) portant l'échec -- désormais journalisé dans les deux
        cas, comme `_perform_eject` (§4.4)."""
        self._log_panel.append_log("Éjection de la carte…")
        self._start_eject(self._device, self._on_eject_requested_finished)

    def _on_eject_requested_finished(self, ok: bool, code: Optional[str], msg: Optional[str]) -> None:
        if ok:
            self._log_panel.append_log(f"{self._device.display} peut maintenant être retirée en toute sécurité.")
        else:
            self._log_panel.append_log(friendly_error_message(code or "EJECT_FAILED"))
            if msg:
                self._log_panel.append_log(msg)

    # --- mode assisté (§5 mode assisté) : 7 étapes, une carte puis l'autre --

    def _switch_to_expert_mode(self) -> None:
        """Bouton « Mode expert », depuis l'accueil assisté ou depuis une
        étape en erreur (§5) -- n'annule/ne défait aucune opération déjà
        réussie : une archive déjà extraite reste utilisable depuis
        l'étape D du mode expert."""
        self._stop_wizard_poll_timer()
        self._wizard_active = False
        self._app_config.ui_mode = "expert"
        app_config.save_config(self._app_config)
        self._main_view.show_home()
        self._root_stack.setCurrentWidget(self._main_view)
        self._refresh_home_state()

    def _start_assisted_ad_hoc_job(self, job_key: str) -> None:
        """Lance un job (§4.6) depuis une tuile de l'accueil assisté (§5,
        refonte menu de tuiles) -- généralise l'ancien `_start_backup_
        system_from_assisted_landing` (qui ne gérait que `backup_system`
        en dur) à tout `job_key` déjà géré par `_start_flow`
        (`"backup"`/`"backup_system"`/`"flash"`/`"copy_games"`/
        `"inject_boot"`/`"reset_card"`/`"eject"`). Réutilise `MainView`/
        `_log_panel` le temps de l'opération, pour bénéficier du journal
        de bord et des états occupé déjà en place, sans en faire un vrai
        changement de mode : contrairement à `_switch_to_expert_mode`,
        `ui_mode` n'est jamais modifié ni persisté ici. Reste dans
        l'habillage assisté (`WizardStepPanel`), jamais l'écran expert
        (`HomeScreen`). `_on_worker_finished` consulte
        `_assisted_ad_hoc_active` pour proposer explicitement la suite
        (`WizardStepPanel.show_next_step_choice`, `_on_assisted_ad_hoc_
        worker_finished` ci-dessus) plutôt que de laisser l'utilisateur
        sans issue une fois l'opération terminée."""
        self._assisted_ad_hoc_active = True
        self._main_view.show_wizard_panel()
        running_title_key, running_instruction_key = _ASSISTED_AD_HOC_RUNNING_STRINGS[job_key]
        self._wizard_panel.show_step(tr(running_title_key), tr(running_instruction_key), can_continue=False)
        self._root_stack.setCurrentWidget(self._main_view)
        self._start_flow(job_key)

    def _on_assisted_backup_tile_clicked(self) -> None:
        """Tuile « Sauvegarder ma carte » (§5, refonte menu de tuiles) --
        ouvre `_assisted_backup_kind_dialog` (instance dédiée, jamais
        `_backup_kind_dialog` du vrai parcours guidé, voir son
        commentaire au constructeur) pour choisir complète vs système
        seul avant de lancer `_start_assisted_ad_hoc_job` avec le
        `job_key` correspondant -- une seule tuile, deux issues possibles,
        même mécanisme final que le vrai parcours guidé en amont de la
        création d'image (usage distinct, mécanisme partagé)."""
        self._assisted_backup_kind_dialog.open()

    def _on_assisted_help_requested(self) -> None:
        """Tuile Aide de l'accueil assisté (§5, refonte menu de tuiles),
        visible sur les trois OS contrairement au bouton d'aide de
        `HomeScreen` (macOS uniquement) -- macOS ouvre `HelpDialog` (Accès
        complet au disque, §3, contenu sans rapport avec les deux autres
        OS) ; Windows/Linux ouvrent `_about_dialog`, minimaliste."""
        if platform.system() == "Darwin":
            self._help_dialog.open()
        else:
            self._about_dialog.open()

    def _start_assisted_identify(self) -> None:
        """Tuile « Rechercher ma console » (§5, refonte menu de tuiles) --
        sélection de carte comme `_start_flow` (un seul candidat détecté ->
        directement ; sinon `_identify_device_dialog`), puis `IdentifyRunner`
        sur un thread séparé (montage du BOOT, potentiellement bloquant,
        §4.4). Opération courte, sans progression à afficher -- pas de
        bascule vers `_main_view`, juste `set_busy` autour de l'appel,
        même principe que `_start_system_backup_estimate` pour un calcul
        similaire."""
        devices = self._list_safe_devices()
        if len(devices) == 1:
            self._run_identify(devices[0])
            return
        self._identify_device_dialog.set_devices(devices)
        self._identify_device_dialog.open()

    def _on_identify_device_chosen(self, device: Device) -> None:
        self._identify_device_dialog.close()
        self._run_identify(device)

    def _run_identify(self, device: Device) -> None:
        self._home.set_busy(True)
        self._assisted_landing.set_busy(True)
        self._identify_runner = IdentifyRunner(device.path, parent=self)
        self._identify_runner.finished_identify.connect(self._on_identify_finished)
        self._identify_runner.start()

    def _on_identify_finished(self, result: IdentifyResult) -> None:
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        self._identify_runner = None
        self._identify_result_dialog.set_result(result)
        self._identify_result_dialog.open()

    def _start_doublons_tool(self) -> None:
        """Tuile « Chercher les doublons » (docs/doublons.md, remplace
        l'ancien flux carte-SD-uniquement) -- outil autonome : ouvre le
        choix du dossier plutôt qu'un choix de carte."""
        self._refresh_doublons_shortcuts()
        self._refresh_doublons_resume_button()
        self._doublons_folder_screen.set_simulation_mode(self._app_config.doublons_simulation_mode)
        self._doublons_folder_screen.set_ignored_folders(list(self._app_config.doublons_ignored_folders))
        self._root_stack.setCurrentWidget(self._doublons_folder_screen)

    def _refresh_doublons_resume_button(self) -> None:
        """Signalé explicitement : « ne jamais obliger à relancer une
        analyse » -- cherche la dernière analyse mise en cache, tous
        dossiers confondus (`find_most_recent_scan_cache`, une seule
        proposition, pas une par raccourci), et la garde en attente
        (`_doublons_resume_cache`) pour que le clic sur le bouton n'ait
        plus qu'à la consommer sans relire le disque une seconde fois."""
        cached = doublons_scan_cache.find_most_recent_scan_cache()
        self._doublons_resume_cache = cached
        if cached is None:
            self._doublons_folder_screen.set_resume_available(None, None)
            return
        self._doublons_folder_screen.set_resume_available(cached.root, self._format_doublons_cache_date(cached.scanned_at))

    @staticmethod
    def _format_doublons_cache_date(iso: str) -> str:
        """`scanned_at` est enregistré en UTC ISO (`scan_cache.py`) --
        converti vers l'heure locale pour l'affichage, jamais montré tel
        quel (un horodatage UTC brut est incompréhensible pour un
        néophyte, §5 vocabulaire). Repli sur la chaîne brute si le format
        s'avère un jour différent -- jamais une exception qui empêcherait
        d'afficher le bouton."""
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError:
            return iso
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone().replace(tzinfo=None)
        return f"{parsed:%d/%m/%Y %H:%M}"

    def _refresh_doublons_shortcuts(self) -> None:
        """Raccourcis cliquables vers les cartes/disques amovibles
        détectés (même confort que l'ancien flux carte SD, demandé
        explicitement) -- lecture seule (`list_partitions`, déjà utilisée
        ailleurs sans élévation, §4.4), jamais un montage actif. Un
        raccourci par point de montage déjà connu du périphérique, plus
        un raccourci dédié vers EASYROMS quand elle est identifiable
        pour une carte R36S reconnue."""
        shortcuts: List[Tuple[str, str]] = []
        for device in self._list_safe_devices():
            for mountpoint in device.mountpoints:
                shortcuts.append((f"{device.display} ({mountpoint})", mountpoint))
            try:
                partitions = list_partitions(device.path)
            except OSError:
                partitions = []
            for partition in partitions:
                if partition.label == EASYROMS_LABEL and partition.mountpoint:
                    shortcuts.append((f"{device.display} — EASYROMS ({partition.mountpoint})", partition.mountpoint))
        self._doublons_folder_screen.set_shortcuts(shortcuts)

    def _on_doublons_folder_chosen(self, path: str) -> None:
        self._app_config.doublons_simulation_mode = self._doublons_folder_screen.simulation_mode()
        self._app_config.doublons_ignored_folders = self._doublons_folder_screen.ignored_folders()
        app_config.save_config(self._app_config)

        # Garde-fous ajoutés après validation du plan -- confirmation
        # explicite avant de lancer une analyse à risque, jamais un scan
        # démarré silencieusement sur un dossier hors de propos.
        if is_filesystem_root(path):
            self._doublons_pending_risk_action = lambda: self._start_doublons_scan(path)
            self._doublons_risk_confirm_dialog.set_message(tr("doublons_risk_filesystem_root"))
            self._doublons_risk_confirm_dialog.open()
            return
        if is_whole_user_folder(path):
            self._doublons_pending_risk_action = lambda: self._start_doublons_scan(path)
            self._doublons_risk_confirm_dialog.set_message(tr("doublons_risk_whole_user_folder"))
            self._doublons_risk_confirm_dialog.open()
            return
        self._start_doublons_scan(path)

    def _on_doublons_risk_confirmed(self) -> None:
        action = self._doublons_pending_risk_action
        self._doublons_pending_risk_action = None
        if action is not None:
            action()

    def _start_doublons_scan(self, path: str) -> None:
        self._doublons_root = path
        self._home.set_busy(True)
        self._assisted_landing.set_busy(True)
        self._doublons_scan_progress_screen.set_files_scanned(0)
        self._root_stack.setCurrentWidget(self._doublons_scan_progress_screen)
        self._doublons_scan_runner = DoublonsScanRunner(
            path,
            self._app_config.doublons_ignored_folders,
            hash_cache=doublons_scan_cache.load_hash_cache(),
            parent=self,
        )
        self._doublons_scan_runner.progress.connect(self._doublons_scan_progress_screen.set_files_scanned)
        self._doublons_scan_runner.large_folder_confirmation_needed.connect(
            self._on_doublons_large_folder_confirmation_needed
        )
        self._doublons_scan_runner.finished_scan.connect(self._on_doublons_scan_finished)
        self._doublons_scan_runner.cancelled.connect(self._on_doublons_scan_cancelled)
        self._doublons_scan_runner.error.connect(self._on_doublons_scan_error)
        self._doublons_scan_runner.start()

    def _on_doublons_scan_cancel_requested(self) -> None:
        if self._doublons_scan_runner is not None:
            self._doublons_scan_runner.cancel()

    def _on_doublons_large_folder_confirmation_needed(self) -> None:
        self._doublons_large_folder_dialog.set_message(tr("doublons_risk_large_folder"))
        self._doublons_large_folder_dialog.open()

    def _on_doublons_large_folder_confirmed(self) -> None:
        if self._doublons_scan_runner is not None:
            self._doublons_scan_runner.resume_after_large_folder_confirmation(True)

    def _on_doublons_large_folder_cancelled(self) -> None:
        """Contrairement à `_doublons_risk_confirm_dialog`, Annuler ici
        doit aussi débloquer le thread d'analyse resté en attente --
        sinon `DoublonsScanRunner` ne se termine jamais."""
        if self._doublons_scan_runner is not None:
            self._doublons_scan_runner.resume_after_large_folder_confirmation(False)

    def _end_doublons_scan(self) -> None:
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        self._doublons_scan_runner = None

    def _on_doublons_scan_finished(self, result) -> None:
        # Lu avant `_end_doublons_scan()` (qui remet `_doublons_scan_runner`
        # à `None`) -- § demandé explicitement : « cache des empreintes
        # SHA-256 ». Sauvegarde best-effort : un échec d'écriture (carte
        # débranchée, dossier de données inaccessible) ne doit jamais faire
        # échouer l'affichage d'un résultat par ailleurs déjà obtenu.
        hash_cache = self._doublons_scan_runner.hash_cache if self._doublons_scan_runner is not None else None
        self._end_doublons_scan()
        if self._doublons_root is not None:
            try:
                doublons_scan_cache.save_scan_cache(self._doublons_root, result)
            except OSError:
                pass
        if hash_cache is not None:
            try:
                doublons_scan_cache.save_hash_cache(hash_cache)
            except OSError:
                pass
        self._display_doublons_results(result)

    def _display_doublons_results(self, result) -> None:
        """Affiche `result` sur l'écran de résultats -- partagé entre une
        analyse fraîche (`_on_doublons_scan_finished`, qui sauvegarde
        d'abord le cache) et une reprise (`_on_doublons_resume_finished`,
        qui ne resauvegarde jamais le cache déjà sur disque, § demandé :
        « ne jamais obliger à relancer une analyse »)."""
        self._doublons_scan_result = result
        self._doublons_results_screen.set_simulation_mode(self._app_config.doublons_simulation_mode)
        if self._doublons_root is not None:
            self._doublons_destination = self._default_doublons_destination(self._doublons_root)
            self._doublons_results_screen.set_destination(self._doublons_destination)
            self._update_doublons_cross_volume_warning()
        undo_available = has_pending_journal_entries(self._doublons_known_destinations())
        self._doublons_results_screen.set_undo_available(undo_available)
        self._doublons_results_screen.set_results(result)
        self._root_stack.setCurrentWidget(self._doublons_results_screen)

    def _default_doublons_destination(self, root: str) -> str:
        """`AppConfig.doublons_last_destination` (§5 demandé : « mémoriser
        la dernière destination choisie comme proposition suivante »)
        quand il reste valable pour `root` -- `doublons.move.default_
        destination(root)` (`root/_doublons`) sinon, y compris si la
        valeur mémorisée est refusée pour ce dossier précis (ex. mémorisée
        pour un tout autre dossier analysé lors d'une session
        précédente, désormais à l'intérieur de celui-ci par coïncidence)."""
        remembered = self._app_config.doublons_last_destination
        if remembered:
            try:
                check_destination_allowed(root, remembered)
                return remembered
            except (DestinationInsideRootNotAllowed, DestinationIsFilesystemRoot, DestinationNotWritable):
                pass
        return default_doublons_destination(root)

    def _update_doublons_cross_volume_warning(self) -> None:
        if self._doublons_root is None or self._doublons_destination is None:
            return
        cross_volume = is_cross_volume_destination(self._doublons_root, self._doublons_destination)
        self._doublons_results_screen.set_cross_volume_warning(cross_volume)

    def _doublons_known_destinations(self) -> List[str]:
        """Destinations à balayer pour « Tout annuler » (§4 demandé
        explicitement : « pour que Tout annuler retrouve le journal même
        si la destination a changé ») -- la destination de la session en
        cours, l'historique mémorisé (`AppConfig.doublons_recent_
        destinations`, mis à jour uniquement lors d'un déplacement réel,
        `_on_doublons_move_confirmed`) et, par prudence, la destination
        par défaut du dossier actuellement analysé même si elle n'a
        jamais été explicitement choisie ni utilisée pour de vrai."""
        destinations = list(self._app_config.doublons_recent_destinations)
        if self._doublons_destination and self._doublons_destination not in destinations:
            destinations.insert(0, self._doublons_destination)
        if self._doublons_root is not None:
            default = default_doublons_destination(self._doublons_root)
            if default not in destinations:
                destinations.append(default)
        return destinations

    def _on_doublons_destination_chosen(self, path: str) -> None:
        if self._doublons_root is None:
            return
        try:
            check_destination_allowed(self._doublons_root, path)
        except DestinationInsideRootNotAllowed:
            QMessageBox.warning(self, tr("app_title"), friendly_error_message("DESTINATION_INSIDE_ROOT"))
            return
        except DestinationIsFilesystemRoot:
            QMessageBox.warning(self, tr("app_title"), friendly_error_message("DESTINATION_FILESYSTEM_ROOT"))
            return
        except DestinationNotWritable:
            QMessageBox.warning(self, tr("app_title"), friendly_error_message("DESTINATION_NOT_WRITABLE"))
            return
        self._doublons_destination = path
        # Mémorisé tout de suite (§5) -- pas seulement au moment d'un
        # déplacement réel (`AppConfig.doublons_recent_destinations`,
        # mis à jour séparément, seulement pour un déplacement réel).
        self._app_config.doublons_last_destination = path
        app_config.save_config(self._app_config)
        self._doublons_results_screen.set_destination(path)
        self._update_doublons_cross_volume_warning()

    def _on_doublons_scan_cancelled(self) -> None:
        # Les empreintes déjà calculées avant l'annulation restent utiles à
        # la prochaine analyse -- sauvegardées ici aussi, même best-effort
        # qu'une analyse menée à son terme (`_on_doublons_scan_finished`).
        hash_cache = self._doublons_scan_runner.hash_cache if self._doublons_scan_runner is not None else None
        self._end_doublons_scan()
        if hash_cache is not None:
            try:
                doublons_scan_cache.save_hash_cache(hash_cache)
            except OSError:
                pass
        self._root_stack.setCurrentWidget(self._doublons_folder_screen)

    def _on_doublons_resume_requested(self) -> None:
        if self._doublons_resume_cache is None:
            return
        self._home.set_busy(True)
        self._assisted_landing.set_busy(True)
        self._doublons_resume_runner = DoublonsResumeRunner(self._doublons_resume_cache, parent=self)
        self._doublons_resume_runner.finished_resume.connect(self._on_doublons_resume_finished)
        self._doublons_resume_runner.error.connect(self._on_doublons_resume_error)
        self._doublons_resume_runner.start()

    def _end_doublons_resume(self) -> None:
        self._home.set_busy(False)
        self._assisted_landing.set_busy(False)
        self._doublons_resume_runner = None

    def _on_doublons_resume_finished(self, result, removed: int) -> None:
        cached = self._doublons_resume_cache
        self._end_doublons_resume()
        if cached is None:
            return
        self._doublons_root = cached.root
        if removed > 0:
            QMessageBox.information(
                self, tr("app_title"), tr("doublons_resume_files_removed_notice", count=removed)
            )
        self._display_doublons_results(result)

    def _on_doublons_resume_error(self, code: str, msg: str) -> None:
        self._end_doublons_resume()
        self._last_error_code = code
        self._last_error_msg = msg
        QMessageBox.warning(self, tr("app_title"), friendly_error_message(code))
        self._root_stack.setCurrentWidget(self._doublons_folder_screen)

    def _on_doublons_scan_error(self, code: str, msg: str) -> None:
        self._end_doublons_scan()
        self._last_error_code = code
        self._last_error_msg = msg
        QMessageBox.warning(self, tr("app_title"), friendly_error_message(code))
        self._root_stack.setCurrentWidget(self._doublons_folder_screen)

    def _on_doublons_move_requested(self, units: List[Unit]) -> None:
        self._pending_doublons_units = units
        self._confirm_move_doublons_dialog.set_units(units, self._app_config.doublons_simulation_mode)
        self._update_doublons_confirm_dialog_destination_display()
        self._confirm_move_doublons_dialog.open()

    def _update_doublons_confirm_dialog_destination_display(self) -> None:
        """Signalé explicitement : « la fenêtre de confirmation doit
        afficher la destination en évidence... avec les avertissements
        associés (autre disque, espace libre à destination) ». Réutilise
        les mêmes règles que l'écran de résultats (`check_destination_
        allowed`/`is_cross_volume_destination`), jamais une seconde
        logique parallèle -- seule la présentation diffère (une fenêtre de
        confirmation plutôt qu'un bandeau permanent)."""
        if self._doublons_root is None or self._doublons_destination is None:
            return
        destination = self._doublons_destination
        self._confirm_move_doublons_dialog.set_destination(destination)
        self._confirm_move_doublons_dialog.set_cross_volume_warning(
            is_cross_volume_destination(self._doublons_root, destination)
        )
        valid = True
        try:
            check_destination_allowed(self._doublons_root, destination)
        except (DestinationInsideRootNotAllowed, DestinationIsFilesystemRoot, DestinationNotWritable):
            valid = False
        self._confirm_move_doublons_dialog.set_destination_valid(valid)
        total_bytes = sum(unit.total_size_bytes for unit in self._pending_doublons_units)
        free_bytes = free_space_at_destination(destination)
        insufficient = free_bytes is not None and free_bytes < total_bytes
        self._confirm_move_doublons_dialog.set_space_warning(
            insufficient, _format_size(free_bytes) if free_bytes is not None else ""
        )
        # § demandé explicitement, point 6 : annoncé ici, avant même la
        # validation -- `move_duplicates` refuse pour de vrai le lot
        # entier au moment de l'exécuter si la destination est
        # positivement FAT (autorité réelle), ceci reste purement
        # informatif, comme l'avertissement d'espace ci-dessus.
        oversized_count = 0
        if is_fat_filesystem(destination_filesystem_kind(destination)):
            oversized_count = len(fat_oversized_members(self._pending_doublons_units))
        self._confirm_move_doublons_dialog.set_fat_warning(oversized_count)

    def _on_doublons_confirm_dialog_destination_chosen(self, path: str) -> None:
        """« Changer… » directement dans la fenêtre de confirmation --
        réutilise `_on_doublons_destination_chosen` tel quel (mêmes refus,
        même mémorisation) puis rafraîchit l'affichage de cette fenêtre
        précise, qui reste ouverte (§ demandé : « ne jamais obliger à
        relancer une analyse » -- changer la destination ne relance rien)."""
        self._on_doublons_destination_chosen(path)
        self._update_doublons_confirm_dialog_destination_display()

    def _on_doublons_move_confirmed(self) -> None:
        if self._doublons_root is None or not self._pending_doublons_units:
            return
        destination = self._doublons_destination or default_doublons_destination(self._doublons_root)
        # Barre de progression réelle (signalement utilisateur -- 1900
        # fichiers sur 1272 groupes, règle §2 n°5) -- le total est connu
        # d'avance (§ garde-fou 1, jamais un membre isolé d'une unité
        # liée), donc déterminée dès le départ.
        total = sum(len(unit.members) for unit in self._pending_doublons_units)
        self._doublons_move_progress_screen.set_progress(0, total)
        self._root_stack.setCurrentWidget(self._doublons_move_progress_screen)
        if not self._app_config.doublons_simulation_mode:
            # Mémorisé avant même le résultat -- une interruption en cours
            # de lot laisse quand même un journal exploitable à cette
            # destination (écriture au fil de l'eau, move.py), qui doit
            # rester trouvable par « Tout annuler » (§4) même si le lot ne
            # se termine pas. Jamais en simulation : rien n'y est écrit.
            app_config.record_doublons_destination(self._app_config, destination)
            app_config.save_config(self._app_config)
        self._doublons_move_runner = DoublonsMoveRunner(
            self._doublons_root,
            self._pending_doublons_units,
            self._app_config.doublons_simulation_mode,
            destination=destination,
            parent=self,
        )
        self._doublons_move_runner.progress.connect(self._doublons_move_progress_screen.set_progress)
        self._doublons_move_runner.error.connect(self._on_doublons_move_error)
        self._doublons_move_runner.finished_move.connect(self._on_doublons_move_finished)
        self._doublons_move_runner.file_error_confirmation_needed.connect(
            self._on_doublons_move_file_error_confirmation_needed
        )
        self._doublons_move_runner.start()

    def _on_doublons_move_cancel_requested(self) -> None:
        if self._doublons_move_runner is not None:
            self._doublons_move_runner.cancel()

    def _on_doublons_move_file_error_confirmation_needed(self, exc) -> None:
        """§ demandé explicitement, point 4 : « proposer de continuer en
        ignorant ce fichier » -- même fenêtre que les analyses à risque
        (`DoublonsRiskConfirmDialog`), titre propre, message construit à
        partir du `MoveFileFailed` (fichier en cause, raison traduite,
        « copie réussie » explicite si seule la suppression de l'original
        a échoué, § point 3)."""
        self._doublons_file_error_dialog.set_title(tr("doublons_file_error_title"))
        self._doublons_file_error_dialog.set_message(doublons_move_file_error_message(exc))
        self._doublons_file_error_dialog.open()

    def _on_doublons_move_file_error_confirmed(self) -> None:
        """« Continuer » -- ignore ce fichier précis et poursuit avec les
        suivants ; ce qui a déjà été déplacé le reste, jamais annulé."""
        if self._doublons_move_runner is not None:
            self._doublons_move_runner.resume_after_file_error_confirmation(True)

    def _on_doublons_move_file_error_cancelled(self) -> None:
        """« Annuler » -- arrête le lot entier à partir de ce fichier."""
        if self._doublons_move_runner is not None:
            self._doublons_move_runner.resume_after_file_error_confirmation(False)

    def _on_doublons_move_error(self, code: str, msg: str) -> None:
        # Lu ici, avant que `_on_doublons_move_finished` ne remette
        # `_doublons_move_runner` à `None` -- § bug corrigé, signalé
        # explicitement : ce que le worker sait déjà (ce qui a réellement
        # bougé, quel fichier précis a échoué) doit servir à afficher un
        # résultat précis, jamais relancer une analyse complète à la
        # place.
        self._last_error_code = code
        self._last_error_msg = msg
        runner = self._doublons_move_runner
        if runner is not None:
            self._doublons_move_error_moved_units = list(runner.moved_units)
            self._doublons_move_error_file_failure = runner.last_file_error
            self._doublons_move_error_skipped_count = len(runner.skipped)
        else:
            self._doublons_move_error_moved_units = []
            self._doublons_move_error_file_failure = None
            self._doublons_move_error_skipped_count = 0

    def _on_doublons_move_finished(self, ok: bool) -> None:
        self._doublons_move_runner = None
        self._pending_doublons_units = []
        if ok:
            # Succès complet -- relance un scan frais, reflète l'état réel
            # du dossier plutôt qu'une mise à jour partielle de
            # l'affichage précédent (comportement inchangé).
            if self._doublons_root is not None:
                self._start_doublons_scan(self._doublons_root)
            return

        # § bug corrigé, signalé explicitement : « après une erreur de
        # déplacement, ne jamais relancer l'analyse. Revenir aux
        # résultats, sélection intacte, en retirant les fichiers déjà
        # déplacés avec succès. » -- s'applique à toute interruption
        # (annulation, échec système, vérification ratée), pas seulement
        # un échec système précis : ce qui a déjà été déplacé reste de
        # toute façon dans le journal (`move.py`, écriture au fil de
        # l'eau), restaurable via « Tout annuler », jamais perdu, et une
        # nouvelle analyse d'une carte de 128 Go serait de toute façon
        # bien plus lente qu'un simple retrait des unités déjà déplacées.
        moved_units = self._doublons_move_error_moved_units
        file_failure = self._doublons_move_error_file_failure
        skipped_count = self._doublons_move_error_skipped_count
        self._doublons_move_error_moved_units = []
        self._doublons_move_error_file_failure = None
        self._doublons_move_error_skipped_count = 0

        if moved_units:
            self._doublons_results_screen.remove_units(moved_units)

        if self._last_error_code == "PARTIAL_MOVE_COMPLETED":
            message = doublons_partial_move_message(len(moved_units), skipped_count)
        elif file_failure is not None:
            message = doublons_move_file_error_message(file_failure)
        else:
            message = friendly_error_message(self._last_error_code or "")
        QMessageBox.warning(self, tr("app_title"), message)
        self._root_stack.setCurrentWidget(self._doublons_results_screen)

    def _on_doublons_export_requested(self) -> None:
        if self._doublons_scan_result is None or self._doublons_root is None:
            return
        default_dir = Path.home() / "Documents" / "R36S Studio" / "Doublons"
        default_name = f"rapport_{datetime.now():%Y-%m-%d_%H-%M}.txt"
        path, _ = QFileDialog.getSaveFileName(
            self, tr("doublons_export_button"), str(default_dir / default_name), "Texte (*.txt)"
        )
        if not path:
            return
        report = build_report(self._doublons_scan_result, self._doublons_root)
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(report, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, tr("app_title"), str(exc))

    def _on_doublons_undo_requested(self) -> None:
        self._confirm_undo_doublons_dialog.open()

    def _on_doublons_undo_confirmed(self) -> None:
        self._doublons_results_screen.setEnabled(False)
        self._doublons_undo_runner = DoublonsUndoRunner(self._doublons_known_destinations(), parent=self)
        self._doublons_undo_runner.error.connect(self._on_doublons_undo_error)
        self._doublons_undo_runner.finished_undo.connect(self._on_doublons_undo_finished)
        self._doublons_undo_runner.start()

    def _on_doublons_undo_error(self, code: str, msg: str) -> None:
        self._last_error_code = code
        self._last_error_msg = msg

    def _on_doublons_undo_finished(self, result) -> None:
        self._doublons_results_screen.setEnabled(True)
        self._doublons_undo_runner = None
        if result is not None and result.conflicts:
            # Signalé mais non bloquant -- chaque entrée en conflit reste
            # dans le journal pour un futur essai (undo.py), rien n'est
            # perdu.
            QMessageBox.warning(
                self, tr("app_title"), tr("doublons_undo_conflicts_warning", count=len(result.conflicts))
            )
        if self._doublons_root is not None:
            self._start_doublons_scan(self._doublons_root)

    # --- mises à jour (update_check.py) -----------------------------------

    def start_update_check(self) -> None:
        """Au plus une fois par jour, sur un thread séparé ; silence total
        si rien de neuf ou hors ligne (`UpdateCheckRunner`). Appelée par
        `app.py::run`, jamais par le constructeur (tests sans réseau)."""
        today = datetime.now().date().isoformat()
        if not self._app_config.check_updates or self._app_config.last_update_check == today:
            return
        self._app_config.last_update_check = today
        app_config.save_config(self._app_config)
        self._update_runner = UpdateCheckRunner(parent=self)
        self._update_runner.update_available.connect(self._on_update_available)
        self._update_runner.start()

    def _on_update_available(self, tag: str, notes: str) -> None:
        self._pending_update = (tag, notes)
        self._app_config.latest_update_tag = tag
        self._app_config.latest_update_notes = notes
        app_config.save_config(self._app_config)
        self._log_panel.append_log(f"[mise à jour] {tag} disponible")
        self._show_update_badge_if_idle()

    def _show_update_badge_if_idle(self) -> None:
        """Jamais pendant une opération disque : rappelée à la fin de chaque
        opération (`_on_worker_finished`)."""
        if self._pending_update is None or self._log_panel.is_operation_active():
            return
        for controls in (self._home.update_controls, self._assisted_landing.update_controls):
            controls.badge.setVisible(self._app_config.check_updates)

    def _on_update_check_toggled(self, checked: bool) -> None:
        self._app_config.check_updates = checked
        app_config.save_config(self._app_config)
        for controls in (self._home.update_controls, self._assisted_landing.update_controls):
            controls.set_checked(checked)
            controls.badge.setVisible(False)
        if checked:
            self._show_update_badge_if_idle()
            self.start_update_check()

    def _open_update_dialog(self) -> None:
        if self._pending_update is None:
            return
        dialog = UpdateDialog(*self._pending_update, parent=self)
        dialog.download_requested.connect(lambda: webbrowser.open(update_check.STORE_URL))
        dialog.open()

    def _on_language_selected(self, code: str) -> None:
        """Choix de langue depuis l'un des deux accueils (i18n.py) --
        mémorisé comme `ui_mode`, appliqué au prochain démarrage seulement :
        chaque écran a lu `tr()` à sa construction, et reconstruire la
        fenêtre en cours de route risquerait d'orpheliner un job ou la
        session d'autorisation macOS. Le message parle la langue choisie,
        pas celle encore affichée."""
        if code == self._app_config.language:
            return
        self._app_config.language = code
        app_config.save_config(self._app_config)
        self._home.set_language(code)
        self._assisted_landing.set_language(code)
        QMessageBox.information(
            self, tr_in(code, "language_restart_title"), tr_in(code, "language_restart_message")
        )

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

    def _open_consoles_diverses(self) -> None:
        """Bouton discret « Consoles diverses », présent sur les deux
        accueils (expert et assisté) -- bascule vers l'écran du package
        isolé `consoles_diverses/`, sans jamais modifier `ui_mode` : ce
        n'est pas un changement de mode, juste une section indépendante.
        Retour à l'accueil habituel via `back_requested`
        (`_show_startup_screen`, câblé dans `_wire_signals`). Rafraîchit la
        configuration réseau à chaque ouverture (adresse serveur/clé de
        licence ont pu changer depuis la dernière visite, via la fenêtre
        de réglages)."""
        self._consoles_diverses_screen.set_network_config(
            consoles_diverses_settings_store.adresse_serveur(),
            self._app_config.consoles_diverses_licence_key,
        )
        self._root_stack.setCurrentWidget(self._consoles_diverses_screen)

    # --- Outil « Console Android » (android/, étape 1, docs/android-
    # adb.md) -- détection en USB via adb, jamais d'élévation de
    # privilèges (contrairement au pipeline backup/flash/worker élevé
    # ci-dessus) : ces méthodes ne font qu'orchestrer les threads dédiés
    # (`android_runner.py`) et traduire leurs résultats pour `AndroidScreen`,
    # qui ne connaît elle-même ni adb ni le réseau. ----------------------

    def _open_tri_screen(self) -> None:
        """Tuile « Ranger mes jeux » (docs/tri-roms.md). Le firmware choisi
        pour le flash est proposé comme cible, toujours remplaçable."""
        self._tri_screen.set_default_firmware(self._app_config.firmware)
        self._tri_screen.show_choose_page()
        self._root_stack.setCurrentWidget(self._tri_screen)

    def _open_android_screen(self) -> None:
        self._root_stack.setCurrentWidget(self._android_screen)
        self._start_android_detection()

    def _start_android_detection(self) -> None:
        """Point d'entrée unique de (re)détection -- adb déjà disponible
        (PATH ou déjà téléchargé par l'app, `resolve_adb_path`) : lance la
        détection directement ; sinon affiche l'écran de consentement au
        téléchargement (brief § adb : jamais de téléchargement avant un
        accord explicite) et récupère la taille annoncée en parallèle."""
        adb_path = android_adb.resolve_adb_path()
        if adb_path is None:
            self._android_screen.show_need_consent(android_platform_tools.platform_tools_url())
            size_runner = AndroidPlatformToolsSizeRunner(self)
            size_runner.finished_size.connect(self._on_android_platform_tools_size_ready)
            size_runner.finished.connect(size_runner.deleteLater)
            size_runner.start()
            return

        self._android_screen.show_detecting()
        runner = AndroidDetectRunner(adb_path, self)
        runner.finished_detect.connect(self._on_android_detect_finished)
        runner.finished.connect(runner.deleteLater)
        self._android_detect_runner = runner
        runner.start()

    def _on_android_detect_finished(self, result: DetectionResult) -> None:
        self._android_detect_runner = None
        self._android_screen.show_detection_result(result)

    def _on_android_platform_tools_size_ready(self, size_bytes) -> None:
        self._android_screen.set_platform_tools_size(size_bytes)

    def _on_android_consent_download_requested(self) -> None:
        self._android_screen.show_downloading()
        runner = AndroidPlatformToolsDownloadRunner(self)
        runner.progress.connect(self._android_screen.set_download_progress)
        runner.error.connect(self._on_android_download_error)
        runner.finished_download.connect(self._on_android_download_finished)
        runner.finished.connect(runner.deleteLater)
        self._android_download_runner = runner
        runner.start()

    def _on_android_cancel_download_requested(self) -> None:
        if self._android_download_runner is not None:
            self._android_download_runner.cancel()

    def _on_android_download_error(self, code: str, message: str) -> None:
        if code == "CANCELLED":
            # Annulation volontaire (bouton Annuler) -- retour silencieux à
            # l'écran de consentement, jamais un message d'erreur pour une
            # action demandée par l'utilisateur lui-même.
            self._android_screen.show_need_consent(android_platform_tools.platform_tools_url())
            return
        self._android_screen.show_download_error(tr("android_download_error"))

    def _on_android_download_finished(self, ok: bool, adb_path: str) -> None:
        self._android_download_runner = None
        if not ok:
            return  # `_on_android_download_error` a déjà affiché le message
        self._start_android_detection()

    def _on_android_search_catalog_requested(self, reference: str) -> None:
        """Le brief distingue « Trouvée » et « Non trouvée -- proposer un
        bouton pour lancer la recherche IA », comme deux étapes séparées --
        mais le contrat réel du serveur (`POST /recherche`, consoles_
        diverses/CLAUDE.md) fait déjà les deux en un seul appel : `statut`
        vaut `trouve_dans_catalogue`, `trouve_par_ia` ou `aucune_
        information_trouvee`. Un seul bouton suffit donc ici -- jamais de
        second appel « IA » distinct, qui n'existe pas côté serveur."""
        reference = reference.strip()
        if not reference:
            return
        self._android_screen.show_catalog_searching()
        server_url = consoles_diverses_settings_store.adresse_serveur()
        licence_key = self._app_config.consoles_diverses_licence_key
        # URL/clé venant strictement de la même source que `_open_consoles_
        # diverses` (`consoles_diverses_settings_store.adresse_serveur()`/
        # `AppConfig.consoles_diverses_licence_key`) -- pas de configuration séparée pour cet écran,
        # vérifié par un test dédié.
        self._android_last_search_url = _android_catalog_search_url(server_url)
        _journaliser_android_recherche(self._android_last_search_url, reference)
        runner = ConsoleSearchRunner(reference, server_url, licence_key)
        runner.finished_ok.connect(self._on_android_search_finished)
        runner.error.connect(self._on_android_search_error)
        runner.finished.connect(runner.deleteLater)
        self._android_search_runner = runner
        runner.start()

    def _on_android_search_finished(self, resultat: ResultatRecherche) -> None:
        self._android_search_runner = None
        if resultat.statut == "aucune_information_trouvee" or resultat.console is None:
            self._android_screen.show_catalog_not_found()
            return
        self._android_screen.show_catalog_found(resultat.console)

    def _on_android_search_error(self, code: str, message_serveur: str) -> None:
        self._android_search_runner = None
        _journaliser_android_erreur_recherche(self._android_last_search_url, code, message_serveur)
        self._android_screen.show_catalog_error(consoles_diverses_friendly_error_message(code, message_serveur))

    def _on_web_requested(self) -> None:
        """Tuile personnelle « Web » (config.py::personal_web_url, jamais
        distribuée à un client) -- relit la variable d'environnement au
        clic plutôt que de faire confiance à un état capturé au démarrage
        (défense en profondeur : le même contrôle a déjà décidé si la
        tuile est même visible, `set_web_tile_visible`). Ouvre dans le
        navigateur par défaut de l'OS -- jamais QtWebEngine, aucune
        nouvelle dépendance."""
        url = app_config.personal_web_url()
        if url is None:
            print("[Web] R36S_STUDIO_WEB_URL absente ou non https -- ouverture refusée.", file=sys.stderr)
            return
        QDesktopServices.openUrl(QUrl(url))

    def _on_consoles_diverses_settings_requested(self) -> None:
        self._consoles_diverses_settings_dialog.set_values(self._app_config.consoles_diverses_licence_key)
        self._consoles_diverses_settings_dialog.open()

    def _on_consoles_diverses_settings_saved(self, licence_key: str) -> None:
        # `.strip()` : un copier-coller laisse souvent un espace ou un retour
        # à la ligne invisible dans un champ masqué (bug réel, clé refusée).
        self._app_config.consoles_diverses_licence_key = licence_key.strip()
        app_config.save_config(self._app_config)
        self._consoles_diverses_screen.set_network_config(
            consoles_diverses_settings_store.adresse_serveur(),
            self._app_config.consoles_diverses_licence_key,
        )

    def _start_wizard(self) -> None:
        self._app_config.ui_mode = "assisted"
        app_config.save_config(self._app_config)
        # Bug corrigé, confirmé sur du vrai matériel : un `_prepare_card_
        # candidate`/`_assisted_ad_hoc_active` resté vrai d'un précédent
        # passage par « Préparer une carte avec cette sauvegarde » (§4.3,
        # ad-hoc) sans retour explicite à l'accueil détournait le bouton
        # Continuer/Actualiser du vrai parcours guidé
        # (`_on_wizard_continue`/`_on_wizard_refresh_requested` routent
        # tous deux sur ces mêmes champs) -- la fenêtre Confirmation
        # s'ouvrait alors avec la carte de l'ancien sondage ad-hoc plutôt
        # que la carte cible réellement détectée à l'étape 3, court-
        # circuitant au passage la vérification d'empreinte (§ pré-vol
        # n°3). Ces deux flux sont censés être mutuellement exclusifs
        # (`_wizard_active`/`_assisted_ad_hoc_active`) : démarrer le vrai
        # parcours doit donc repartir d'un état ad-hoc propre, quel que
        # soit ce qui a été laissé derrière, comme `_cancel_wizard`/
        # `_on_assisted_ad_hoc_return_home` le font déjà en sens inverse.
        if self._prepare_card_poll_timer.isActive():
            self._prepare_card_poll_timer.stop()
        self._prepare_card_candidate = None
        self._assisted_ad_hoc_active = False
        self._wizard_flow.reset()
        self._wizard_active = True
        self._wizard_source_device = None
        self._wizard_source_fingerprint = None
        self._wizard_target_device = None
        self._wizard_source_ejected = None
        self._wizard_source_eject_error_msg = None
        self._wizard_backup_kind = None
        self._wizard_estimated_backup_bytes = None
        self._wizard_last_poll_diagnostic = None
        self._wizard_last_poll_monotonic = None
        self._wizard_poll_stall_warned = False
        self._pending_target_candidate = None
        self._same_card_unverified_dialog.close()
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
        self._stop_wizard_poll_timer()
        if self._prepare_card_poll_timer.isActive():
            self._prepare_card_poll_timer.stop()
        self._prepare_card_candidate = None
        self._pending_target_candidate = None
        self._same_card_unverified_dialog.close()
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
            self._start_wizard_poll_timer()
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
        jamais détecter la carte source comme si c'était la neuve.

        Bug corrigé, confirmé sur du vrai matériel : cette éjection
        automatique échouait *silencieusement* sur Windows (aucune ligne
        dans le journal entre la fin de la sauvegarde et la détection
        suivante, ni succès ni échec) -- `eject_device` s'exécutait dans le
        processus GUI, non élevé, et levait `ERROR_ACCESS_DENIED` avant
        même que le protocole JSON Lines ait quoi que ce soit à relayer.
        Passe désormais par `_start_eject` (worker élevé dédié, comme
        `backup`/`flash`) ; le résultat n'arrive qu'une fois ce worker
        terminé (`_on_wizard_source_eject_finished`), jamais de façon
        synchrone.

        ⚠️ **Quatrième signalement, non résolu, diagnostic ajouté en
        attendant** : sur du vrai matériel Windows, aucune ligne d'éjection
        n'apparaît du tout entre la fin de la sauvegarde système et la
        détection suivante -- ni succès ni échec -- alors que l'écran
        demande déjà « Branche la carte SD neuve ». Avant ce correctif, le
        tout premier `append_log` de cette fonction arrivait *après*
        `show_step(...)` et *avant* `_start_eject(...)` : une exception
        levée par l'un ou l'autre (ex. `self._wizard_source_device` valant
        `None`, `_start_eject` accédant alors à `device.path` sur `None`)
        remontait alors sans jamais toucher le journal -- exactement le
        symptôme rapporté (§4.4 : jamais un succès, ni une absence totale
        de trace, silencieux). Journalisé désormais en tout premier, avant
        même `show_step`, et le corps de la fonction est protégé par un
        `try/except` qui journalise explicitement toute exception plutôt
        que de la laisser disparaître -- si la ligne `wizard_ejecting_source`
        n'apparaît toujours pas au prochain test réel, cette fonction n'est
        simplement jamais atteinte (à chercher du côté de `_on_wizard_job_
        finished`/`_enter_wizard_job`, pas ici).

        **Éjection déjà chaînée dans le worker de l'étape 2, cas courant.**
        `_start_worker` ajoute `--eject-after` à la sauvegarde elle-même
        quand le parcours guidé est actif (§5) -- `_wizard_source_ejected`
        (rempli par `_on_wizard_source_eject_result`, reçu avant la fin de
        ce worker) vaut alors déjà `True` la plupart du temps : sauter
        directement au même point d'arrivée que l'ancien chemin
        (`_on_wizard_source_eject_finished`) évite une seconde invite UAC
        rien que pour cette éjection, en plus de celle déjà demandée pour
        la sauvegarde. `False` (l'éjection chaînée a échoué -- rapportée
        séparément, la sauvegarde elle-même a déjà réussi) ou `None`
        (signal jamais reçu) retombent sur le worker d'éjection dédié
        ci-dessous, exactement comme avant ce chaînage -- sans jamais
        avoir à refaire toute la sauvegarde pour ça."""
        if self._wizard_source_ejected:
            self._on_wizard_source_eject_finished(True, None, None)
            return
        refreshed = self._refresh_device_before_eject_retry(self._wizard_source_device)
        if refreshed is None:
            return
        self._wizard_source_device = refreshed
        self._log_panel.append_log(tr("wizard_ejecting_source"))
        try:
            title_key, instruction_key = _WIZARD_STEP_STRINGS[WizardJob.DETECT_TARGET]
            self._wizard_panel.show_step(tr(title_key), tr("wizard_ejecting_source"), can_continue=False)
            self._start_eject(self._wizard_source_device, self._on_wizard_source_eject_finished)
        except Exception as exc:
            self._last_error_code = "EJECT_FAILED"
            self._last_error_msg = str(exc)
            self._log_panel.finish_error(
                friendly_error_message(self._last_error_code),
                details=error_log_detail(self._last_error_code, self._last_error_msg),
            )
            self._wizard_panel.show_error()

    def _on_wizard_source_eject_finished(self, ok: bool, code: Optional[str], msg: Optional[str]) -> None:
        if not ok:
            self._last_error_code = code or "EJECT_FAILED"
            self._last_error_msg = msg or ""
            self._log_panel.finish_error(
                friendly_error_message(self._last_error_code),
                details=error_log_detail(self._last_error_code, self._last_error_msg),
            )
            self._wizard_panel.show_error()
            return
        title_key, instruction_key = _WIZARD_STEP_STRINGS[WizardJob.DETECT_TARGET]
        self._log_panel.append_log(tr("wizard_source_ejected"))
        self._wizard_panel.show_step(tr(title_key), tr(instruction_key), can_continue=False, show_refresh=True)
        self._wizard_panel.set_status(tr("wizard_status_waiting"))
        self._start_wizard_poll_timer()

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
        """Continuer avance la détection en cours (`DETECT_SOURCE` ou
        `DETECT_TARGET`, toutes deux activent ce bouton une fois une carte
        trouvée, §5 mode assisté) -- les autres étapes du parcours de
        clonage avancent d'elles-mêmes via `_on_wizard_job_finished` ou
        leurs propres boutons dédiés (`BackupKindDialog`).

        « Préparer une carte avec cette sauvegarde » (§4.3) partage ce
        même bouton/signal -- vérifié en tout premier, jamais
        `self._wizard_flow` pour ce cas précis (ce parcours ponctuel n'est
        pas un vrai `WizardJob`, y toucher corromprait le vrai parcours
        guidé). `not self._wizard_active` en garde-fou supplémentaire :
        bug corrigé, confirmé sur du vrai matériel -- `_prepare_card_
        candidate` resté vrai d'un passage précédent par ce parcours
        ponctuel (sans retour explicite à l'accueil) détournait sinon le
        Continuer du vrai parcours guidé vers cette branche, ouvrant la
        fenêtre Confirmation avec la mauvaise carte et court-circuitant la
        vérification d'empreinte (§ pré-vol n°3). `_start_wizard` réinitialise
        désormais cet état ad-hoc au démarrage -- cette condition reste en
        plus, en dernier recours, si un futur chemin laissait à nouveau
        cet état incohérent."""
        if self._prepare_card_candidate is not None and not self._wizard_active:
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

    def _start_wizard_poll_timer(self) -> None:
        """Point de passage unique pour (re)démarrer `_wizard_poll_timer`
        (§5 mode assisté) -- réinitialise `_wizard_last_poll_monotonic` au
        moment précis du redémarrage, jamais seulement à `_start_wizard`.

        Bug corrigé, rapporté sur du vrai matériel : `_check_wizard_poll_
        stall` (ci-dessous) déclenchait un faux positif systématique après
        toute pause légitime du minuteur -- une sauvegarde de 10 min
        (`_stop_wizard_poll_timer` pendant l'étape CREATE_IMAGE, aucun
        rapport avec un arrêt anormal) redémarrait le sondage à l'étape
        DETECT_TARGET en comparant au dernier sondage d'*avant* la pause,
        vieux de plusieurs centaines de secondes. Pire : le cycle « même
        carte, on continue d'attendre » de DETECT_TARGET (`_on_wizard_
        fingerprint_ready`, ci-dessous) arrête puis relance ce même
        minuteur à *chaque* carte retrouvée identique à la source -- une
        vérification d'empreinte (montage/démontage du BOOT) prenant
        rarement moins de quelques secondes, l'écart mesuré entre deux
        sondages consécutifs dépassait alors le seuil en boucle, noyant le
        journal d'un faux positif toutes les 6 à 12 s tant que la carte
        neuve n'était pas encore branchée -- un cas pourtant parfaitement
        normal (§5, l'utilisateur n'a simplement pas encore échangé les
        cartes).

        Journalise « Sondage automatique de la carte démarré. » une seule
        fois par vraie transition arrêté -> actif (jamais à chaque relance
        interne pendant l'attente, ci-dessus) -- rend visible dans le
        journal que le minuteur démarre bien, plutôt que de laisser
        deviner son état (bug rapporté : le sondage semblait ne jamais
        démarrer sur le binaire empaqueté, sans aucune trace pour le
        confirmer ou l'infirmer)."""
        if not self._wizard_poll_timer.isActive():
            self._log_panel.append_log(tr("wizard_poll_started"))
        self._wizard_poll_stall_warned = False
        self._wizard_last_poll_monotonic = time.monotonic()
        self._wizard_poll_timer.start()

    def _stop_wizard_poll_timer(self) -> None:
        """Symétrique de `_start_wizard_poll_timer` -- journalise l'arrêt
        une seule fois par vraie transition actif -> arrêté, jamais si le
        minuteur était déjà arrêté (`isActive()` évalué *avant* `.stop()`,
        qui est de toute façon un no-op sûr sur un minuteur déjà arrêté)."""
        if self._wizard_poll_timer.isActive():
            self._log_panel.append_log(tr("wizard_poll_stopped"))
        self._wizard_poll_timer.stop()

    def _check_wizard_poll_stall(self) -> None:
        """Chien de garde (voir la note `_WIZARD_POLL_STALL_THRESHOLD_
        SECONDS` ci-dessus) : si le sondage automatique semble être resté
        silencieux nettement plus longtemps que son intervalle normal
        (1,5 s) -- signe soit d'un arrêt du minuteur non détecté par la
        relecture de code, soit (confirmé en usage réel sur le binaire
        empaqueté) d'une énumération des disques anormalement lente sur
        cette machine (`_list_devices_with_diagnostics`, plusieurs
        secondes par appel côté Windows avant la consolidation en un seul
        appel PowerShell, `devices/windows.py::_LIST_DEVICES_COMMAND`) --
        relance le minuteur plutôt que de seulement le constater : un
        redémarrage explicite ne coûte rien si `_wizard_poll_timer`
        tournait déjà (`QTimer.start()` réarme simplement l'échéance), et
        corrige réellement le cas où il se serait arrêté sans que rien
        d'autre ne le relance.

        `_wizard_last_poll_monotonic` est mis à jour à chaque appel, y
        compris pendant un épisode de ralentissement -- une comparaison
        tick à tick, jamais ancrée sur l'instant d'avant le début de
        l'épisode (sans quoi le premier sondage qui retrouve un rythme
        normal semblerait, à tort, tout aussi en retard que les précédents).
        `_wizard_poll_stall_warned` évite de répéter la même ligne tant que
        l'épisode persiste -- remis à `False` dès qu'un sondage retrouve un
        rythme normal (branche `elapsed <= ...`). La relance ci-dessous
        appelle directement `.start()` sur le minuteur plutôt que
        `_start_wizard_poll_timer()` : cette dernière remettrait
        `_wizard_poll_stall_warned` à `False` inconditionnellement, ce qui
        rouvrirait la porte à répéter la même ligne dès le tick suivant si
        le ralentissement persiste -- exactement le défaut rapporté."""
        now = time.monotonic()
        previous = self._wizard_last_poll_monotonic
        self._wizard_last_poll_monotonic = now
        if previous is None:
            return
        elapsed = now - previous
        if elapsed <= _WIZARD_POLL_STALL_THRESHOLD_SECONDS:
            self._wizard_poll_stall_warned = False
            return
        if not self._wizard_poll_stall_warned:
            self._log_panel.append_log(tr("wizard_poll_stall_detected", seconds=round(elapsed)))
            self._wizard_poll_stall_warned = True
        self._wizard_poll_timer.start()

    def _on_wizard_poll(self) -> None:
        self._check_wizard_poll_stall()
        devices, rejected_lines = self._list_devices_with_diagnostics()
        self._log_wizard_detection_diagnostic(len(devices), rejected_lines)

        if len(devices) > 1:
            # Plusieurs cartes candidates (ex. un disque USB qui passe le
            # filtre en plus de la carte SD, §4.2) : avant ce correctif,
            # `candidate` retombait à `None`, indiscernable de « aucune
            # carte » -- proposer un choix plutôt que de rester bloqué en
            # silence, comme le mode expert le fait déjà via cette même
            # fenêtre.
            self._stop_wizard_poll_timer()
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
        self._stop_wizard_poll_timer()
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
        « Préparer une carte ». `and not self._wizard_active` : même
        garde-fou supplémentaire qu'`_on_wizard_continue` -- un sondage
        ad-hoc mal routé pendant l'étape 3 du vrai parcours guidé (carte
        source encore branchée, éjection en échec) contournerait sinon la
        vérification d'empreinte propre à cette étape (§ pré-vol n°3),
        `_on_prepare_card_poll` n'en ayant aucune notion."""
        if self._assisted_ad_hoc_active and not self._wizard_active:
            if not self._prepare_card_poll_timer.isActive():
                self._prepare_card_poll_timer.start()
            self._on_prepare_card_poll()
            return
        self._start_wizard_poll_timer()
        self._on_wizard_poll()

    def _on_wizard_fingerprint_ready(
        self, job: WizardJob, candidate: Device, fingerprint: Optional[str]
    ) -> None:
        if job == WizardJob.DETECT_SOURCE:
            self._stop_wizard_poll_timer()  # trouvé -> plus besoin de reinterroger
            self._wizard_source_device = candidate
            self._wizard_source_fingerprint = fingerprint
            self._wizard_panel.set_status(tr("wizard_status_device_found", display=candidate.display))
            self._wizard_panel.set_can_continue(True)
        elif job == WizardJob.DETECT_TARGET:
            if is_same_card(self._wizard_source_fingerprint, fingerprint):
                self._wizard_panel.set_status(tr("wizard_status_same_card"))
                self._wizard_panel.set_can_continue(False)
                self._start_wizard_poll_timer()  # continue d'attendre une vraie carte différente
                return
            # Bug corrigé, confirmé sur du vrai matériel : `is_same_card`
            # seule ne peut plus rien affirmer quand la source n'a pas
            # d'empreinte (carte vierge ou firmware non reconnu, § pré-vol
            # n°3) -- et sur Windows, certains lecteurs de carte gardent le
            # même chemin de périphérique quelle que soit la carte insérée
            # (un repli tenté sur le chemin bloquait donc indéfiniment,
            # sans issue, sur ce type de lecteur -- retiré). Une différence
            # de taille reste une preuve positive de carte différente
            # (une carte ne change jamais de capacité) ; une taille
            # identique, elle, ne prouve jamais rien (cas courant en
            # préparant plusieurs consoles avec des cartes du même
            # modèle) -- garde-fou le plus critique du parcours (écrire
            # par erreur sur la carte source détruirait la seule copie
            # fonctionnelle de la console), donc une confirmation
            # explicite plutôt qu'un signal automatique supplémentaire.
            source_device = self._wizard_source_device
            source_size = source_device.size_bytes if source_device is not None else None
            if fingerprint is None and not size_proves_different_card(source_size, candidate.size_bytes):
                self._stop_wizard_poll_timer()
                self._pending_target_candidate = candidate
                self._wizard_panel.set_status(tr("wizard_status_confirmation_needed"))
                self._same_card_unverified_dialog.set_device(candidate)
                self._same_card_unverified_dialog.open()
                return
            self._stop_wizard_poll_timer()
            self._wizard_target_device = candidate
            self._wizard_panel.set_status(tr("wizard_status_device_found", display=candidate.display))
            self._wizard_panel.set_can_continue(True)

    def _on_same_card_unverified_confirmed(self) -> None:
        """L'utilisateur a explicitement certifié que la carte détectée à
        l'étape 3 est bien différente de la carte source (`SameCard
        UnverifiedDialog`, § pré-vol n°3) -- accepte alors la carte comme
        `_on_wizard_fingerprint_ready` l'aurait fait directement si un
        signal automatique (empreinte ou taille) avait pu trancher."""
        self._same_card_unverified_dialog.close()
        candidate = self._pending_target_candidate
        self._pending_target_candidate = None
        if candidate is None:
            return
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
        self._whole_card = False
        used_bytes = sf3000_clone.whole_card_used_bytes(self._file_path, self._device)
        if used_bytes is not None:
            self._use_whole_card_automatically(used_bytes)
        self._confirm_dialog.set_device(self._device)
        self._confirm_dialog.open()

    def _on_wizard_job_finished(self, ok: bool) -> None:
        job = self._wizard_flow.current_job()
        if not ok:
            friendly = friendly_error_message(self._last_error_code or "")
            self._log_panel.finish_error(friendly, details=error_log_detail(self._last_error_code, self._last_error_msg))
            self._wizard_panel.show_error()
            return

        if job == WizardJob.CREATE_IMAGE:
            self._log_panel.append_log(tr("wizard_image_created_log", path=self._file_path))

        self._log_panel.finish_success(self._success_message(), allow_eject=False, reveal_path=None)

        self._wizard_flow.mark_done(job)
        self._enter_wizard_job(self._wizard_flow.current_job())

    # --- étape 5 : éjection, via le worker élevé comme _perform_eject --------

    def _refresh_device_before_eject_retry(self, device: Optional[Device]) -> Optional[Device]:
        """Reconfirme la carte à éjecter avant chaque tentative -- bug
        corrigé, confirmé sur du vrai matériel : une deuxième tentative
        après une invite UAC refusée réutilisait tel quel l'ancien chemin
        Windows (`\\\\.\\PhysicalDriveN`) de la première -- Windows a pu le
        libérer/renuméroter entre-temps, rejeté ensuite par le worker élevé
        lui-même comme introuvable (`DEVICE_NOT_ALLOWED`,
        `_resolve_device_or_report`) sur un chemin déjà mort. Un seul
        candidat détecté -> utilisé directement, y compris au tout premier
        appel (sans effet sur le cas normal, qui retrouve simplement la
        même carte) -- l'éjection ne modifie aucune donnée, contrairement à
        une écriture, donc aucune vérification d'empreinte supplémentaire
        n'est nécessaire ici (§ pré-vol, réservée aux écritures). Zéro ou
        plusieurs candidates -> message explicite déjà journalisé plutôt
        qu'une tentative sur un chemin peut-être mort."""
        devices = self._list_safe_devices()
        if len(devices) == 1:
            return devices[0]
        self._last_error_code = "DEVICE_NOT_ALLOWED"
        self._last_error_msg = tr("eject_multiple_cards") if devices else tr("eject_card_not_found")
        self._log_panel.finish_error(
            friendly_error_message(self._last_error_code), details=self._last_error_msg
        )
        self._wizard_panel.show_error()
        return None

    def _run_wizard_eject(self) -> None:
        refreshed = self._refresh_device_before_eject_retry(self._wizard_target_device)
        if refreshed is None:
            return
        self._wizard_target_device = refreshed
        self._log_panel.append_log("Éjection de la carte…")
        self._start_eject(self._wizard_target_device, self._on_wizard_eject_finished)

    def _on_wizard_eject_finished(self, ok: bool, code: Optional[str], msg: Optional[str]) -> None:
        if not ok:
            self._last_error_code = code or "EJECT_FAILED"
            self._last_error_msg = msg or ""
            self._log_panel.finish_error(
                friendly_error_message(self._last_error_code),
                details=error_log_detail(self._last_error_code, self._last_error_msg),
            )
            self._wizard_panel.show_error()
            return
        self._log_panel.append_log(
            f"{self._wizard_target_device.display} peut maintenant être retirée en toute sécurité."
        )
        self._wizard_flow.mark_done(WizardJob.EJECT)
        self._enter_wizard_job(self._wizard_flow.current_job())
