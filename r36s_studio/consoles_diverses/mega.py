# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Dossier public MEGA : liste des fichiers, adresse de téléchargement et
déchiffrement (source `mega` de `telechargement.py`, muOS).

Un lien de dossier `https://mega.nz/folder/<ID>#<CLÉ>` porte la clé AES
du dossier dans son fragment. Via l'API publique (`g.api.mega.co.nz/cs`,
sans compte) :

1. `{"a": "f", "c": 1, "r": 1}` liste les nœuds ; la clé de chaque nœud
   (`k`, chiffrée en AES-ECB par la clé du dossier) donne pour un fichier
   la clé AES-128 (moitiés XOR) et le nonce CTR ; ses attributs (`a`,
   AES-CBC, préfixe `MEGA{`) donnent son nom.
2. `{"a": "g", "g": 1, "ssl": 2, "n": <handle>}` donne une adresse HTTPS
   temporaire ; le contenu est chiffré en AES-128-CTR (`dechiffreur`).

Vérifié le 2026-10-17 sur le dossier muOS 2601.1 (images par console +
`hash.txt` portant les SHA-256). Ce qui casse le plus souvent : le quota
de transfert gratuit de MEGA (HTTP 509 en cours de route) et le lien du
dossier, qui change à chaque version de muOS.
"""

from __future__ import annotations

import base64
import json
import re
import struct
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

API_URL = "https://g.api.mega.co.nz/cs?id=0&n={dossier}"
MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_HASH_FILE_BYTES = 64 * 1024

_DOSSIER = re.compile(r"^/folder/([A-Za-z0-9_-]{8,})$")
_CLE = re.compile(r"^[A-Za-z0-9_-]{22}$")

# opener(url, data) -> réponse lisible (`read`) en gestionnaire de contexte.
PostOpener = Callable[[str, Optional[bytes]], Any]


class MegaErreur(Exception):
    """Dossier illisible, nœud introuvable ou réponse inattendue de MEGA."""


@dataclass(frozen=True)
class LienDossier:
    dossier: str
    cle: bytes  # 16 octets


@dataclass(frozen=True)
class FichierMega:
    handle: str
    nom: str
    taille: int
    cle: bytes  # AES-128
    nonce: bytes  # 8 premiers octets du compteur CTR


def lien_dossier(url: str) -> Optional[LienDossier]:
    """`https://mega.nz/folder/<ID>#<CLÉ>` -> `LienDossier`, `None` pour
    tout autre lien (hôte, chemin ou clé inattendus)."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    match = _DOSSIER.match(parsed.path or "")
    if parsed.scheme != "https" or parsed.hostname != "mega.nz" or not match or not _CLE.match(parsed.fragment or ""):
        return None
    return LienDossier(dossier=match.group(1), cle=_b64(parsed.fragment))


def _b64(texte: str) -> bytes:
    texte = texte.replace("-", "+").replace("_", "/").replace(",", "")
    return base64.b64decode(texte + "=" * (-len(texte) % 4))


def _aes(cle: bytes, mode):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms

    return Cipher(algorithms.AES(cle), mode).decryptor()


def _ecb(cle: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import modes

    d = _aes(cle, modes.ECB())
    return d.update(data) + d.finalize()


def _nom_dechiffre(cle: bytes, attributs: str) -> Optional[str]:
    from cryptography.hazmat.primitives.ciphers import modes

    data = _b64(attributs)
    if not data or len(data) % 16:
        return None
    d = _aes(cle, modes.CBC(bytes(16)))
    clair = (d.update(data) + d.finalize()).rstrip(bytes(1))
    if not clair.startswith(b"MEGA{"):
        return None
    try:
        nom = json.loads(clair[4:].decode("utf-8")).get("n")
    except (ValueError, AttributeError):
        return None
    return nom if isinstance(nom, str) else None


def _appel(lien: LienDossier, requete: dict, opener: PostOpener) -> Any:
    with opener(API_URL.format(dossier=lien.dossier), json.dumps([requete]).encode()) as response:
        raw = response.read(MAX_API_RESPONSE_BYTES + 1)
    if len(raw) > MAX_API_RESPONSE_BYTES:
        raise MegaErreur("réponse de MEGA trop grande")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise MegaErreur("réponse de MEGA illisible") from exc
    # Erreur MEGA : un entier négatif, seul ou dans la liste.
    if isinstance(payload, int) or (isinstance(payload, list) and payload and isinstance(payload[0], int)):
        raise MegaErreur(f"MEGA a refusé la requête (code {payload if isinstance(payload, int) else payload[0]})")
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise MegaErreur("réponse de MEGA inattendue")
    return payload[0]


def lister(lien: LienDossier, opener: PostOpener) -> List[FichierMega]:
    """Fichiers du dossier (sous-dossiers compris), noms déchiffrés. Un
    nœud indéchiffrable est ignoré, jamais deviné."""
    noeuds = _appel(lien, {"a": "f", "c": 1, "r": 1}, opener).get("f")
    if not isinstance(noeuds, list):
        raise MegaErreur("liste de fichiers absente")
    fichiers = []
    for n in noeuds:
        if not isinstance(n, dict) or n.get("t") != 0:
            continue
        taille = n.get("s")
        if not isinstance(taille, int) or not isinstance(n.get("a"), str) or not isinstance(n.get("h"), str):
            continue
        for part in str(n.get("k", "")).split("/"):
            if ":" not in part:
                continue
            try:
                brute = _ecb(lien.cle, _b64(part.split(":", 1)[1]))
            except ValueError:
                continue
            if len(brute) != 32:
                continue
            k = struct.unpack(">8I", brute)
            cle = struct.pack(">4I", k[0] ^ k[4], k[1] ^ k[5], k[2] ^ k[6], k[3] ^ k[7])
            nom = _nom_dechiffre(cle, n["a"])
            if nom is not None:
                fichiers.append(FichierMega(n["h"], nom, taille, cle, struct.pack(">2I", k[4], k[5])))
                break
    return fichiers


def url_telechargement(lien: LienDossier, fichier: FichierMega, opener: PostOpener) -> str:
    """Adresse HTTPS temporaire du contenu chiffré, sur un serveur MEGA."""
    url = _appel(lien, {"a": "g", "g": 1, "ssl": 2, "n": fichier.handle}, opener).get("g")
    if not isinstance(url, str) or not url_contenu_sure(url):
        raise MegaErreur("adresse de téléchargement inattendue")
    return url


def url_contenu_sure(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = parsed.hostname or ""
    return parsed.scheme == "https" and (host == "mega.co.nz" or host.endswith(".mega.co.nz") or host.endswith(".mega.nz"))


def dechiffreur(cle: bytes, nonce: bytes) -> Callable[[bytes], bytes]:
    """Fonction à appliquer, dans l'ordre, à chaque bloc téléchargé."""
    from cryptography.hazmat.primitives.ciphers import modes

    d = _aes(cle, modes.CTR(nonce + bytes(8)))
    return d.update


def lire_sha256(lien: LienDossier, fichiers: List[FichierMega], nom: str, opener: PostOpener) -> Optional[str]:
    """SHA-256 de `nom` lue dans un `hash.txt` du dossier (`<hex> <nom>`
    par ligne, format muOS), `None` s'il n'y en a pas ou s'il est illisible
    -- jamais une erreur : la somme est un contrôle en plus."""
    for f in fichiers:
        if f.nom.lower() != "hash.txt" or f.taille > MAX_HASH_FILE_BYTES:
            continue
        try:
            url = url_telechargement(lien, f, opener)
            with opener(url, None) as response:
                texte = dechiffreur(f.cle, f.nonce)(response.read(MAX_HASH_FILE_BYTES + 1)).decode("utf-8", "replace")
        except (OSError, ValueError, MegaErreur):
            return None
        sommes: Dict[str, str] = {}
        for ligne in texte.splitlines():
            parts = ligne.split()
            if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
                sommes[parts[1].lstrip("*")] = parts[0].lower()
        return sommes.get(nom)
    return None


__all__ = [
    "FichierMega",
    "LienDossier",
    "MegaErreur",
    "dechiffreur",
    "lien_dossier",
    "lire_sha256",
    "lister",
    "url_contenu_sure",
    "url_telechargement",
]
