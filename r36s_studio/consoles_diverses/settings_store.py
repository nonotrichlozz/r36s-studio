# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE


"""Adresse du serveur de la section « Consoles diverses » -- en dur
(`adresse_serveur`), jamais saisie depuis l'interface.

La clé de licence ne vit plus ici : elle est dans `config.json`
(`AppConfig.consoles_diverses_licence_key`), lue et écrite par `MainWindow`
avec le reste de la configuration. L'ancien stockage au trousseau système
(`keyring`) a été retiré : il a produit deux bugs réels sous Windows (clé
figée à une ancienne valeur, voir `consoles_diverses/CLAUDE.md`), et une
clé de licence par client se révoque côté serveur si elle fuit -- ce n'est
pas un mot de passe."""

from __future__ import annotations

import os
import sys
from typing import Optional
from urllib.parse import urlsplit

from .strings import tr

# Serveur de production, en dur -- jamais saisi ni modifiable depuis
# l'interface : un client ne saurait pas quoi mettre, et une adresse mal
# tapée rendait la section inutilisable sans message clair. Le seul
# moyen de viser un autre serveur (Worker local pendant le développement)
# est `R36S_STUDIO_CLOUD_URL`, jamais accessible depuis la GUI -- même
# principe que `R36S_STUDIO_DEV=1` (CLAUDE.md §6).
PRODUCTION_SERVER_URL = "https://r36s-studio-cloud.r36studio.workers.dev"
SERVER_URL_ENV_VAR = "R36S_STUDIO_CLOUD_URL"


def valider_adresse_serveur(url: str) -> Optional[str]:
    """Durcissement demandé, point 3 : `https://` toujours accepté ;
    `http://` seulement pour `localhost`/`127.0.0.1` -- sinon la clé de
    licence (en-tête `X-Licence-Key`) circulerait en clair sur le réseau.
    Retourne un message d'erreur clair (à afficher tel quel) si invalide,
    `None` si l'adresse est acceptable."""
    url = (url or "").strip()
    if not url:
        return tr("settings_url_empty")
    try:
        parts = urlsplit(url)
    except ValueError:
        return tr("settings_url_invalid_scheme")
    if parts.scheme == "https":
        return None
    if parts.scheme == "http":
        if parts.hostname in ("localhost", "127.0.0.1"):
            return None
        return tr("settings_url_http_remote_refused")
    return tr("settings_url_invalid_scheme")


def adresse_serveur() -> str:
    """Adresse du serveur interrogé par la recherche (`POST /recherche`),
    relue à chaque appel : `PRODUCTION_SERVER_URL`, sauf si
    `R36S_STUDIO_CLOUD_URL` est définie et passe `valider_adresse_serveur`
    (https, ou http seulement vers localhost -- la clé de licence ne
    circule jamais en clair). Une valeur refusée n'est jamais ignorée en
    silence : signalée sur la sortie d'erreur, repli sur la production."""
    surcharge = os.environ.get(SERVER_URL_ENV_VAR, "").strip()
    if not surcharge:
        return PRODUCTION_SERVER_URL
    erreur = valider_adresse_serveur(surcharge)
    if erreur:
        print(
            f"[Consoles diverses] {SERVER_URL_ENV_VAR} refusée ({surcharge!r}) : {erreur} "
            f"-- serveur de production utilisé.",
            file=sys.stderr,
        )
        return PRODUCTION_SERVER_URL
    return surcharge


__all__ = [
    "PRODUCTION_SERVER_URL",
    "SERVER_URL_ENV_VAR",
    "adresse_serveur",
    "valider_adresse_serveur",
]
