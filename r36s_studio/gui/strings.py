# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

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
    # Section « Consoles diverses » (consoles_diverses/, étape 1) -- bouton
    # discret vers un écran indépendant, isolé dans son propre package
    # (règle d'isolation, consoles_diverses/CLAUDE.md). Symétrique sur les
    # deux accueils (expert et assisté).
    "home_consoles_diverses_button": "Consoles diverses",
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
    # Remise à zéro (§4.3 bis) : pour une carte laissée en plusieurs
    # partitions illisibles après des essais de firmware -- efface tout et
    # recrée un seul espace de stockage normal, comme une carte SD neuve.
    "home_tile_reset_card": "Remettre la carte à zéro",
    "home_tile_reset_card_desc": (
        "Efface tout sur cette carte et la remet en un seul espace de stockage normal — "
        "utile après avoir essayé plusieurs firmwares."
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
    # Accueil du mode assisté (§5 mode assisté) -- écran par défaut au
    # lancement, remplacé par le mode expert (six étapes) sur demande.
    "assisted_prepare_button": "Préparer ma carte automatiquement",
    "assisted_expert_mode_button": "Mode expert",
    # Sauvegarde système sans les jeux (§4.3), aussi proposée comme option
    # du mode assisté -- discrète, sous le bouton principal.
    "assisted_backup_system_button": "Sauvegarder mon système sans les jeux",
    # Libellés courts des 10 tuiles de l'accueil assisté (refonte menu de
    # tuiles, §5) -- un seul libellé par tuile, bas-gauche, pas de
    # description séparée contrairement aux lignes de HomeScreen (préfixe
    # distinct de "home_tile_*", qui reste celui des lignes du mode
    # expert -- même concept, texte plus court pour tenir dans une tuile).
    # Tuile 1 seule à porter aussi une description (correctif visuel,
    # icône/libellé agrandis) ; "Rechercher ma console"/"Consoles
    # diverses" fusionnées en une seule tuile « Identifier ma console »
    # (correctif visuel) -- l'accès au catalogue se fait désormais depuis
    # l'écran de résultat de l'identification (`IdentifyResultDialog`).
    "assisted_tile_prepare": "Préparer ma carte",
    "assisted_tile_prepare_desc": "Copie complète de l'ancienne carte vers la neuve, étape par étape.",
    "assisted_tile_identify": "Identifier ma console",
    "assisted_tile_backup": "Sauvegarder ma carte",
    "assisted_tile_flash": "Installer un système",
    "assisted_tile_copy_games": "Copier mes jeux",
    "assisted_tile_find_duplicates": "Chercher les doublons",
    "assisted_tile_eject": "Éjecter la carte",
    "assisted_tile_reset_card": "Remettre la carte à zéro",
    "assisted_tile_help": "Aide",
    # En-tête de l'accueil assisté (§5, correctif visuel -- manquait
    # entièrement). Le nom de l'app lui-même réutilise "app_title", jamais
    # dupliqué ici.
    "assisted_brand_subtitle": "Choisis ce que tu veux faire avec ta carte SD.",
    # Étiquette de section au-dessus de la grille (maquette de référence,
    # docs/screenshots/maquette-accueil.png) -- manquait entièrement.
    "assisted_section_label": "Pour commencer",
    # Titre/message du nouveau dialogue "À propos" (Windows/Linux, tuile
    # Aide) -- macOS ouvre HelpDialog (Accès complet au disque) à la
    # place, sans rapport avec ces deux OS.
    "about_title": "À propos de R36S Studio",
    "about_orientation": (
        "Chaque tuile de l'accueil correspond à une action sur ta carte SD. "
        "Branche ta carte, l'appli détecte ce qu'il y a dessus et propose "
        "l'action pertinente avec un badge (faisable, déjà faite, non "
        "pertinente pour cette carte). Rien n'est jamais fait sans que tu "
        "cliques dessus, et toute action qui efface quelque chose te le "
        "demande explicitement avant de commencer."
    ),
    "about_close": "Fermer",
    # Résultat de la tuile « Rechercher ma console » (§5, refonte menu de
    # tuiles) -- `identify/__init__.py::identify_from_boot_directory`,
    # jamais un nom convivial inventé pour l'identifiant du .dtb (convention
    # déjà suivie ailleurs dans ce projet, §4.6).
    "identify_result_title": "Ta console",
    "identify_result_board": "Identifiant détecté : {board}",
    # Accès au catalogue (consoles_diverses/, ex-tuile « Consoles diverses »
    # fusionnée ici, §5 correctif visuel) -- toujours affiché, succès ou
    # échec de l'identification.
    "identify_result_catalog_button": "Voir le catalogue des consoles",
    "identify_result_clone_warning": (
        "Cette carte semble être une console clone (matériel différent d'une R36S/R35S standard). "
        "ArkOS et ROCKNIX ne démarrent généralement pas dessus -- EmuELEC, lui, fonctionne."
    ),
    "identify_failed_mount_failed": (
        "Impossible de lire le système de la carte. Débranche-la et rebranche-la, puis réessaie."
    ),
    "identify_failed_no_dtb_found": (
        "Aucune information de modèle trouvée sur cette carte -- c'est normal pour une carte tout juste flashée."
    ),
    "identify_failed_all_dtb_invalid": (
        "Les informations de modèle présentes sur cette carte sont illisibles ou corrompues."
    ),
    # Outil « Doublons de jeux » (docs/doublons.md, remplace l'ancien flux
    # carte-SD-uniquement) -- déplacement vers un dossier _doublons/,
    # jamais une suppression : le vocabulaire choisi ("écarter") reflète
    # ça, jamais "supprimer".
    "doublons_back_button": "Retour",
    "doublons_folder_title": "Choisir un dossier",
    "doublons_folder_hint": (
        "Choisis le dossier à analyser -- sur ton ordinateur, une carte SD ou un disque externe."
    ),
    "doublons_folder_no_shortcuts": "Aucune carte ni disque amovible détecté pour l'instant.",
    "doublons_browse_button": "Parcourir…",
    "doublons_options_title": "OPTIONS",
    "doublons_simulation_checkbox": "Simuler sans rien déplacer",
    "doublons_ignored_folders_title": "Dossiers ignorés :",
    "doublons_scan_progress_title": "Analyse en cours",
    "doublons_scan_progress_count": "{count} fichier(s) analysé(s)",
    "doublons_scan_cancel_button": "Annuler",
    "doublons_risk_title": "Ce dossier peut prendre du temps à analyser",
    "doublons_risk_cancel": "Annuler",
    "doublons_risk_continue": "Continuer",
    "doublons_risk_filesystem_root": (
        "Tu as choisi la racine entière d'un disque -- l'analyse peut prendre très "
        "longtemps et parcourir des dossiers sans rapport avec tes jeux. Continuer quand même ?"
    ),
    "doublons_risk_whole_user_folder": (
        "Tu as choisi un dossier personnel entier plutôt qu'un dossier de jeux précis -- "
        "l'analyse peut prendre très longtemps. Continuer quand même ?"
    ),
    "doublons_risk_large_folder": (
        "Ce dossier contient déjà plus de 200 000 fichiers et l'analyse continue -- "
        "ça peut prendre du temps. Continuer ?"
    ),
    "doublons_results_title": "Doublons trouvés",
    "doublons_undo_button": "Tout annuler",
    "doublons_undo_conflicts_warning": (
        "{count} fichier(s) n'ont pas pu être restauré(s) automatiquement -- "
        "vérifie le contenu du dossier _doublons/."
    ),
    "doublons_export_button": "Exporter le rapport",
    "doublons_simulation_banner": "Mode simulation actif -- rien ne sera déplacé.",
    "doublons_summary": (
        "{files} fichier(s) analysé(s) -- {exact} groupe(s) de copies identiques, "
        "{versions} groupe(s) de versions différentes."
    ),
    "doublons_empty": "Aucun doublon trouvé.",
    "doublons_selection_summary": "{count} fichier(s) sélectionné(s) -- {size} récupérables",
    "doublons_group_exact_title": "Copies identiques",
    "doublons_exact_group_hash_label": "SHA-256 : {hash}",
    "doublons_exact_group_identical_notice": (
        "Contenu strictement identique (même empreinte SHA-256), malgré des noms différents."
    ),
    "doublons_move_this_one": "Écarter celui-ci",
    "doublons_move_selected_button": "Écarter la sélection",
    "doublons_excluded_title": "Groupes exclus -- fichier lié introuvable",
    "doublons_excluded_entry": "{manifest} : {missing} introuvable(s)",
    "doublons_confirm_title": "Écarter ces doublons ?",
    "doublons_confirm_message": (
        "{count} fichier(s) ({size}) seront déplacés dans un dossier _doublons/ -- "
        "pas supprimés, tu peux les remettre à leur place plus tard si besoin."
    ),
    "doublons_confirm_message_simulation": (
        "Simulation : {count} fichier(s) ({size}) seraient déplacés dans un dossier "
        "_doublons/ -- rien ne sera réellement touché."
    ),
    "doublons_confirm_button": "Écarter",
    "doublons_confirm_button_simulation": "Simuler",
    "doublons_confirm_cancel": "Annuler",
    "doublons_undo_confirm_title": "Tout annuler ?",
    "doublons_undo_confirm_message": (
        "Tous les fichiers déplacés dans _doublons/ seront remis à leur emplacement d'origine."
    ),
    "doublons_undo_confirm_button": "Tout annuler",
    # Sauvegarde système lancée depuis l'accueil assisté (§4.3) : reste
    # entièrement dans l'habillage assisté (WizardStepPanel), jamais
    # l'écran expert -- correctif d'un défaut de parcours signalé (bascule
    # vers le mode expert pendant l'opération, sans proposition de suite
    # une fois terminée).
    "assisted_backup_system_running_title": "Sauvegarde du système en cours",
    "assisted_backup_system_running_instruction": "Ne débranche pas ta carte pendant la sauvegarde.",
    "assisted_backup_system_done_title": "Sauvegarde terminée",
    "assisted_backup_system_done_instruction": "Que veux-tu faire maintenant ?",
    # Mécanisme ad-hoc généralisé (§5, refonte menu de tuiles) -- même
    # principe que les paires backup_system ci-dessus, pour chacun des
    # autres job_keys déclenchables depuis une tuile de l'accueil assisté.
    # "flash" réutilise volontairement les paires "assisted_prepare_card_
    # done_*" existantes (ci-dessous) : même situation finale ("carte
    # préparée"), qu'on y soit arrivé via cette tuile ou via « Préparer une
    # carte avec cette sauvegarde ».
    "assisted_backup_running_title": "Sauvegarde de la carte en cours",
    "assisted_backup_running_instruction": "Ne débranche pas ta carte pendant la sauvegarde.",
    "assisted_backup_done_title": "Sauvegarde terminée",
    "assisted_backup_done_instruction": "Que veux-tu faire maintenant ?",
    "assisted_flash_running_title": "Installation du système en cours",
    "assisted_flash_running_instruction": "Ne débranche pas ta carte pendant l'installation.",
    "assisted_copy_games_running_title": "Copie des jeux en cours",
    "assisted_copy_games_running_instruction": "Ne débranche pas ta carte pendant la copie.",
    "assisted_copy_games_done_title": "Jeux copiés",
    "assisted_copy_games_done_instruction": "Que veux-tu faire maintenant ?",
    "assisted_reset_card_running_title": "Remise à zéro de la carte en cours",
    "assisted_reset_card_running_instruction": "Ne débranche pas ta carte pendant l'opération.",
    "assisted_reset_card_done_title": "Carte remise à zéro",
    "assisted_reset_card_done_instruction": "Que veux-tu faire maintenant ?",
    "assisted_eject_running_title": "Éjection de la carte en cours",
    "assisted_eject_running_instruction": "Ne débranche pas ta carte.",
    "assisted_eject_done_title": "Carte éjectée",
    "assisted_eject_done_instruction": "Tu peux retirer ta carte en toute sécurité.",
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
    # Bug corrigé, confirmé sur du vrai matériel : ni le contenu (empreinte
    # de BOOT indisponible) ni la taille ne peuvent alors prouver qu'il
    # s'agit d'une carte différente -- et le chemin de périphérique ne peut
    # pas servir de repli non plus sur Windows (certains lecteurs gardent
    # le même chemin quelle que soit la carte insérée, §4.4). Plutôt qu'un
    # blocage silencieux et définitif (l'approche précédente, qui bloquait
    # indéfiniment sur ce type de lecteur, sans issue), `SameCardUnverified
    # Dialog` (screens.py) exige une confirmation explicite -- ce statut
    # s'affiche pendant qu'elle est ouverte.
    "wizard_status_confirmation_needed": "Confirmation nécessaire — vérifie la fenêtre affichée.",
    "wizard_status_multiple_candidates": "Plusieurs cartes détectées — choisis la bonne.",
    # Journal de bord (§5 vocabulaire : le détail technique n'apparaît
    # que là) -- combien de périphériques retenus/écartés à un sondage du
    # mode assisté, avec la raison de chaque exclusion.
    "wizard_diagnostic_summary": "Détection : {accepted} carte(s) retenue(s), {rejected} écartée(s)",
    # Cycle de vie du minuteur de sondage automatique (`_start_wizard_poll_
    # timer`/`_stop_wizard_poll_timer`), journalisé une fois par transition
    # réelle (jamais à chaque relance interne pendant l'attente, §5 mode
    # assisté) -- rend visible si le sondage démarre bien et reste actif,
    # plutôt que de laisser deviner son état.
    "wizard_poll_started": "Sondage automatique de la carte démarré.",
    "wizard_poll_stopped": "Sondage automatique de la carte arrêté.",
    # Chien de garde (§5 mode assisté, `_check_wizard_poll_stall`) : signale
    # un sondage automatique resté silencieux anormalement longtemps et le
    # relance -- une seule ligne par épisode de ralentissement, jamais
    # répétée tant qu'il persiste (`_wizard_poll_stall_warned`).
    "wizard_poll_stall_detected": (
        "Le sondage automatique de la carte semblait interrompu depuis {seconds} s — relancé."
    ),
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
    # Remise à zéro (§4.3 bis, mode expert uniquement) -- choix de
    # l'étiquette du volume avant la fenêtre Confirmation, valeur par
    # défaut simple toujours remplaçable.
    "reset_card_label_title": "Nom de la carte",
    "reset_card_label_instruction": (
        "Choisis le nom qui s'affichera pour cette carte une fois vide — "
        "tu peux garder celui-ci."
    ),
    "reset_card_label_continue": "Continuer",
    # Choix du système de fichiers (§4.3 bis) -- ajouté suite à un
    # signalement : une console (SF3000HD) ne lit que le FAT32, rendue
    # inutilisable par le formatage exFAT jusque-là systématique. exFAT
    # reste le choix par défaut (le plus courant).
    "reset_card_filesystem_title": "Comment formater la carte ?",
    "reset_card_filesystem_exfat": "exFAT — recommandé",
    "reset_card_filesystem_exfat_desc": "Accepte les gros fichiers. Fonctionne avec la plupart des consoles récentes.",
    "reset_card_filesystem_fat32": "FAT32",
    "reset_card_filesystem_fat32_desc": "Pour les consoles anciennes qui ne lisent pas l'exFAT.",
    "reset_card_filesystem_fat32_note": "En FAT32, un seul fichier ne peut pas dépasser 4 Go.",
    # Vérification préalable, jamais après coup (§4.3 bis) -- en pratique
    # ne se déclenche jamais sur une vraie carte SD (le seuil se situe
    # autour de quelques dizaines de Mio), garde-fou par principe.
    "reset_card_fat32_impossible_warning": (
        "Le FAT32 n'est pas possible sur une carte aussi petite. Choisis exFAT à la place."
    ),
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
    # Avertissement après un flash Android (§4.6) : contrairement au reste
    # de l'interface (§5, jamais de jargon), ce message nomme volontairement
    # le vrai texte de la fenêtre Windows -- c'est une vraie fenêtre système
    # à laquelle réagir correctement, pas la description d'une action de
    # l'app (même principe que `HelpDialog`, §3).
    "flash_android_format_prompt_warning": (
        "Windows va sans doute proposer de formater ta carte (« Vous devez formater le "
        "disque… »), parfois plusieurs fois de suite — refuse à chaque fois, c'est normal : "
        "Windows ne sait simplement pas lire le système Android que tu viens d'installer, "
        "ce n'est pas un problème avec ta carte."
    ),
    # Constaté en usage réel : le même genre de boîte apparaît aussi après
    # un flash non-Android (ArkOS/ROCKNIX/EmuELEC/AmberELEC/MinUI, une
    # seule partition ext4 illisible plutôt que plusieurs) -- message
    # générique, sans détailler un mécanisme (écrans de rechange...) propre
    # à Android uniquement.
    "flash_format_prompt_warning_generic": (
        "Windows va peut-être proposer de formater la carte — refuse, c'est normal."
    ),
    # Constaté en usage réel : une image Android démarre parfois sur un
    # écran figé si l'écran choisi ne correspond pas à celui de la console
    # -- le mécanisme de rechange existe déjà sur le BOOT (dossier "Panels"),
    # mais rien ne l'indiquait dans l'app avant ce message (un débutant en
    # aurait conclu que le logiciel ne marche pas).
    "flash_android_panel_mismatch_warning": (
        "Si l'écran reste noir ou figé au démarrage, regarde sur le BOOT de la carte : "
        "un dossier « Panels » contient un sous-dossier par type d'écran, chacun avec des "
        "fichiers .dtb à copier à la racine du BOOT pour changer d'écran. Plusieurs essais "
        "sont parfois nécessaires — et rien ne garantit qu'un de ces écrans corresponde à "
        "ta console."
    ),
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
    # SameCardUnverifiedDialog (§5 mode assisté, étape 3) : ni le contenu ni
    # la taille de la carte détectée ne prouvent qu'il s'agit d'une carte
    # différente de la carte d'origine -- garde-fou le plus critique du
    # parcours (écrire par erreur sur la carte source détruirait la seule
    # copie fonctionnelle de la console), donc une confirmation explicite
    # plutôt qu'un passage silencieux. Bug corrigé, confirmé sur du vrai
    # matériel : remplace un repli sur le chemin de périphérique qui ne
    # fonctionnait pas sur certains lecteurs Windows (chemin identique quelle
    # que soit la carte insérée).
    "same_card_unverified_title": "Confirme qu'il s'agit d'une carte différente",
    "same_card_unverified_message": (
        "Impossible de vérifier automatiquement que « {display} » ({size_go:.1f} Go) "
        "est bien une carte différente de la carte d'origine — elle n'a pas de "
        "système lisible pour comparer son contenu, et la taille seule ne suffit "
        "pas à le prouver. Si c'est une carte neuve ou vierge, c'est normal. "
        "Assure-toi d'avoir bien retiré la carte d'origine : y écrire par erreur "
        "détruirait la seule copie fonctionnelle de ta console."
    ),
    "same_card_unverified_checkbox": "Je confirme qu'il s'agit bien d'une carte différente de la carte d'origine.",
    "same_card_unverified_confirm": "Continuer",
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
    "execute_title_reset_card": "Remise à zéro de la carte en cours…",
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
    # Bug corrigé (§4.4/§5) : distinct d'`error_eject_failed` -- une invite
    # UAC refusée ou fermée n'a rien à voir avec des fichiers ouverts sur
    # la carte, message dédié plutôt que le générique ci-dessus.
    "error_elevation_refused": "L'autorisation Windows a été refusée. Réessaie et accepte l'invite.",
    "error_reset_card_failed": (
        "Impossible de remettre cette carte à zéro. Débranche-la puis rebranche-la, "
        "ferme les fenêtres qui l'affichent, puis réessaie."
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
    # Outil « Doublons de jeux » (docs/doublons.md, § garde-fous ajoutés
    # après validation du plan) -- codes propres à `gui/doublons_runner.py`,
    # jamais réutilisés depuis les messages carte-SD ci-dessus/dessous
    # (`error_io_error` mentionne explicitement "la carte", trompeur pour
    # un dossier quelconque du PC).
    "error_doublons_io_error": (
        "Une erreur de lecture ou d'écriture est survenue. Vérifie que le dossier est toujours accessible."
    ),
    "error_destination_not_writable": (
        "Impossible d'écrire dans le dossier _doublons/ -- vérifie qu'il n'est pas en lecture seule."
    ),
    "error_volume_mismatch": (
        "Le dossier _doublons/ se trouve sur un disque différent de celui analysé -- opération annulée par prudence."
    ),
    "error_path_outside_root": "Un fichier à déplacer ne se trouve plus dans le dossier analysé.",
    "error_output_exists": "Un fichier du même nom existe déjà à cet emplacement. Choisis un autre nom ou un autre dossier.",
    "error_image_not_found": "Le fichier image choisi est introuvable. Il a peut-être été déplacé ou supprimé.",
    "error_io_error": "Une erreur de lecture ou d'écriture est survenue. Vérifie que la carte est toujours branchée.",
    # Bug corrigé, confirmé sur du vrai matériel : sans ce code dédié,
    # FSCTL_LOCK_VOLUME refusé par un autre programme (Explorateur,
    # indexeur, antivirus) retombait sur error_io_error ci-dessus -- « vérifie
    # que la carte est branchée » est faux dans ce cas précis (la carte est
    # bien branchée, le worker bien élevé) et n'aide pas à résoudre le
    # problème réel.
    "error_volume_in_use": (
        "La carte semble utilisée par un autre programme (l'Explorateur de "
        "fichiers, l'indexation de recherche, un antivirus…). Ferme les "
        "fenêtres qui l'affichent puis réessaie."
    ),
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
    "ELEVATION_REFUSED": "error_elevation_refused",
    "RESET_CARD_FAILED": "error_reset_card_failed",
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
    "VOLUME_IN_USE": "error_volume_in_use",
    "UNSUPPORTED_OS": "error_unsupported_os",
    "CONFIRMATION_REFUSED": "error_confirmation_refused",
    "INVALID_ARGS": "error_invalid_args",
    "DOUBLONS_IO_ERROR": "error_doublons_io_error",
    "DESTINATION_NOT_WRITABLE": "error_destination_not_writable",
    "VOLUME_MISMATCH": "error_volume_mismatch",
    "PATH_OUTSIDE_ROOT": "error_path_outside_root",
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
