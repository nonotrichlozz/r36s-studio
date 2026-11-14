# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Vérification des mises à jour (docs/claude/packaging.md) : interroge la
dernière Release GitHub. Sans Qt -- appelée depuis un thread par
`gui/partition_runner.py::UpdateCheckRunner`, qui rattrape toute erreur
réseau ou de format et l'écrit au journal (l'app marche hors ligne, §1 ;
2026-11-14 : un échec muet a masqué une vérification cassée un mois)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from r36s_studio import APP_VERSION

_REPO = "nonotrichlozz/r36s-studio"
LATEST_RELEASE_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
# Destination du bouton « Obtenir la nouvelle version » : la page de la
# dernière Release, où l'installeur est joint, gratuit (plus de boutique
# depuis 2026-11-14).
STORE_URL = f"https://github.com/{_REPO}/releases/latest"


def _version_tuple(version: str) -> Optional[Tuple[int, ...]]:
    try:
        return tuple(int(part) for part in version.strip().lstrip("vV").split("."))
    except ValueError:
        return None


def is_newer(tag: str, current: Optional[str] = None) -> bool:
    latest, mine = _version_tuple(tag), _version_tuple(current or APP_VERSION)
    return latest is not None and mine is not None and latest > mine


# Mise à jour automatique (Windows empaqueté seulement, 2026-11-08) :
# l'installeur joint à la Release est téléchargé en arrière-plan, vérifié
# (taille + SHA-256 du champ `digest` de l'API GitHub), puis lancé en un
# clic. Sans `digest` publié, jamais d'installation automatique : repli
# sur le bouton qui ouvre la page de la Release.
INSTALLER_ASSET_NAME = "R36S-Studio-Setup.exe"
_DOWNLOAD_PREFIX = f"https://github.com/{_REPO}/releases/download/"
MAX_INSTALLER_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class LatestRelease:
    tag: str
    notes: str
    installer_url: str = ""
    installer_size: int = 0
    installer_sha256: str = ""

    @property
    def can_auto_install(self) -> bool:
        return bool(self.installer_url and self.installer_size and self.installer_sha256)


def _installer_from_assets(assets) -> Tuple[str, int, str]:
    """`(url, taille, sha256)` de l'installeur Windows, ou des valeurs vides
    si l'asset manque ou n'est pas digne de confiance (adresse hors de la
    Release du dépôt, taille absurde, pas de SHA-256 publiée)."""
    if not isinstance(assets, list):
        return "", 0, ""
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") != INSTALLER_ASSET_NAME:
            continue
        url = str(asset.get("browser_download_url") or "")
        size = asset.get("size")
        digest = str(asset.get("digest") or "")
        sha = digest[len("sha256:"):].lower() if digest.startswith("sha256:") else ""
        if (
            url.startswith(_DOWNLOAD_PREFIX)
            and isinstance(size, int)
            and 0 < size <= MAX_INSTALLER_BYTES
            and len(sha) == 64
            and all(c in "0123456789abcdef" for c in sha)
        ):
            return url, size, sha
    return "", 0, ""


def fetch_latest_release(opener=urllib.request.urlopen, timeout: float = 5) -> LatestRelease:
    """Dernière Release *publiée* (tag, notes, installeur Windows
    vérifiable) -- `/releases/latest` ignore les brouillons. Lève sur toute
    erreur (réseau, quota API, JSON inattendu) : à l'appelant de la dire."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"User-Agent": f"r36s-studio/{APP_VERSION}", "Accept": "application/vnd.github+json"},
    )
    with opener(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    url, size, sha = _installer_from_assets(data.get("assets"))
    return LatestRelease(str(data["tag_name"]), str(data.get("body") or ""), url, size, sha)


def auto_install_supported() -> bool:
    """Seulement l'app Windows installée par l'installeur (PyInstaller,
    `sys.frozen`) : sous macOS/Linux ou en développement, le bouton
    ouvre la page de la Release comme avant."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def default_update_dir() -> Path:
    return Path(tempfile.gettempdir()) / "R36S Studio" / "mise-a-jour"


class InstallerDownloadError(Exception):
    pass


def download_installer(
    release: LatestRelease,
    destination_dir: Optional[Path] = None,
    *,
    opener=urllib.request.urlopen,
    timeout: float = 30,
    block_size: int = 1024 * 1024,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Path:
    """Télécharge l'installeur de `release` et vérifie taille et SHA-256.
    Fichier `.part` pendant le téléchargement, renommé seulement une fois
    vérifié : jamais un installeur incomplet ou modifié laissé à lancer.
    Un fichier déjà présent et juste n'est pas retéléchargé."""
    if not release.can_auto_install:
        raise InstallerDownloadError("aucun installeur vérifiable dans cette version")
    folder = destination_dir or default_update_dir()
    folder.mkdir(parents=True, exist_ok=True)
    safe_tag = "".join(c for c in release.tag if c.isalnum() or c in ".-_") or "derniere"
    final = folder / f"R36S-Studio-Setup-{safe_tag}.exe"
    if final.is_file() and final.stat().st_size == release.installer_size and _sha256_file(final) == release.installer_sha256:
        return final
    partial = final.with_name(final.name + ".part")
    digest = hashlib.sha256()
    done = 0
    request = urllib.request.Request(release.installer_url, headers={"User-Agent": f"r36s-studio/{APP_VERSION}"})
    try:
        with opener(request, timeout=timeout) as response, open(partial, "wb") as out:
            while True:
                if should_cancel is not None and should_cancel():
                    raise InstallerDownloadError("téléchargement annulé")
                chunk = response.read(block_size)
                if not chunk:
                    break
                done += len(chunk)
                if done > release.installer_size:
                    raise InstallerDownloadError("le fichier dépasse la taille annoncée")
                out.write(chunk)
                digest.update(chunk)
    except InstallerDownloadError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001 -- réseau coupé, disque plein...
        partial.unlink(missing_ok=True)
        raise InstallerDownloadError(f"échec du téléchargement : {exc}") from exc
    if done != release.installer_size or digest.hexdigest() != release.installer_sha256:
        partial.unlink(missing_ok=True)
        raise InstallerDownloadError("installeur incomplet ou modifié (taille ou SHA-256)")
    os.replace(partial, final)
    return final


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Options Inno Setup : installation sans questions (barre de progression
# visible), l'installeur ferme R36S Studio s'il est encore ouvert, puis le
# relance à la fin (`/RELANCER=1`, lu par le [Code] de
# windows_installer.iss -- jamais par défaut, sinon le test d'installation
# silencieuse de la CI resterait bloqué sur l'app ouverte).
INSTALLER_ARGS = ("/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELANCER=1")


def launch_installer(path: Path, popen=None) -> None:
    """Lance l'installeur détaché : il doit survivre à la fermeture de
    R36S Studio, qui quitte juste après (`MainWindow`). Pas d'UAC :
    `PrivilegesRequired=lowest`."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    (popen or subprocess.Popen)([str(path), *INSTALLER_ARGS], creationflags=flags, close_fds=True)

