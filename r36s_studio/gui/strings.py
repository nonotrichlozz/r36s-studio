"""Chaînes de l'interface, isolées ici dès le départ pour faciliter une
traduction future (§5 : « chaînes isolées dans un fichier de traduction »).

Vocabulaire : aucun terme technique ('périphérique bloc', '/dev/sdb',
'partition') ne doit apparaître ailleurs que dans le journal de bord
(le détail brut du backend y suit le message principal, en ligne
supplémentaire, §5 refonte navigation) — on dit "ta carte SD", pas "le
périphérique bloc"."""

from __future__ import annotations

from typing import Optional

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
    # Sauvegarde système sans les jeux (§4.3/§4.6) -- s'arrête juste avant
    # la partition de jeux (EASYROMS ou STORAGE), un fichier bien plus
    # petit qu'une image complète.
    "home_tile_backup_system": "Sauvegarder mon système sans les jeux",
    "home_tile_backup_system_desc": (
        "Enregistre l'écran et les réglages de ta carte, sans tes jeux — "
        "un fichier bien plus petit qu'une sauvegarde complète."
    ),
    # Aide macOS uniquement (§3/§5 -- HomeScreen n'ajoute ce bouton que sur
    # macOS, seul OS concerné par cette autorisation).
    "home_help": "Aide : autoriser l'accès à la carte (Mac)",
    "status_available": "Faisable",
    "status_done": "Déjà faite",
    "status_not_relevant": "Non pertinente pour cette carte",
    "status_platform_limited": "PC ou Linux",
    "status_system_incompatible": "Non applicable — carte ROCKNIX",
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
    # Sauvegarde système sans les jeux (§4.3), aussi proposée comme option
    # du mode assisté -- discrète, sous le bouton principal.
    "assisted_backup_system_button": "Sauvegarder mon système sans les jeux",
    # Sauvegarde système lancée depuis l'accueil assisté (§4.3) : reste
    # entièrement dans l'habillage assisté (WizardStepPanel), jamais
    # l'écran expert -- correctif d'un défaut de parcours signalé (bascule
    # vers le mode expert pendant l'opération, sans proposition de suite
    # une fois terminée).
    "assisted_backup_system_running_title": "Sauvegarde du système en cours",
    "assisted_backup_system_running_instruction": "Ne débranche pas ta carte pendant la sauvegarde.",
    "assisted_backup_system_done_title": "Sauvegarde terminée",
    "assisted_backup_system_done_instruction": "Que veux-tu faire maintenant ?",
    "assisted_prepare_card_button": "Préparer une carte avec cette sauvegarde",
    "assisted_return_home_button": "Revenir à l'accueil",
    "assisted_prepare_card_choose_device_title": "Choisis la carte à préparer",
    "assisted_prepare_card_choose_device_instruction": (
        "Branche la carte SD neuve que tu veux préparer avec cette sauvegarde."
    ),
    "assisted_prepare_card_done_title": "Carte préparée",
    "assisted_prepare_card_done_instruction": "Que veux-tu faire maintenant ?",
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
    "wizard_step1_title": "1. Insère ta carte SD d'origine",
    "wizard_step1_instruction": "Branche l'ancienne carte SD de ta console sur ton ordinateur.",
    "wizard_step2_title": "2. Copie de ta carte sur l'ordinateur",
    "wizard_step2_instruction": "Choisis ce que tu veux sauvegarder, puis on l'enregistre sur ton ordinateur.",
    # Étape 2 (§5 mode assisté, parcours de clonage) : choix entre copie
    # complète et système seul, avant même d'ouvrir la fenêtre Choix du
    # fichier -- image disque brute dans les deux cas, aucune opération au
    # niveau fichier, ce qui rend ce choix indépendant du firmware
    # installé sur la carte source.
    "wizard_backup_kind_title": "Que veux-tu sauvegarder ?",
    "wizard_backup_kind_full": "Copie complète",
    "wizard_backup_kind_full_desc": "L'écran, les réglages et tous tes jeux. Jusqu'à environ {size}.",
    "wizard_backup_kind_system": "Système seul, sans les jeux",
    "wizard_backup_kind_system_desc": "L'écran et les réglages seulement — un fichier bien plus petit.",
    "wizard_create_image_size_hint": "Taille maximale de la copie : environ {size}.",
    "wizard_image_created_log": "Image créée : {path}",
    "wizard_step3_title": "3. Insère ta carte neuve",
    "wizard_step3_instruction": "Branche maintenant la carte neuve à préparer.",
    # Éjection de la carte source, en tout début de l'étape 3 -- avant même
    # d'afficher la consigne d'insertion ci-dessus (§5 mode assisté,
    # correctif : retirer la carte pendant qu'elle est encore montée
    # risquait de corrompre des données).
    "wizard_ejecting_source": "Éjection de ta carte d'origine…",
    "wizard_source_ejected": "Tu peux maintenant retirer ta carte d'origine en toute sécurité.",
    "wizard_step4_title": "4. Installation sur ta carte neuve",
    "wizard_step4_instruction": "On installe ta sauvegarde sur ta carte neuve.",
    "wizard_step5_title": "5. Éjection",
    "wizard_step5_instruction": "On retire ta carte neuve en toute sécurité — elle est prête.",
    "wizard_finished": "Ta carte est prête ! Tu peux la retirer et la mettre dans ta console.",
    # Chemin de destination annoncé dès le début de la copie (étapes A/B du
    # mode expert, §5 mode assisté historiquement) -- pas seulement à la
    # fin, journal de bord uniquement (§5 vocabulaire).
    "wizard_archive_destination_log": "Destination : {path}",
    # Fenêtre Choix du fichier, flash uniquement (§5 mode assisté, étape 5)
    # -- l'image n'est pas hébergée sur GitHub (Mega, Google Drive,
    # OneDrive, torrent), seul le lien vers la page des releases est ouvert.
    "file_releases_button": "Voir les versions disponibles en ligne",
    # Catalogue de firmwares, flash uniquement (§4.6, mode expert --
    # identify/firmware_catalog.py). ROCKNIX est la seule entrée à
    # téléchargement automatique (images attachées directement aux
    # releases GitHub, file_rocknix_download_button, identify/rocknix.py)
    # ; toutes les autres ouvrent leur page de releases dans le
    # navigateur (file_releases_button) -- vérifié individuellement pour
    # chacune avant l'ajout du catalogue, aucune n'a d'assets exploitables
    # directement comme ROCKNIX.
    "firmware_status_maintained": "Maintenu",
    "firmware_status_archived": "Archivé",
    "firmware_status_experimental": "Expérimental",
    "file_firmware_arkos_title": "ArkOS / dArkOS",
    "file_firmware_arkos_desc": (
        "Figée depuis fin 2025 : aucune mise à jour officielle. La version "
        "communautaire pour R36S (dArkOS) reste installable."
    ),
    "file_firmware_rocknix_title": "ROCKNIX",
    "file_firmware_rocknix_desc": "Un système plus récent, avec le transfert de jeux par USB intégré.",
    # EmuELEC (§4.6) -- consoles clones uniquement : ArkOS et ROCKNIX
    # standard ne démarrent pas sur ce matériel (identify/__init__.py::
    # CLONE_DTB_FILENAMES). Pas de correspondance d'assets par SoC
    # vérifiée à ce jour pour la R36S/RK3326, contrairement à ROCKNIX.
    "file_firmware_emuelec_title": "EmuELEC",
    "file_firmware_emuelec_desc": "Pour les consoles clones : ArkOS et ROCKNIX n'y démarrent pas.",
    # AmberELEC/MinUI/R36Droid/andr36oid (§4.6) -- ajoutés au catalogue
    # sans compatibilité R36S officiellement confirmée par leur projet
    # (vérifié sur leurs pages de releases avant l'ajout) : descriptions
    # honnêtes sur cette incertitude plutôt qu'une promesse non vérifiée.
    "file_firmware_amberelec_title": "AmberELEC",
    "file_firmware_amberelec_desc": (
        "Conçu pour la même famille de puce (RK3326) que la R36S, "
        "compatibilité R36S non officiellement confirmée."
    ),
    "file_firmware_minui_title": "MinUI",
    "file_firmware_minui_desc": (
        "Interface minimaliste. Portage communautaire pour R36S, distinct du projet officiel."
    ),
    "file_firmware_r36droid_title": "R36Droid (Android)",
    "file_firmware_r36droid_desc": "Portage communautaire d'Android (LineageOS) pour R36S/RK3326.",
    "file_firmware_andr36oid_title": "andr36oid (Android)",
    "file_firmware_andr36oid_desc": "Autre portage communautaire d'Android (LineageOS) pour R36S/RK3326.",
    "file_manual_download_hint": (
        "Le fichier téléchargé peut être une archive (.7z, .zip…) : décompresse-la "
        "d'abord si besoin, puis choisis ici le fichier .img qu'elle contient."
    ),
    "file_rocknix_download_button": "Télécharger la dernière version",
    # Fenêtre de choix entre plusieurs variantes ROCKNIX (§5, étape de
    # flash) -- une vraie release peut en publier plusieurs (ex. -a/-b),
    # jamais de sélection automatique entre elles.
    "rocknix_variant_title": "Choisis une version de ROCKNIX",
    "rocknix_variant_hint": (
        "Plusieurs versions sont disponibles. Si tu ne sais pas laquelle choisir, "
        "prends la première de la liste."
    ),
    # Choix du périphérique
    "device_title": "Choisis ta carte SD",
    "device_refresh": "Rafraîchir",
    "device_empty": "Aucune carte SD détectée. Branche-la puis clique sur Rafraîchir.",
    "device_next": "Suivant",
    "device_back": "Retour",
    # Choix du fichier
    "file_title_backup": "Où enregistrer la sauvegarde ?",
    "file_title_backup_system": "Où enregistrer la sauvegarde du système ?",
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
    "execute_title_backup_system": "Sauvegarde du système en cours…",
    "execute_title_flash": "Écriture en cours…",
    "execute_title_extract_boot": "Copie de l'écran d'origine en cours…",
    "execute_title_extract_easyroms": "Copie des jeux en cours…",
    "execute_title_inject_boot": "Remise en place de l'écran d'origine…",
    "execute_title_copy_games": "Copie des jeux en cours…",
    "execute_title_list_rocknix": "Recherche des versions ROCKNIX en ligne…",
    "execute_title_download_rocknix": "Téléchargement de ROCKNIX en cours…",
    "rocknix_download_success": "La dernière version de ROCKNIX a été téléchargée : {path}",
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
    # Écran de bienvenue au premier lancement (macOS uniquement, §3) --
    # affiché tant que l'Accès complet au disque n'est pas détecté
    # (`elevate.has_full_disk_access`), à la place de l'accueil habituel.
    "fda_welcome_title": "Bienvenue dans R36S Studio",
    "fda_welcome_body": (
        "Avant de commencer, ton Mac bloque deux choses par défaut : "
        "ouvrir une application qui ne vient pas d'un développeur reconnu "
        "par Apple, et laisser cette application accéder directement à une "
        "carte SD.\n\n"
        "1. Si ce n'est pas déjà fait : ferme cette fenêtre, fais un clic "
        "droit sur R36S Studio dans le Finder, choisis « Ouvrir », puis "
        "confirme — une seule fois.\n"
        "2. Ouvre Réglages Système → Confidentialité et sécurité → Accès "
        "complet au disque (utilise le bouton ci-dessous pour y aller "
        "directement).\n"
        "3. Clique sur « + », choisis R36S Studio dans la liste, puis "
        "active le bouton à côté de son nom.\n"
        "4. Reviens ici et clique sur « J'ai terminé ».\n\n"
        "Cette autorisation ne se fait qu'une fois par version de "
        "l'application : si elle est de nouveau bloquée après une mise à "
        "jour, il faudra recommencer ces étapes."
    ),
    "fda_welcome_open_settings": "Ouvrir les réglages",
    "fda_welcome_done": "J'ai terminé",
    "fda_welcome_still_not_detected": (
        "Autorisation pas encore détectée. Vérifie que R36S Studio est bien "
        "coché dans la liste Accès complet au disque, puis réessaie."
    ),
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
    # Format de l'image choisie pour le flash (§4.3/§5) -- détecté par les
    # octets d'en-tête, pas seulement l'extension (imaging/image_source.py).
    "error_seven_zip_archive": (
        "Ce fichier est une archive 7-Zip. Décompresse-la d'abord — tu obtiendras "
        "un fichier .img que tu pourras flasher directement."
    ),
    "error_unsupported_image_format": (
        "Ce fichier n'est pas une image utilisable. Formats acceptés : .img, .img.gz, .img.xz."
    ),
    # Téléchargement automatique ROCKNIX (§5, étape de flash, identify/rocknix.py).
    "error_rocknix_asset_not_found": (
        "Impossible de trouver la version ROCKNIX pour ta console en ligne. "
        "Réessaie plus tard, ou choisis un fichier déjà téléchargé."
    ),
    "error_rocknix_checksum_mismatch": (
        "Le fichier téléchargé est corrompu ou incomplet. Réessaie."
    ),
    "error_rocknix_download_failed": (
        "Le téléchargement a échoué. Vérifie ta connexion internet, puis réessaie."
    ),
    "error_games_partition_not_found": (
        "Impossible de reconnaître l'emplacement des jeux (EASYROMS ou STORAGE) sur "
        "cette carte — la sauvegarde système sans les jeux ne sait pas où s'arrêter."
    ),
    # Pré-vol du parcours de clonage (§5 mode assisté) : jamais un échec
    # après une longue copie déjà lancée -- ces deux vérifications
    # s'exécutent avant d'écrire quoi que ce soit.
    "error_insufficient_disk_space": (
        "Ton ordinateur n'a pas assez de place libre pour créer cette sauvegarde. "
        "Libère de l'espace, ou choisis un autre disque, puis réessaie."
    ),
    "error_destination_too_small": (
        "Cette carte est trop petite pour la sauvegarde à installer. "
        "Utilise une carte neuve d'au moins la même taille."
    ),
    # Codes émis par le worker élevé (`__main__.py`) mais absents de
    # `_ERROR_MESSAGE_KEYS` jusqu'ici (bug corrigé) -- retombaient sur
    # `error_generic` malgré une cause précise et déjà connue. `IO_ERROR`
    # en particulier est le repli générique de la quasi-totalité des
    # commandes CLI pour une erreur disque/E-S imprévue (carte débranchée
    # en cours de copie, permission refusée...) : le plus susceptible
    # d'apparaître en usage réel de tous les codes qui manquaient.
    "error_output_exists": "Un fichier du même nom existe déjà à cet emplacement. Choisis un autre nom ou un autre dossier.",
    "error_image_not_found": "Le fichier image choisi est introuvable. Il a peut-être été déplacé ou supprimé.",
    "error_io_error": "Une erreur de lecture ou d'écriture est survenue. Vérifie que la carte est toujours branchée.",
    "error_unsupported_os": "Cette opération n'est pas prise en charge sur ce système.",
    "error_confirmation_refused": "Écriture annulée : la confirmation n'a pas été reçue.",
    # INVALID_ARGS : mauvaise combinaison d'options en ligne de commande
    # (CLI direct, §1) -- la GUI construit toujours des arguments valides,
    # ce code ne devrait donc jamais apparaître ici, mais mappé quand même
    # par principe (aucun code connu du protocole ne doit retomber sur le
    # message générique, ci-dessous).
    "error_invalid_args": "Commande invalide.",
    "error_generic": "Une erreur est survenue.",
    # Estimation avant de lancer la sauvegarde système sans les jeux (§4.3)
    # -- journal de bord, avant l'ouverture de la fenêtre Choix du fichier.
    "system_backup_estimating": "Calcul de la taille estimée…",
    "system_backup_estimate_result": "Taille estimée : environ {size} (sans les jeux).",
    # Même information, affichée directement sur la fenêtre Choix du
    # fichier plutôt que seulement dans le journal de bord (§4.3).
    "file_system_backup_size": "Taille estimée : environ {size} (sans les jeux).",
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
    "SEVEN_ZIP_ARCHIVE": "error_seven_zip_archive",
    "UNSUPPORTED_IMAGE_FORMAT": "error_unsupported_image_format",
    "ROCKNIX_ASSET_NOT_FOUND": "error_rocknix_asset_not_found",
    "ROCKNIX_CHECKSUM_MISMATCH": "error_rocknix_checksum_mismatch",
    "ROCKNIX_DOWNLOAD_FAILED": "error_rocknix_download_failed",
    "GAMES_PARTITION_NOT_FOUND": "error_games_partition_not_found",
    "INSUFFICIENT_DISK_SPACE": "error_insufficient_disk_space",
    "DESTINATION_TOO_SMALL": "error_destination_too_small",
    "OUTPUT_EXISTS": "error_output_exists",
    "IMAGE_NOT_FOUND": "error_image_not_found",
    "IO_ERROR": "error_io_error",
    "UNSUPPORTED_OS": "error_unsupported_os",
    "CONFIRMATION_REFUSED": "error_confirmation_refused",
    "INVALID_ARGS": "error_invalid_args",
}


def friendly_error_message(code: str) -> str:
    """Message principal, sans jargon (§5), pour un code d'erreur du
    protocole. Le message brut du backend (qui peut contenir un chemin
    technique, un nom de système de fichiers...) n'est jamais affiché ici —
    il suit comme ligne supplémentaire dans le journal de bord
    (`LogPanel.finish_error`, §5 refonte navigation)."""
    return tr(_ERROR_MESSAGE_KEYS.get(code, "error_generic"))


def error_log_detail(code: Optional[str], msg: Optional[str]) -> str:
    """Détail à journaliser à la suite du message convivial
    (`LogPanel.finish_error`/`LogPanel.append_log`, §5) -- bug corrigé,
    confirmé sur du vrai matériel : un code d'erreur sans traduction
    connue (`friendly_error_message` retombe alors sur `error_generic`,
    « Une erreur est survenue. ») ne laissait auparavant aucune trace du
    code réel, seulement le message brut de l'exception (`msg`, souvent
    peu parlant seul, ex. juste un chemin) -- rendant tout diagnostic après
    coup impossible sans reproduire le bug avec un débogueur. Le code brut
    du protocole (ex. `IO_ERROR`) précède désormais le message dans ce cas
    précis ; un code déjà traduit (§5 vocabulaire : le message principal
    reste sans jargon) n'a pas besoin de cette répétition, le message brut
    seul suffit comme avant."""
    code = code or ""
    msg = msg or ""
    if code and code not in _ERROR_MESSAGE_KEYS:
        return f"{code} : {msg}" if msg else code
    return msg
