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

"""Chaînes propres au package `consoles_diverses/`, isolées de
`gui/strings.py` (§CLAUDE.md du package, règle d'isolation demandée par la
spec) -- seule une clé de libellé de bouton d'entrée vit dans
`gui/strings.py`, puisque le bouton lui-même appartient à des écrans
existants (`HomeScreen`/`AssistedLandingScreen`). Même vocabulaire que le
reste de l'application (§5 de CLAUDE.md racine) : aucun terme technique,
jamais de jargon."""

from __future__ import annotations

STRINGS = {
    "screen_title": "Consoles diverses",
    "back_button": "← Retour à l'accueil",
    "reference_placeholder": "Référence de la console (ex. RG35XX, SF3000HD...)",
    "search_button": "Rechercher",
    "settings_button": "Réglages",
    "searching_status": "Recherche en cours…",
    "badge_verified": "Vérifié",
    "badge_unverified": "Non vérifié",
    "restriction_commerciale_banner": "Licence non commerciale : usage commercial interdit.",
    "unverified_banner": "Informations trouvées automatiquement, non vérifiées.",
    "licence_a_verifier_mention": "Licence à vérifier",
    "identity_fabricant": "Fabricant : {valeur}",
    "identity_soc": "SoC : {valeur}",
    "identity_architecture": "Architecture : {valeur}",
    "identity_os_type": "Type de système : {valeur}",
    "category_frontend": "Front-end",
    "category_systeme_cfw": "Système / CFW",
    "category_firmware_origine": "Firmware d'origine",
    "category_mises_a_jour": "Mises à jour",
    "category_empty": "Aucune option connue dans cette catégorie.",
    "incompatibles_title": "Incompatible avec",
    "sources_title": "Sources",
    "no_info_title": "Aucune information trouvée",
    "no_info_message": "Le serveur n'a trouvé aucune information sur cette console.",
    "retry_button": "Réessayer",
    "option_licence": "Licence : {valeur}",
    "option_source_url": "Source : {valeur}",
    # Réglages
    "settings_title": "Réglages — Consoles diverses",
    "settings_server_url_label": "Adresse du serveur",
    "settings_licence_label": "Clé de licence",
    "settings_save_button": "Enregistrer",
    "settings_cancel_button": "Annuler",
    "settings_no_keyring_warning": (
        "Aucun trousseau système disponible sur cet ordinateur : la clé sera "
        "mémorisée seulement pour cette session, à ressaisir au prochain lancement."
    ),
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
    "error_licence_requise": "Une clé de licence est nécessaire pour la recherche automatique. Renseigne-la dans les réglages de cette section.",
    "error_licence_invalide": "La clé de licence renseignée n'est pas reconnue par le serveur. Vérifie-la dans les réglages.",
    "error_recherche_ia_indisponible": "La recherche automatique est momentanément indisponible.{message_serveur}",
    "error_configuration_manquante": "Le serveur n'est pas configuré correctement. Contacte l'administrateur du serveur.",
    "error_erreur_api_ia": "La recherche automatique a rencontré un problème. Réessaie plus tard.",
    "error_reponse_ia_non_json": "La recherche automatique a renvoyé une réponse invalide. Réessaie plus tard.",
    "error_serveur_injoignable": "Impossible de joindre le serveur. Vérifie l'adresse dans les réglages et ta connexion.",
    "error_delai_depasse": "Le serveur met trop de temps à répondre (plus de 30 secondes). Réessaie.",
    "error_reponse_invalide": "Le serveur a renvoyé une réponse inattendue.",
    "error_erreur_inattendue": "Une erreur inattendue est survenue.",
    "error_generique": "Une erreur est survenue.",
}


def tr(key: str, **kwargs) -> str:
    """Traduit `key` et l'interpole avec `kwargs` -- point d'entrée unique
    vers `STRINGS` (même contrat que `gui/strings.py::tr`)."""
    template = STRINGS[key]
    return template.format(**kwargs) if kwargs else template


_ERROR_MESSAGE_KEYS = {
    "reference_invalide": "error_reference_invalide",
    "licence_requise": "error_licence_requise",
    "licence_invalide": "error_licence_invalide",
    "recherche_ia_indisponible": "error_recherche_ia_indisponible",
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
