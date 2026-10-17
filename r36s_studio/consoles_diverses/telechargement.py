# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Téléchargement direct d'un firmware depuis une fiche du catalogue
(champ optionnel `options.*[].telechargement`, voir
`r36s-studio-catalogue/schema/console.schema.json`).

Une option peut décrire où trouver son image :

    "telechargement": {
      "depot": "knulli-cfw/knulli-linux",
      "motif_fichier": "^knulli-h700-rg40xx-v-.*\\.img\\.gz$",
      "url_directe": "https://github.com/.../knulli-h700-rg40xx-v-scarab-20260511.img.gz"
    }

`resoudre` cherche d'abord dans la **dernière** release GitHub de `depot`
le fichier dont le nom correspond à `motif_fichier` -- une nouvelle
version publiée par le projet est donc prise automatiquement, sans
toucher au catalogue. Si l'API GitHub ne répond pas (réseau, limite de
requêtes anonymes) ou ne trouve rien, repli sur `url_directe` (version
figée au moment de la vérification de la fiche).

**Source MEGA** (`"source": "mega"`, muOS, absent de GitHub) : `dossier`
est le lien public `https://mega.nz/folder/<ID>#<CLÉ>` ; le fichier est
choisi par `motif_fichier` parmi ceux du dossier, sa SHA-256 lue dans un
`hash.txt` du dossier quand il existe, et le contenu déchiffré pendant le
téléchargement (`mega.py`, `FichierFirmware.dechiffrement`). Pas de
`depot` : une version antérieure de l'app, qui l'exige, n'affiche donc pas
de bouton. Gofile écarté (2026-10-17) : son API exige un jeton calculé
par un script obfusqué.

Le champ optionnel `apres_flash` liste les fichiers à copier sur la carte
juste après le flash (`partitions/post_flash_copy.py`, mêmes règles de
chemin côté GUI et côté worker).

Une fiche reste une donnée externe (`consoles_diverses/CLAUDE.md`,
durcissement) : seul un dépôt au format `propriétaire/nom` est accepté,
seuls des liens `https://github.com/` (ou un dossier `https://mega.nz/`
et ses serveurs de contenu) sont téléchargés, la taille annoncée est
plafonnée (`MAX_IMAGE_BYTES`), et le nom de
fichier final doit être une image flashable (`.img`, `.img.gz`,
`.img.xz`) sans aucun séparateur de chemin. Aucune écriture disque ici :
le téléchargement lui-même passe par `identify/rocknix.py::download_asset`
(blocs, progression réelle, annulation, somme sha256), et le flash par la
fenêtre Confirmation habituelle (§2 n°6), jamais sautée."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple
from urllib.parse import unquote, urlparse

from r36s_studio import __version__
from r36s_studio.partitions.post_flash_copy import PostFlashCopy, copies_depuis_json

from . import mega

API_RELEASE_LATEST = "https://api.github.com/repos/{depot}/releases/latest"
REQUEST_TIMEOUT_SECONDS = 30
MAX_API_RESPONSE_BYTES = 4 * 1024 * 1024

_DEPOT_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_EXTENSIONS_FLASHABLES = (".img", ".img.gz", ".img.xz")
_HOTE_AUTORISE = "github.com"
# Plus grande image raisonnable pour une carte de console (muOS RG40XX-V :
# 4,4 Go compressés, 8,2 Gio décompressés).
MAX_IMAGE_BYTES = 16 * 1024**3
SOURCES = ("github", "mega")

Opener = Callable[..., Any]  # opener(url) en GET, opener(url, data) en POST (MEGA)


class TelechargementErreur(Exception):
    """Aucun fichier téléchargeable trouvé (ni dans la dernière release, ni
    via `url_directe`)."""


@dataclass(frozen=True)
class Telechargement:
    depot: str  # "" pour la source MEGA
    motif_fichier: str
    url_directe: Optional[str] = None
    # Copies à faire sur la carte juste après le flash (ex. `dtb.img` de
    # ROCKNIX sur H700), transmises au worker élevé par `MainWindow`
    # (`--copy-after-flash`, `partitions/post_flash_copy.py`).
    apres_flash: Tuple[PostFlashCopy, ...] = ()
    source: str = "github"
    dossier: Optional[str] = None  # lien de dossier MEGA (`source == "mega"`)


@dataclass(frozen=True)
class FichierFirmware:
    nom: str
    url: str
    taille: int = 0
    sha256: Optional[str] = None
    depuis_derniere_release: bool = False
    # (clé AES-128, nonce) : contenu chiffré à déchiffrer en AES-CTR pendant
    # le téléchargement (`mega.dechiffreur`), `None` pour GitHub.
    dechiffrement: Optional[Tuple[bytes, bytes]] = None


def telechargement_depuis_json(data: Any) -> Optional[Telechargement]:
    """Parsing défensif (même principe que `models.py`) : `None` dès que
    l'entrée est absente ou inexploitable, jamais d'exception -- une fiche
    sans téléchargement direct reste simplement affichée avec son lien."""
    if not isinstance(data, dict):
        return None
    source = data.get("source", "github")
    if source not in SOURCES:
        return None
    depot = data.get("depot", "" if source == "mega" else None)
    dossier = data.get("dossier")
    motif = data.get("motif_fichier")
    if source == "mega":
        if not (isinstance(dossier, str) and mega.lien_dossier(dossier)):
            return None
        depot, dossier = "", dossier
    elif not isinstance(depot, str) or not _DEPOT_PATTERN.match(depot):
        return None
    else:
        dossier = None
    if not isinstance(motif, str) or not motif:
        return None
    try:
        re.compile(motif)
    except re.error:
        return None
    url_directe = data.get("url_directe")
    if not (isinstance(url_directe, str) and url_github_sure(url_directe)):
        url_directe = None
    # Une seule entrée `apres_flash` invalide suffit à retirer le bouton :
    # jamais une installation à moitié réglée (console qui ne démarre pas).
    copies = copies_depuis_json(data.get("apres_flash"))
    if copies is None:
        return None
    return Telechargement(
        depot=depot,
        motif_fichier=motif,
        url_directe=url_directe if source == "github" else None,
        apres_flash=tuple(copies),
        source=source,
        dossier=dossier,
    )


def url_github_sure(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme == "https" and parsed.hostname == _HOTE_AUTORISE


def nom_fichier_sur(nom: str) -> bool:
    if not nom or "/" in nom or "\\" in nom or nom in (".", "..") or nom.startswith("."):
        return False
    return nom.lower().endswith(_EXTENSIONS_FLASHABLES)


def _default_opener(url: str, data: Optional[bytes] = None):
    """GET (API GitHub) ou POST JSON (API MEGA, `data`)."""
    headers = {"User-Agent": f"R36S-Studio/{__version__}"}
    if data is None:
        headers["Accept"] = "application/vnd.github+json"
    else:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)


def _taille_acceptable(taille: Any) -> bool:
    return not isinstance(taille, int) or taille <= MAX_IMAGE_BYTES


def _sha256_depuis_digest(digest: Any) -> Optional[str]:
    """GitHub publie `"digest": "sha256:<hex>"` pour chaque fichier d'une
    release -- vérifié au téléchargement quand il est présent."""
    if isinstance(digest, str) and digest.lower().startswith("sha256:"):
        valeur = digest.split(":", 1)[1].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", valeur):
            return valeur
    return None


def _depuis_derniere_release(tel: Telechargement, opener: Opener) -> Optional[FichierFirmware]:
    with opener(API_RELEASE_LATEST.format(depot=tel.depot)) as response:
        raw = response.read(MAX_API_RESPONSE_BYTES + 1)
    if len(raw) > MAX_API_RESPONSE_BYTES:
        return None
    payload = json.loads(raw)
    assets = payload.get("assets") if isinstance(payload, dict) else None
    if not isinstance(assets, list):
        return None
    motif = re.compile(tel.motif_fichier)
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        nom = asset.get("name")
        url = asset.get("browser_download_url")
        if not (isinstance(nom, str) and isinstance(url, str)):
            continue
        if not motif.search(nom) or not nom_fichier_sur(nom) or not url_github_sure(url):
            continue
        taille = asset.get("size")
        if not _taille_acceptable(taille):
            continue
        return FichierFirmware(
            nom=nom,
            url=url,
            taille=taille if isinstance(taille, int) and taille > 0 else 0,
            sha256=_sha256_depuis_digest(asset.get("digest")),
            depuis_derniere_release=True,
        )
    return None


def _depuis_mega(tel: Telechargement, opener: Opener) -> FichierFirmware:
    lien = mega.lien_dossier(tel.dossier or "")
    if lien is None:
        raise TelechargementErreur("lien de dossier MEGA invalide")
    try:
        fichiers = mega.lister(lien, opener)
        motif = re.compile(tel.motif_fichier)
        for f in fichiers:
            if motif.search(f.nom) and nom_fichier_sur(f.nom) and 0 < f.taille <= MAX_IMAGE_BYTES:
                return FichierFirmware(
                    nom=f.nom,
                    url=mega.url_telechargement(lien, f, opener),
                    taille=f.taille,
                    sha256=mega.lire_sha256(lien, fichiers, f.nom, opener),
                    depuis_derniere_release=True,
                    dechiffrement=(f.cle, f.nonce),
                )
    except (OSError, ValueError, mega.MegaErreur) as exc:
        raise TelechargementErreur(f"MEGA ne répond pas comme prévu : {exc}") from exc
    raise TelechargementErreur(f"Aucun fichier correspondant à {tel.motif_fichier!r} dans le dossier MEGA.")


def resoudre(tel: Telechargement, *, opener: Opener = _default_opener) -> FichierFirmware:
    """Fichier à télécharger pour `tel` : dernière release d'abord, puis
    `url_directe` (GitHub) ; fichier du dossier (MEGA). Lève
    `TelechargementErreur` si rien ne donne un fichier flashable."""
    if tel.source == "mega":
        return _depuis_mega(tel, opener)
    try:
        trouve = _depuis_derniere_release(tel, opener)
    except (OSError, ValueError):
        trouve = None
    if trouve is not None:
        return trouve

    if tel.url_directe:
        nom = unquote(urlparse(tel.url_directe).path.rsplit("/", 1)[-1])
        if nom_fichier_sur(nom):
            return FichierFirmware(nom=nom, url=tel.url_directe)

    raise TelechargementErreur(f"Aucun fichier correspondant à {tel.motif_fichier!r} dans {tel.depot}.")


__all__ = [
    "Telechargement",
    "FichierFirmware",
    "TelechargementErreur",
    "telechargement_depuis_json",
    "url_github_sure",
    "nom_fichier_sur",
    "resoudre",
]
