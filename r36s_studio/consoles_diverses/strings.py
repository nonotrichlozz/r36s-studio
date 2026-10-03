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
