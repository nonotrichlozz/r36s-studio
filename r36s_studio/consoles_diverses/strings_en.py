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

"""Chaînes anglaises de la section « Consoles diverses » -- mêmes clés et
mêmes variables `{…}` que `strings.STRINGS` (vérifié par
`tests/test_consoles_diverses_strings.py`). Isolées ici plutôt que dans
`gui/strings_en.py` (règle d'isolation, `consoles_diverses/CLAUDE.md`)."""

from __future__ import annotations

STRINGS_EN = {
    "screen_title": "Other consoles",
    "back_button": "← Back to home",
    "reference_placeholder": "Console reference (e.g. RG35XX, SF3000HD...)",
    "search_button": "Search",
    "settings_button": "Settings",
    "searching_status": "Searching…",
    "searching_status_lente": "The search is taking longer than expected…",
    "badge_verified": "Verified",
    "badge_unverified": "Not verified",
    "unverified_note": "Found automatically, not verified.",
    "restriction_commerciale_banner": "Non-commercial license: commercial use is forbidden.",
    "restriction_commerciale_chip": "Non-commercial",
    "licence_a_verifier_mention": "License to be checked",
    "licence_non_detectee": "License not detected",
    "info_title": "Good to know",
    "android_notice": (
        "Android console: it is prepared through ADB, not through the SD card (coming soon to R36S Studio)."
    ),
    "hardware_title": "Hardware",
    "hardware_label_soc": "SoC",
    "hardware_label_architecture": "Architecture",
    "hardware_label_os_type": "System",
    "value_not_found": "Not found",
    "category_frontend": "Front-end",
    "category_systeme_cfw": "System / CFW",
    "category_firmware_origine": "Original firmware",
    "category_mises_a_jour": "Updates",
    "categories_without_options": "Nothing found for: {liste}",
    "no_options_at_all_message": "Little information found for this console.",
    "incompatibles_title": "Do not install: {liste}",
    "open_page_button": "Open the page",
    "open_github_button": "Open on GitHub",
    "sources_title": "Sources ({total})",
    "no_info_title": "No information found",
    "no_info_message": "The server found no information about this console.",
    "retry_button": "Try again",
    "settings_title": "Settings — Other consoles",
    "settings_server_url_label": "Server address",
    "settings_licence_label": "License key",
    "settings_save_button": "Save",
    "settings_cancel_button": "Cancel",
    "settings_no_keyring_warning": (
        "No system keychain is available on this computer: the key will only be remembered for this "
        "session, and you will need to enter it again next time."
    ),
    "settings_url_empty": "Enter a server address.",
    "settings_url_invalid_scheme": "The address must start with http:// or https://.",
    "settings_url_http_remote_refused": (
        "An http:// address is only accepted for localhost or 127.0.0.1 -- otherwise your license key "
        "would travel unencrypted over the network. Use https:// for a remote server."
    ),
    "error_reference_invalide": "This reference is not valid (characters not allowed, or too long).",
    "error_licence_requise": (
        "A license key is needed for the automatic search. Enter it in the settings of this section."
    ),
    "error_licence_invalide": "The license key entered is not recognized by the server. Check it in the settings.",
    "error_recherche_ia_indisponible": "The automatic search is temporarily unavailable.{message_serveur}",
    "error_configuration_manquante": (
        "The server is not configured correctly. Contact the server's administrator."
    ),
    "error_erreur_api_ia": "The automatic search ran into a problem. Try again later.",
    "error_reponse_ia_non_json": "The automatic search returned an invalid response. Try again later.",
    "error_serveur_injoignable": (
        "Could not reach the server. Check the address in the settings and your connection."
    ),
    "error_delai_depasse": "The server is taking too long to respond (more than 90 seconds). Try again.",
    "error_ia_surchargee": "The search service is overloaded at the moment. Try again in a few minutes.",
    "error_reponse_invalide": "The server returned an unexpected response.",
    "error_erreur_inattendue": "An unexpected error occurred.",
    "error_generique": "An error occurred.",
}
