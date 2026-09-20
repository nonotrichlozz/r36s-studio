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

"""Téléchargement des « platform-tools » officiels de Google (adb) -- sur
accord explicite de l'utilisateur uniquement (§ adb du brief : "proposer de
télécharger... après accord explicite de l'utilisateur (afficher l'URL et
la taille)"). Jamais embarqué dans le dépôt.

Toute communication réseau passe par un paramètre `opener` injectable
(même contrat que `consoles_diverses/client.py` : reçoit un
`urllib.request.Request` déjà construit) -- aucun test de ce module ne fait
d'appel réseau réel."""

from __future__ import annotations

import platform
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable, Optional

from r36s_studio.config import config_dir

Opener = Callable[[urllib.request.Request], Any]
ProgressCallback = Callable[[int, int], None]
CancelCheck = Callable[[], bool]

REQUEST_TIMEOUT_SECONDS = 30
DOWNLOAD_BLOCK_SIZE = 1024 * 256
_ZIP_TEMP_NAME = "platform-tools-download.zip"

# Une image par OS, comme documenté par Google (aucune version figée dans
# l'URL -- "latest" pointe toujours vers la dernière publiée).
_URLS_BY_SYSTEM = {
    "Windows": "https://dl.google.com/android/repository/platform-tools-latest-windows.zip",
    "Darwin": "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip",
    "Linux": "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
}


class PlatformToolsError(Exception):
    """Échec de récupération/installation des platform-tools -- jamais
    affiché brut à l'écran (§5 vocabulaire du CLAUDE.md racine), traduit
    côté GUI."""


class PlatformToolsDownloadCancelledError(PlatformToolsError):
    pass


class UnsupportedPlatformError(PlatformToolsError):
    """OS sans URL connue -- ne devrait jamais arriver sur les trois OS
    officiellement supportés (§1 du CLAUDE.md racine), mais explicite
    plutôt qu'un `KeyError` brut si ce module tournait un jour ailleurs."""


def _default_opener(request: urllib.request.Request):
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)


def platform_tools_url(system: Optional[str] = None) -> str:
    system = system or platform.system()
    try:
        return _URLS_BY_SYSTEM[system]
    except KeyError as exc:
        raise UnsupportedPlatformError(f"Aucun paquet platform-tools connu pour '{system}'.") from exc


def platform_tools_install_dir() -> Path:
    """Dossier de données de l'app (`config_dir()`, §6 du CLAUDE.md
    racine) -- jamais les Documents de l'utilisateur (`partitions/
    archives.py`, `identify/rocknix.py`) : adb n'est pas un contenu que
    l'utilisateur a produit, c'est un outil interne à l'application."""
    return config_dir() / "platform-tools"


def _adb_executable_name() -> str:
    return "adb.exe" if platform.system() == "Windows" else "adb"


def installed_adb_path() -> Optional[Path]:
    """`None` si les platform-tools n'ont jamais été téléchargés par cette
    app (`adb.resolve_adb_path` regarde d'abord le PATH, ce module n'est
    consulté qu'en repli)."""
    path = platform_tools_install_dir() / _adb_executable_name()
    return path if path.exists() else None


def fetch_platform_tools_size(*, opener: Opener = _default_opener, system: Optional[str] = None) -> Optional[int]:
    """Taille annoncée par le serveur (`Content-Length`, requête `HEAD`) --
    affichée sur l'écran de consentement avant tout téléchargement (brief :
    "afficher l'URL et la taille"). `None` si le serveur ne l'annonce pas
    ou si la requête échoue -- l'écran affiche alors une taille inconnue
    plutôt qu'une valeur inventée (jamais de progression/info simulée,
    §2 règle 5 du CLAUDE.md racine, même esprit appliqué ici)."""
    request = urllib.request.Request(platform_tools_url(system), method="HEAD")
    try:
        with opener(request) as response:
            return _content_length(response)
    except (OSError, ValueError, UnsupportedPlatformError):
        return None


def _content_length(response: Any) -> Optional[int]:
    try:
        raw = response.headers.get("Content-Length")
    except AttributeError:
        return None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def download_and_install(
    *,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
    opener: Opener = _default_opener,
    system: Optional[str] = None,
) -> Path:
    """Télécharge le zip officiel puis l'extrait dans
    `platform_tools_install_dir()` -- le zip de Google contient déjà un
    dossier `platform-tools/` de tête (vérifiable directement sur la page
    de téléchargement du SDK Android), l'extraction reproduit donc
    directement `platform_tools_install_dir()` sans étape de renommage.

    Progression réelle par blocs (règle §2 n°5 du CLAUDE.md racine, même
    principe qu'`identify/rocknix.py::download_asset` même si ce n'est pas
    une écriture disque brute -- une barre figée à 0 % ou 100 % pendant
    plusieurs dizaines de Mo induirait le même faux sentiment de blocage) ;
    annulation coopérative, consultée avant chaque bloc, même sort qu'un
    échec réel (fichier partiel supprimé)."""
    install_dir = platform_tools_install_dir()
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    zip_path = install_dir.parent / _ZIP_TEMP_NAME

    request = urllib.request.Request(platform_tools_url(system))
    done = 0
    try:
        with opener(request) as response:
            total = _content_length(response) or 0
            with open(zip_path, "wb") as out:
                while True:
                    if should_cancel is not None and should_cancel():
                        raise PlatformToolsDownloadCancelledError(f"Téléchargement annulé après {done} octets.")
                    chunk = response.read(DOWNLOAD_BLOCK_SIZE)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        # Taille totale inconnue (`Content-Length` absent) :
                        # repli sur `done` comme total plutôt qu'une valeur
                        # inventée -- même compromis que celui déjà accepté
                        # ailleurs dans ce projet pour un total introuvable
                        # sans décompression complète (CLAUDE.md racine,
                        # historique `.img.xz`).
                        on_progress(done, total if total else done)
    except PlatformToolsDownloadCancelledError:
        zip_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        zip_path.unlink(missing_ok=True)
        raise PlatformToolsError(f"Échec du téléchargement : {exc}") from exc

    if on_progress is not None:
        on_progress(done, done)  # dernier événement, compte final exact (règle §2 n°5)

    try:
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(install_dir.parent)
    except zipfile.BadZipFile as exc:
        zip_path.unlink(missing_ok=True)
        raise PlatformToolsError(f"Archive platform-tools invalide : {exc}") from exc
    zip_path.unlink(missing_ok=True)

    adb_path = installed_adb_path()
    if adb_path is None:
        raise PlatformToolsError("adb introuvable après extraction des platform-tools.")
    if platform.system() != "Windows":
        # Le zip Google conserve les permissions d'origine sur macOS/Linux
        # en pratique, mais `zipfile.extractall` ne les restaure pas de
        # façon fiable sur toutes les versions de Python -- s'assurer
        # explicitement que le binaire reste exécutable plutôt que de
        # dépendre de ce comportement.
        adb_path.chmod(adb_path.stat().st_mode | 0o111)
    return adb_path


__all__ = [
    "Opener",
    "ProgressCallback",
    "CancelCheck",
    "PlatformToolsError",
    "PlatformToolsDownloadCancelledError",
    "UnsupportedPlatformError",
    "platform_tools_url",
    "platform_tools_install_dir",
    "installed_adb_path",
    "fetch_platform_tools_size",
    "download_and_install",
]
