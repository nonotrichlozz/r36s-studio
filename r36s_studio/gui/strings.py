"""Chaînes de l'interface, isolées ici dès le départ pour faciliter une
traduction future (§5 : « chaînes isolées dans un fichier de traduction »).

Vocabulaire : aucun terme technique ('périphérique bloc', '/dev/sdb',
'partition') ne doit apparaître ailleurs que dans le panneau Détails —
on dit "ta carte SD", pas "le périphérique bloc"."""

from __future__ import annotations

STRINGS = {
    "app_title": "R36S Studio",
    # Accueil
    "home_title": "Que veux-tu faire ?",
    "home_tile_backup": "Sauvegarder ma carte",
    "home_tile_backup_desc": "Enregistre le contenu actuel de ta carte SD dans un fichier.",
    "home_tile_flash": "Préparer une nouvelle carte",
    "home_tile_flash_desc": "Écrit le système sur une carte SD neuve.",
    "home_tile_inject_boot": "Remettre l'écran d'origine",
    "home_tile_copy_games": "Copier des jeux",
    "home_coming_soon": "Bientôt disponible",
    # Choix du périphérique
    "device_title": "Choisis ta carte SD",
    "device_refresh": "Rafraîchir",
    "device_empty": "Aucune carte SD détectée. Branche-la puis clique sur Rafraîchir.",
    "device_next": "Suivant",
    "device_back": "Retour",
    # Choix du fichier
    "file_title_backup": "Où enregistrer la sauvegarde ?",
    "file_title_flash": "Choisis le fichier image",
    "file_browse": "Parcourir…",
    "file_next": "Suivant",
    "file_back": "Retour",
    # Confirmation
    "confirm_title": "Attention",
    "confirm_checkbox": "Je comprends que toutes les données de cette carte seront effacées",
    "confirm_erase": "Toutes les données de « {display} » ({size_go:.1f} Go) seront définitivement effacées.",
    "confirm_go": "Effacer et écrire",
    "confirm_cancel": "Annuler",
    # Exécution
    "execute_title_backup": "Sauvegarde en cours…",
    "execute_title_flash": "Écriture en cours…",
    "execute_cancel": "Annuler",
    "execute_speed": "{speed:.1f} Mo/s",
    "execute_eta": "Temps restant estimé : {eta}",
    "execute_eta_unknown": "Temps restant estimé : —",
    # Résultat
    "result_success": "Terminé !",
    "result_error": "Un problème est survenu",
    "result_cancelled": "Opération annulée",
    "result_eject": "Éjecter la carte",
    "result_home": "Retour à l'accueil",
    # Divers
    "details_toggle": "Détails",
}


def tr(key: str, **kwargs) -> str:
    """Traduit `key` et l'interpole avec `kwargs` — point d'entrée unique
    vers `STRINGS`, pour qu'un futur fichier par langue n'ait qu'un seul
    endroit à brancher."""
    template = STRINGS[key]
    return template.format(**kwargs) if kwargs else template
