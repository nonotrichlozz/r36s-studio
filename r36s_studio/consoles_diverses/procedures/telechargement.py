# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Téléchargement avec reprise (en-tête HTTP `Range`) et SHA-256
obligatoire, pour les fichiers d'une procédure (plusieurs Go).

- Fichier final déjà présent avec la bonne SHA-256 : rien n'est retéléchargé.
- Coupure : le morceau reçu reste dans `<nom>.part` ; la fois suivante, la
  suite seulement est demandée. Un serveur qui ignore `Range` (réponse 200
  au lieu de 206) fait repartir de zéro.
- SHA-256 différente à la fin : le `.part` est supprimé, jamais renommé.

`opener` injectable (même principe que `client.py`) : aucun test ne touche
le réseau."""

from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from r36s_studio import __version__

USER_AGENT = f"R36S-Studio/{__version__}"  # Cloudflare/GitHub : jamais « Python-urllib »
_BLOC = 1024 * 1024


class TelechargementErreur(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code  # "reseau", "empreinte", "annule", "url"
        self.detail = detail


def sha256_fichier(chemin: Path, annule: Callable[[], bool] = lambda: False) -> str:
    empreinte = hashlib.sha256()
    with open(chemin, "rb") as fichier:
        for bloc in iter(lambda: fichier.read(_BLOC), b""):
            if annule():
                raise TelechargementErreur("annule")
            empreinte.update(bloc)
    return empreinte.hexdigest()


def telecharger(
    url: str,
    destination: Path,
    sha256: str,
    progression: Callable[[int, int], None] = lambda fait, total: None,
    annule: Callable[[], bool] = lambda: False,
    opener: Optional[Callable] = None,
) -> Path:
    """Télécharge `url` vers `destination` et vérifie sa SHA-256.
    `progression(octets reçus, total ou 0)`. Lève `TelechargementErreur`."""
    if not url.startswith("https://"):
        raise TelechargementErreur("url", url)
    sha256 = sha256.lower()
    if destination.exists():
        if sha256_fichier(destination, annule) == sha256:
            taille = destination.stat().st_size
            progression(taille, taille)
            return destination
        destination.unlink()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partiel = destination.with_name(destination.name + ".part")
    deja = partiel.stat().st_size if partiel.exists() else 0

    requete = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    if deja:
        requete.add_header("Range", f"bytes={deja}-")
    ouvrir = opener or urllib.request.urlopen
    try:
        reponse = ouvrir(requete, timeout=60)
    except OSError as exc:
        raise TelechargementErreur("reseau", str(exc)) from exc

    with reponse:
        statut = getattr(reponse, "status", 200)
        if deja and statut != 206:
            deja = 0  # le serveur renvoie tout depuis le début
        longueur = int(reponse.headers.get("Content-Length") or 0)
        total = deja + longueur if longueur else 0
        empreinte = hashlib.sha256()
        if deja:
            with open(partiel, "rb") as existant:
                for bloc in iter(lambda: existant.read(_BLOC), b""):
                    empreinte.update(bloc)
        fait = deja
        with open(partiel, "ab" if deja else "wb") as sortie:
            while True:
                if annule():
                    raise TelechargementErreur("annule")
                try:
                    bloc = reponse.read(_BLOC)
                except OSError as exc:
                    raise TelechargementErreur("reseau", str(exc)) from exc
                if not bloc:
                    break
                sortie.write(bloc)
                empreinte.update(bloc)
                fait += len(bloc)
                progression(fait, total)
    if total and fait != total:
        raise TelechargementErreur("reseau", f"fichier incomplet ({fait}/{total} octets)")
    if empreinte.hexdigest() != sha256:
        partiel.unlink()
        raise TelechargementErreur("empreinte", destination.name)
    os.replace(partiel, destination)
    return destination


__all__ = ["TelechargementErreur", "telecharger", "sha256_fichier", "USER_AGENT"]
