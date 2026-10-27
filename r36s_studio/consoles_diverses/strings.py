# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Chaînes propres au package `consoles_diverses/`, isolées de
`gui/strings.py` (§CLAUDE.md du package, règle d'isolation demandée par la
spec) -- seule une clé de libellé de bouton d'entrée vit dans
`gui/strings.py`, puisque le bouton lui-même appartient à des écrans
existants (`HomeScreen`/`AssistedLandingScreen`). Même vocabulaire que le
reste de l'application (§5 de CLAUDE.md racine) : aucun terme technique,
jamais de jargon. Français = référence ; l'anglais vit dans
`strings_en.py`, langue choisie par `r36s_studio.i18n` (module neutre,
ni `gui/` ni PySide6)."""

from __future__ import annotations

from r36s_studio import i18n

from .strings_en import STRINGS_EN

STRINGS = {
    "screen_title": "Consoles diverses",
    "back_button": "← Retour à l'accueil",
    "reference_placeholder": "Référence de la console (ex. RG35XX, SF3000HD...)",
    "search_button": "Rechercher",
    "settings_button": "Réglages",
    "searching_status": "Recherche en cours…",
    "searching_status_lente": "La recherche prend plus de temps que prévu…",
    "badge_verified": "Vérifié",
    "badge_unverified": "Non vérifié",
    "unverified_note": "Trouvé automatiquement, non vérifié.",
    "restriction_commerciale_banner": "Licence non commerciale : usage commercial interdit.",
    "restriction_commerciale_chip": "Non commerciale",
    "licence_a_verifier_mention": "Licence à vérifier",
    "licence_non_detectee": "Licence non détectée",
    "info_title": "À savoir",
    "android_notice": (
        "Console Android : la préparation se fait par ADB, pas par la carte SD "
        "(bientôt dans R36S Studio)."
    ),
    "hardware_title": "Matériel",
    "hardware_label_soc": "SoC",
    "hardware_label_architecture": "Architecture",
    "hardware_label_os_type": "Système",
    "value_not_found": "Non trouvé",
    "category_frontend": "Front-end",
    "category_systeme_cfw": "Système / CFW",
    "category_firmware_origine": "Firmware d'origine",
    "category_mises_a_jour": "Mises à jour",
    "categories_without_options": "Rien trouvé pour : {liste}",
    "install_button": "⬇ Télécharger et installer",
    "no_options_at_all_message": "Peu d'informations trouvées pour cette console.",
    "incompatibles_title": "Ne pas installer : {liste}",
    "open_page_button": "Ouvrir la page",
    # Libellé plus parlant quand le lien pointe vers GitHub (§ retouche
    # visuelle des liens) -- même bouton, même règle de sécurité
    # (`_est_url_externe_sure`), seul le texte change.
    "open_github_button": "Ouvrir sur GitHub",
    "sources_title": "Sources ({total})",
    "no_info_title": "Aucune information trouvée",
    "no_info_message": "Le serveur n'a trouvé aucune information sur cette console.",
    "retry_button": "Réessayer",
    # Aucune clé saisie : l'écran l'explique d'emblée plutôt que de rester
    # vide sous le champ de recherche -- sans bloquer (le catalogue vérifié
    # se consulte sans clé).
    "no_licence_title": "Clé de licence",
    "no_licence_message": "Les consoles déjà au catalogue se consultent sans clé. Pour chercher une console qui n'y est pas encore, saisis la clé de licence reçue à l'achat.",
    "enter_licence_button": "Saisir ma clé",
    # Réglages
    "settings_title": "Réglages — Consoles diverses",
    "settings_licence_label": "Clé de licence",
    "settings_save_button": "Enregistrer",
    "settings_cancel_button": "Annuler",
    "settings_url_empty": "Indique une adresse de serveur.",
    "settings_url_invalid_scheme": "L'adresse doit commencer par http:// ou https://.",
    "settings_url_http_remote_refused": (
        "Une adresse http:// n'est acceptée que pour localhost ou 127.0.0.1 -- sinon ta "
        "clé de licence circulerait en clair sur le réseau. Utilise https:// pour un "
        "serveur distant."
    ),
    # Erreurs -- messages clairs pour un débutant, jamais de jargon (§5
    # vocabulaire de CLAUDE.md racine). Le message brut du serveur, quand il
    # existe, est interpolé en second plan plutôt qu'affiché seul.
    "error_reference_invalide": "Cette référence n'est pas valide (caractères non autorisés ou trop longue).",
    "error_licence_requise": "Une clé de licence est nécessaire pour chercher une console qui n'est pas encore au catalogue. Saisis la clé reçue à l'achat.",
    "error_licence_invalide": "Cette clé de licence n'est pas reconnue. Vérifie qu'elle a été copiée en entier (elle commence par « r36s- »), sans espace en trop.",
    "error_licence_expiree": "Ta clé de licence a expiré. Renouvelle-la pour continuer à chercher de nouvelles consoles ; les consoles déjà au catalogue restent consultables.",
    "error_licence_revoquee": "Cette clé de licence a été désactivée. Contacte le vendeur si tu penses que c'est une erreur.",
    "error_quota_licence_depasse": "Ta clé a atteint son nombre de recherches pour aujourd'hui. Réessaie demain ; les consoles déjà au catalogue restent consultables.",
    "error_trop_de_requetes": "Trop de recherches d'affilée. Attends une minute, puis réessaie.",
    "error_erreur_interne": "Le serveur a rencontré un problème. Réessaie dans quelques minutes.",
    "error_recherche_ia_indisponible": "La recherche automatique est momentanément indisponible.{message_serveur}",
    "error_configuration_manquante": "Le serveur n'est pas configuré correctement. Contacte l'administrateur du serveur.",
    "error_erreur_api_ia": "La recherche automatique a rencontré un problème. Réessaie plus tard.",
    "error_reponse_ia_non_json": "La recherche automatique a renvoyé une réponse invalide. Réessaie plus tard.",
    "error_serveur_injoignable": "Impossible de joindre le serveur. Vérifie ta connexion internet, puis réessaie.",
    "error_delai_depasse": "Le serveur met trop de temps à répondre (plus de 90 secondes). Réessaie.",
    "error_ia_surchargee": "Le service de recherche est surchargé pour le moment. Réessaie dans quelques minutes.",
    "error_reponse_invalide": "Le serveur a renvoyé une réponse inattendue.",
    "error_erreur_inattendue": "Une erreur inattendue est survenue.",
    "error_generique": "Une erreur est survenue.",
    # Installations guidées par USB (`procedure_screen.py`, champ
    # `procedures` de la fiche). Les consignes propres à la console (gestes,
    # premier démarrage, dépannage) viennent de la fiche elle-même.
    "procedures_title": "Installations guidées",
    "procedure_button": "Installer pas à pas",
    "procedure_experimental": "Expérimental : cette installation n'a pas encore été vérifiée sur la console.",
    "procedure_desactivee_mode": "Pas encore possible depuis R36S Studio : cette installation ne passe pas par le câble USB.",
    "procedure_desactivee_etape": "Pas encore possible depuis R36S Studio : une étape n'est pas encore prise en charge sans risque pour les données de la console.",
    "procedure_desactivee_systeme": "Non disponible sur ce système : cette installation demande un ordinateur {systemes}.",
    "procedure_desactivee_pac": "Pas encore possible : la fiche ne dit pas comment vérifier le fichier avant de l'écrire.",
    "proc_back": "← Retour à la fiche",
    "proc_help_button": "Dépannage",
    "proc_help_title": "Dépannage",
    "proc_help_empty": "Aucun conseil de dépannage pour cette console.",
    "proc_credit": "{firmware} est l'œuvre de {auteur}. R36S Studio télécharge ses fichiers depuis la page officielle, sans jamais les redistribuer.",
    "proc_credit_page": "Page officielle",
    "proc_variant_title": "Choisis la version",
    "proc_variant_recommended": "{nom} (recommandée)",
    "proc_erase_warning": "Tout le contenu de la console sera effacé.",
    "proc_erase_checkbox": "J'ai compris : tout le contenu de la console sera effacé.",
    "proc_continue": "Continuer",
    "proc_cancel": "Annuler",
    "proc_retry": "Réessayer",
    "proc_prereq_title": "Vérifications",
    "proc_prereq_os_ok": "Ordinateur Windows",
    "proc_prereq_space_ok": "Espace libre suffisant ({libre} disponibles)",
    "proc_prereq_space_ko": "Pas assez d'espace libre : il faut {requis}, il reste {libre}.",
    "proc_prereq_drivers_ok": "Pilotes USB de la console déjà installés",
    "proc_prereq_drivers_todo": "Pilotes USB de la console : ils seront installés (Windows demandera une autorisation)",
    "proc_prereq_tools": "7-Zip et outil d'installation : fournis avec les fichiers téléchargés, rien à installer",
    "proc_prereq_checking": "Vérification en cours…",
    "proc_download_title": "Téléchargement",
    "proc_download_status": "{nom} : {fait} sur {total}",
    "proc_download_status_unknown": "{nom} : {fait}",
    "proc_drivers_title": "Pilotes USB",
    "proc_drivers_status": "Installation des pilotes USB de la console… Windows va demander une autorisation.",
    "proc_drivers_reboot": "Pilotes installés. Windows conseille de redémarrer l'ordinateur ; tu peux d'abord essayer sans.",
    "proc_password_title": "Mot de passe de l'archive",
    "proc_password_help": "Le mot de passe n'est pas public. {source}",
    "proc_password_placeholder": "Mot de passe",
    "proc_password_show": "Afficher",
    "proc_password_never_saved": "Il n'est jamais enregistré : il sert seulement le temps d'ouvrir l'archive.",
    "proc_password_wrong": "Ce mot de passe ne convient pas. Vérifie-le (majuscules, espaces) et réessaie.",
    "proc_extract_title": "Ouverture de l'archive",
    "proc_extract_checking": "Vérification du mot de passe…",
    "proc_extract_status": "Extraction : {pourcent} %",
    "proc_pick_title": "Fichier du système",
    "proc_pick_message": "Ce fichier ne se télécharge pas automatiquement. Télécharge-le depuis la page ci-dessous, puis choisis-le : le fichier .pac, ou l'archive qui le contient.",
    "proc_pick_button": "Choisir le fichier…",
    "proc_pick_open_page": "Ouvrir la page de téléchargement",
    "proc_pac_ok": "Fichier vérifié : {nom}, version {version}.",
    "proc_pac_wrong": "Ce fichier n'est pas fait pour cette console ({nom}, version {version}). Rien n'a été écrit sur la console.",
    "proc_pac_unreadable": "Ce fichier n'est pas un fichier système lisible. Rien n'a été écrit sur la console.",
    "proc_instructions_title": "Avant de brancher la console",
    "proc_instructions_done": "C'est fait",
    "proc_delai_label": "Attendre la console au plus",
    "proc_flash_title": "Installation",
    "proc_flash_loading": "Préparation du fichier du système : {pourcent} %",
    "proc_flash_starting": "Lancement de l'outil d'installation…",
    "proc_flash_connect_title": "Branche la console en mode installation",
    "proc_flash_connect_countdown": "En attente de la console… ({secondes} s)",
    "proc_flash_android": "La console a démarré normalement. Débranche-la, éteins-la, et recommence en maintenant le bouton indiqué pendant que tu branches le câble.",
    "proc_flash_detected": "Console détectée. L'installation commence…",
    "proc_flash_running_title": "Ne débranche pas la console",
    "proc_flash_running": "Installation en cours : {pourcent} %",
    "proc_flash_cancel_refused": "L'installation a commencé : elle ne peut plus être arrêtée sans risque.",
    "proc_flash_bouton_retour": "La console a été vue mais n'a pas répondu : elle n'était pas en mode Download. Maintiens le bouton Retour, au centre de la manette, pendant que tu branches le câble, puis réessaie. Rien n'a été écrit.",
    "proc_flash_timeout": "La console n'a pas été détectée à temps. Rien n'a été écrit.",
    "proc_flash_failed": "L'installation n'a pas abouti. {message}",
    "proc_fallback_button": "Utiliser l'outil graphique",
    "proc_fallback_guide": "L'outil d'installation s'ouvre. Le chemin du fichier est copié : clique sur l'engrenage de gauche, colle le chemin ({chemin}), clique sur la flèche, puis branche la console comme avant.",
    "proc_done_title": "Installation terminée",
    "proc_done_android": "Installer des émulateurs (Console Android)",
    "proc_done_back": "Terminer",
    "proc_error_title": "Problème",
    "proc_error_reseau": "Le téléchargement s'est interrompu. Vérifie ta connexion puis clique sur Réessayer : il reprendra où il s'est arrêté.",
    "proc_error_empreinte": "Un fichier téléchargé ne correspond pas à l'original ({detail}). Il a été supprimé ; clique sur Réessayer.",
    "proc_error_outils": "Les outils d'installation sont introuvables dans le fichier téléchargé.",
    "proc_error_disque": "Impossible d'écrire sur le disque de l'ordinateur.",
    "proc_error_extraction": "L'archive n'a pas pu être ouverte.",
    "proc_error_pac_absent": "Le fichier du système est introuvable après l'ouverture de l'archive.",
    "proc_error_pilotes": "Les pilotes USB n'ont pas été installés : sans eux, l'ordinateur ne verra pas la console.",
    "proc_error_pilotes_refus": "L'autorisation de Windows a été refusée : les pilotes USB n'ont pas été installés.",
    "proc_error_url": "Adresse de téléchargement refusée.",
}


def tr(key: str, **kwargs) -> str:
    """Traduit `key` et l'interpole avec `kwargs` -- point d'entrée unique
    vers les chaînes (même contrat que `gui/strings.py::tr` : langue
    courante, repli sur le français pour une clé manquante)."""
    template = _TRANSLATIONS.get(i18n.get_language(), STRINGS).get(key)
    if template is None:
        template = STRINGS[key]
    return template.format(**kwargs) if kwargs else template


_TRANSLATIONS = {
    "fr": STRINGS,
    "en": STRINGS_EN,
}


_ERROR_MESSAGE_KEYS = {
    "reference_invalide": "error_reference_invalide",
    "licence_requise": "error_licence_requise",
    "licence_invalide": "error_licence_invalide",
    "licence_expiree": "error_licence_expiree",
    "licence_revoquee": "error_licence_revoquee",
    "quota_licence_depasse": "error_quota_licence_depasse",
    # Serveur mal réglé (LICENCE_MODE ≠ "prod") : même message qu'une
    # configuration manquante, rien que l'utilisateur puisse corriger.
    "licence_non_supportee": "error_configuration_manquante",
    "trop_de_requetes": "error_trop_de_requetes",
    "erreur_interne": "error_erreur_interne",
    "recherche_ia_indisponible": "error_recherche_ia_indisponible",
    "ia_surchargee": "error_ia_surchargee",
    "configuration_manquante": "error_configuration_manquante",
    "erreur_api_ia": "error_erreur_api_ia",
    "reponse_ia_non_json": "error_reponse_ia_non_json",
    "serveur_injoignable": "error_serveur_injoignable",
    "delai_depasse": "error_delai_depasse",
    "reponse_invalide": "error_reponse_invalide",
    "erreur_inattendue": "error_erreur_inattendue",
}


def friendly_error_message(code: str, message_serveur: str = "") -> str:
    """Message clair pour un code d'erreur de `client.py::RechercheErreur`.
    `message_serveur` (le champ `message` optionnel du serveur, ex. pour
    `recherche_ia_indisponible`) est interpolé en phrase secondaire plutôt
    qu'affiché seul -- reste compréhensible pour un débutant même si le
    serveur renvoie un détail technique, et n'ajoute rien quand il est
    vide."""
    key = _ERROR_MESSAGE_KEYS.get(code, "error_generique")
    suffixe = f" {message_serveur}" if message_serveur else ""
    if key == "error_recherche_ia_indisponible":
        return tr(key, message_serveur=suffixe)
    return tr(key)


__all__ = ["STRINGS", "tr", "friendly_error_message"]
