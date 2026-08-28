"""Chaînes de l'interface, isolées ici dès le départ pour faciliter une
traduction future (§5 : « chaînes isolées dans un fichier de traduction »).

Vocabulaire : aucun terme technique ('périphérique bloc', '/dev/sdb',
'partition') ne doit apparaître ailleurs que dans le journal de bord
(le détail brut du backend y suit le message principal, en ligne
supplémentaire, §5 refonte navigation) — on dit "ta carte SD", pas "le
périphérique bloc"."""

from __future__ import annotations

STRINGS = {
    "app_title": "R36S Studio",
    # Accueil -- six étapes chronologiques fixes du workflow à deux cartes
    # (§4.5), toujours toutes visibles et cliquables, plus la sauvegarde
    # complète (opération de sécurité, en dehors des six étapes).
    "home_title": "Que veux-tu faire ?",
    "home_refresh": "Rafraîchir",
    # Symétrique de "assisted_expert_mode_button" -- bouton de retour au
    # mode assisté, en haut à droite de l'écran expert (§5 mode assisté).
    "home_assisted_mode_button": "Mode assisté",
    "home_step_a_title": "A. Copier le BOOT de la SD d'origine",
    "home_step_a_desc": "Enregistre l'écran et les réglages de ton ancienne carte sur ton ordinateur.",
    "home_step_b_title": "B. Copier l'EASYROMS de la SD d'origine",
    "home_step_b_desc": "Enregistre tes jeux et sauvegardes de l'ancienne carte sur ton ordinateur.",
    "home_step_c_title": "C. Flasher ArkOS sur la nouvelle SD",
    "home_step_c_desc": "Écrit le système sur ta carte neuve.",
    "home_step_d_title": "D. Copier le BOOT sur la nouvelle SD",
    "home_step_d_desc": "Remet l'écran et les réglages d'origine sur la carte neuve.",
    "home_step_e_title": "E. Copier l'EASYROMS sur la nouvelle SD",
    "home_step_e_desc": "Remet tes jeux et sauvegardes sur la carte neuve.",
    "home_step_f_title": "F. Éjecter la SD en toute sécurité",
    "home_step_f_desc": "Démonte la carte pour qu'elle puisse être retirée sans risque.",
    "home_backup_separator": "Par sécurité",
    "home_tile_backup": "Sauvegarder l'image complète de ma carte",
    "home_tile_backup_desc": "Enregistre le contenu actuel de ta carte SD dans un fichier, au cas où.",
    # Aide macOS uniquement (§3/§5 -- HomeScreen n'ajoute ce bouton que sur
    # macOS, seul OS concerné par cette autorisation).
    "home_help": "Aide : autoriser l'accès à la carte (Mac)",
    "status_available": "Faisable",
    "status_done": "Déjà faite",
    "status_not_relevant": "Non pertinente pour cette carte",
    "status_platform_limited": "PC ou Linux",
    # Bandeau carte détectée, en haut de l'accueil.
    "home_banner_line_device": "{display} — {size_go:.1f} Go",
    "home_banner_state_arkos": "Carte ArkOS reconnue",
    "home_banner_state_unprepared": "Carte non préparée",
    "home_banner_state_none": "Aucune carte détectée pour l'instant",
    "console_animation_toggle": "Animations de la console",
    # Accueil du mode assisté (§5 mode assisté) -- écran par défaut au
    # lancement, remplacé par le mode expert (six étapes) sur demande.
    "assisted_prepare_button": "Préparer ma carte automatiquement",
    "assisted_expert_mode_button": "Mode expert",
    # Panneau d'étape du mode assisté (WizardStepPanel) -- une étape à la
    # fois, consigne claire + bouton pour continuer (§5 mode assisté).
    "wizard_continue": "Continuer",
    "wizard_resume": "Reprendre",
    "wizard_cancel": "Annuler",
    "wizard_status_waiting": "En attente de ta carte…",
    "wizard_status_device_found": "Carte reconnue : {display}",
    "wizard_status_same_card": "C'est la même carte — insère la carte neuve, pas l'ancienne.",
    "wizard_status_multiple_candidates": "Plusieurs cartes détectées — choisis la bonne.",
    # Journal de bord (§5 vocabulaire : le détail technique n'apparaît
    # que là) -- combien de périphériques retenus/écartés à un sondage du
    # mode assisté, avec la raison de chaque exclusion.
    "wizard_diagnostic_summary": "Détection : {accepted} carte(s) retenue(s), {rejected} écartée(s)",
    "wizard_identify_result": "Console identifiée : {board} (écran {panel}).",
    "wizard_identify_failed": "Impossible d'identifier ta console — la version MultiPanel sera proposée par défaut.",
    "wizard_step1_title": "1. Insère ta carte SD d'origine",
    "wizard_step1_instruction": "Branche l'ancienne carte SD de ta console sur ton ordinateur.",
    "wizard_step2_title": "2. Identification de ta console",
    "wizard_step2_instruction": "On regarde les réglages de ta carte pour reconnaître ton modèle de console.",
    "wizard_step3_title": "3. Copie de l'écran et des jeux",
    "wizard_step3_instruction": "On enregistre l'écran, les réglages et les jeux de ta carte d'origine sur ton ordinateur.",
    "wizard_step4_title": "4. Insère ta carte neuve",
    "wizard_step4_instruction": "Retire la carte d'origine et branche la carte neuve à préparer.",
    "wizard_step5_title": "5. Installation d'ArkOS",
    "wizard_step5_instruction": "On installe le système sur ta carte neuve.",
    "wizard_step6_title": "6. Remise en place de ton écran",
    "wizard_step6_instruction": "On remet l'écran et les réglages d'origine sur la carte neuve.",
    "wizard_step7_title": "7. Éjection",
    "wizard_step7_instruction": "On retire ta carte neuve en toute sécurité — elle est prête.",
    "wizard_finished": "Ta carte est prête ! Tu peux la retirer et la mettre dans ta console.",
    # Fenêtre Choix du fichier, flash uniquement (§5 mode assisté, étape 5)
    # -- l'image n'est pas hébergée sur GitHub (Mega, Google Drive,
    # OneDrive, torrent), seul le lien vers la page des releases est ouvert.
    "file_releases_button": "Voir les versions disponibles en ligne",
    # Choix du périphérique
    "device_title": "Choisis ta carte SD",
    "device_refresh": "Rafraîchir",
    "device_empty": "Aucune carte SD détectée. Branche-la puis clique sur Rafraîchir.",
    "device_next": "Suivant",
    "device_back": "Retour",
    # Choix du fichier
    "file_title_backup": "Où enregistrer la sauvegarde ?",
    "file_title_flash": "Choisis le fichier image",
    "file_title_extract_boot": "Où enregistrer la sauvegarde de l'écran d'origine ?",
    "file_title_extract_easyroms": "Où enregistrer la sauvegarde des jeux ?",
    "file_title_inject_boot": "Choisis la sauvegarde de l'écran d'origine à réinjecter",
    "file_title_copy_games": "Choisis la sauvegarde de jeux à réinjecter",
    "file_archive_empty": "Aucune sauvegarde trouvée sur cet ordinateur. Utilise « Parcourir… » pour en choisir une.",
    "file_destination_hint": "Un dossier daté sera créé automatiquement à l'intérieur de cet emplacement.",
    "file_browse": "Parcourir…",
    "file_next": "Suivant",
    "file_back": "Retour",
    # Confirmation
    "confirm_title": "Attention",
    "confirm_checkbox": "Je comprends que toutes les données de cette carte seront effacées",
    "confirm_erase": "Toutes les données de « {display} » ({size_go:.1f} Go) seront définitivement effacées.",
    "confirm_go": "Effacer et écrire",
    "confirm_cancel": "Annuler",
    # Journal de bord (colonne droite, §5 -- remplace les anciens écrans
    # Exécution et Résultat) : en-tête au repos ou pendant une opération.
    "log_header_idle": "En attente",
    "log_header_active": "OPÉRATION ACTIVE — {title}",
    "execute_title_backup": "Sauvegarde en cours…",
    "execute_title_flash": "Écriture en cours…",
    "execute_title_extract_boot": "Copie de l'écran d'origine en cours…",
    "execute_title_extract_easyroms": "Copie des jeux en cours…",
    "execute_title_inject_boot": "Remise en place de l'écran d'origine…",
    "execute_title_copy_games": "Copie des jeux en cours…",
    "execute_cancel": "Annuler",
    "execute_speed": "{speed:.1f} Mo/s",
    "execute_eta": "Temps restant estimé : {eta}",
    "execute_eta_unknown": "Temps restant estimé : —",
    # Résultats de fin d'opération -- affichés comme lignes du journal de
    # bord, plus un écran séparé (§5, refonte navigation).
    "result_eject": "Éjecter la carte",
    "result_archive_created": "Enregistrée dans : {path} — Taille : {size}",
    "result_archive_source": "À partir de : {path}",
    # Aide (macOS uniquement -- autorisation Accès complet au disque, §3)
    "help_title": "Autoriser l'accès à ta carte SD",
    "help_body": (
        "Sur Mac, R36S Studio a besoin d'une autorisation spéciale pour accéder "
        "directement à ta carte SD, même après avoir entré ton mot de passe "
        "administrateur : l'Accès complet au disque.\n\n"
        "1. Ouvre Réglages Système → Confidentialité et sécurité.\n"
        "2. Descends jusqu'à « Accès complet au disque ».\n"
        "3. Utilise le bouton ci-dessous pour y aller directement, ou vas-y "
        "toi-même.\n"
        "4. Clique sur « + », choisis R36S Studio dans la liste, puis active "
        "le bouton à côté de son nom.\n"
        "5. Reviens dans R36S Studio et relance l'opération.\n\n"
        "Cette autorisation ne se fait qu'une fois par version de "
        "l'application. Si l'accès est de nouveau bloqué après une mise à "
        "jour, reviens simplement sur cet écran et recommence : reconstruire "
        "l'application change sa signature, ce qui invalide l'autorisation "
        "précédente."
    ),
    "help_back": "Retour",
    "help_open_settings": "Ouvrir les réglages",
    # Version + horodatage de construction (footer de l'accueil) -- sans ça,
    # impossible de savoir si l'app testée contient les derniers correctifs.
    "about_version": "R36S Studio v{version} ({suffix})",
    "about_build": "build du {timestamp}",
    "about_dev": "version de développement",
    # Messages d'erreur (vocabulaire §5 : jamais de jargon technique dans le
    # message principal -- le détail brut du backend suit, en ligne
    # supplémentaire, directement dans le journal de bord (§5, refonte
    # navigation -- plus de panneau "Détails" séparé à déplier).
    "error_partition_not_found": (
        "Impossible de trouver les fichiers de la console sur cette carte. "
        "As-tu bien préparé cette carte avec R36S Studio ?"
    ),
    "error_partition_not_mounted": (
        "La carte n'a pas pu s'ouvrir correctement. Débranche-la, rebranche-la, puis réessaie."
    ),
    "error_easyroms_ntfs_macos": (
        "Ton Mac ne peut pas copier des jeux sur cette carte à cause d'une limitation du "
        "système. Utilise un PC Windows ou Linux pour cette étape."
    ),
    "error_mountpoint_not_writable": (
        "Impossible d'écrire sur ta carte. Vérifie qu'elle n'est pas protégée en écriture, "
        "puis réessaie."
    ),
    "error_device_not_allowed": "Cette carte n'est plus accessible. Débranche-la puis rebranche-la.",
    "error_source_not_found": "Le dossier choisi est introuvable.",
    "error_verify_failed": "La vérification après écriture a échoué. Réessaie avec une carte neuve.",
    "error_cancelled": "L'opération a été annulée avant la fin.",
    "error_eject_failed": (
        "Impossible d'éjecter la carte. Ferme les fichiers ouverts dessus, puis réessaie, "
        "ou retire-la manuellement."
    ),
    "error_macos_tcc_blocked": (
        "Ton Mac empêche l'accès à la carte SD tant que R36S Studio n'a pas la permission "
        "Accès complet au disque. Ouvre l'Aide pour l'activer."
    ),
    "error_macos_tcc_protected_folder": (
        "Ton Mac bloque l'accès à ce fichier car il se trouve dans un dossier protégé "
        "(Téléchargements, Bureau ou Documents). Déplace-le ailleurs, puis réessaie."
    ),
    "error_generic": "Une erreur est survenue.",
}


def tr(key: str, **kwargs) -> str:
    """Traduit `key` et l'interpole avec `kwargs` — point d'entrée unique
    vers `STRINGS`, pour qu'un futur fichier par langue n'ait qu'un seul
    endroit à brancher."""
    template = STRINGS[key]
    return template.format(**kwargs) if kwargs else template


# code du protocole (§3, r36s_studio.protocol) -> clé de message convivial
_ERROR_MESSAGE_KEYS = {
    "CANCELLED": "error_cancelled",
    "PARTITION_NOT_FOUND": "error_partition_not_found",
    "PARTITION_NOT_MOUNTED": "error_partition_not_mounted",
    "EASYROMS_NTFS_MACOS": "error_easyroms_ntfs_macos",
    "MOUNTPOINT_NOT_WRITABLE": "error_mountpoint_not_writable",
    "DEVICE_NOT_ALLOWED": "error_device_not_allowed",
    "SOURCE_NOT_FOUND": "error_source_not_found",
    "VERIFY_FAILED": "error_verify_failed",
    "EJECT_FAILED": "error_eject_failed",
    "MACOS_TCC_BLOCKED": "error_macos_tcc_blocked",
    "MACOS_TCC_PROTECTED_FOLDER": "error_macos_tcc_protected_folder",
}


def friendly_error_message(code: str) -> str:
    """Message principal, sans jargon (§5), pour un code d'erreur du
    protocole. Le message brut du backend (qui peut contenir un chemin
    technique, un nom de système de fichiers...) n'est jamais affiché ici —
    il suit comme ligne supplémentaire dans le journal de bord
    (`LogPanel.finish_error`, §5 refonte navigation)."""
    return tr(_ERROR_MESSAGE_KEYS.get(code, "error_generic"))
