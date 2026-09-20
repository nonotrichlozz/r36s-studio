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

"""Configuration utilisateur persistée (§6) : `~/.config/r36s-studio/
config.json` (`%APPDATA%\\r36s-studio\\config.json` sous Windows, même
convention que `gui/logs.py:log_dir()`). Contient uniquement des
préférences locales -- jamais de secret (§9).

Aujourd'hui : le mode d'interface choisi (assisté/expert, §5 mode
assisté) et le firmware retenu pour le flash (mode expert), mémorisés
d'un lancement à l'autre. Un fichier absent ou corrompu retombe
silencieusement sur les valeurs par défaut plutôt que de lever -- une
préférence perdue n'est jamais bloquante, contrairement à une détection
de carte ratée (§4.5), mais le principe est le même."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID

DEFAULT_UI_MODE = "assisted"
_VALID_UI_MODES = {"assisted", "expert"}

# Firmware choisi pour l'étape de flash (§4.6 étape C, mode expert
# uniquement -- le parcours de clonage du mode assisté n'a pas de choix
# de firmware, il restaure la propre sauvegarde de l'utilisateur).
# Mémorisé d'un lancement à l'autre comme `ui_mode`, avec le même
# principe de repli silencieux sur la valeur par défaut. Dérivé du
# catalogue (`identify/firmware_catalog.py`) plutôt qu'un second ensemble
# à resynchroniser à la main à chaque ajout d'entrée. ROCKNIX plutôt
# qu'ArkOS par défaut : ArkOS est désormais archivé (§4.6) -- un vrai
# changement de comportement pour toute installation qui n'a jamais
# choisi explicitement de firmware, volontaire ici plutôt que de
# continuer à proposer par défaut un firmware qu'on affiche par ailleurs
# comme archivé.
DEFAULT_FIRMWARE = "rocknix"
_VALID_FIRMWARES = set(FIRMWARE_BY_ID)

# Système de fichiers choisi pour « Remettre la carte à zéro » (§4.3 bis,
# mode expert uniquement). Mémorisé comme `firmware`/`ui_mode` -- signalé
# par un utilisateur : une console (SF3000HD) qui ne lit que le FAT32,
# rendue inutilisable par le formatage exFAT par défaut. exFAT reste le
# défaut ici (le cas le plus courant, §4.3 bis -- l'EASYROMS de la carte
# source d'une R36S d'origine est déjà en exFAT sur le matériel de test) ;
# FAT32 reste un choix explicite, jamais présumé.
DEFAULT_RESET_CARD_FILESYSTEM = "exfat"
_VALID_RESET_CARD_FILESYSTEMS = {"exfat", "fat32"}

# Section « Consoles diverses » (consoles_diverses/, étape 1) -- adresse du
# serveur r36s-studio-cloud interrogé par POST /recherche. Seule l'adresse
# vit ici : jamais la clé de licence (trousseau système, `consoles_
# diverses/settings_store.py`, §9 de CLAUDE.md racine -- aucun secret dans
# un fichier de configuration). Pas d'ensemble de valeurs valides comme
# `_VALID_FIRMWARES` ci-dessus : une adresse de serveur est un champ libre,
# pas un choix parmi un catalogue fixe -- sa validité (schéma http(s),
# localhost pour http:// nu) est vérifiée à la saisie par `consoles_
# diverses/settings_store.py::valider_adresse_serveur`, pas ici.
DEFAULT_CONSOLES_DIVERSES_SERVER_URL = "http://localhost:8787"

# Outil « Doublons de jeux » (docs/doublons.md) -- liste par défaut des
# dossiers ignorés (« cochables », modifiable par l'utilisateur ensuite,
# jamais un ensemble figé comme `_VALID_FIRMWARES` ci-dessus). "Tout
# dossier commençant par un point" reste une règle structurelle du
# parcours (`doublons/scan.py`), jamais une entrée de cette liste.
DEFAULT_DOUBLONS_IGNORED_FOLDERS = [
    "cubegm",
    "rootfs",
    "BGM",
    "Music",
    "Movie",
    "Photo",
    "Ebook",
    "SteamLibrary",
    ".res",
    "Imgs",
    "media",
    "bios",
]

# Coché par défaut au premier lancement (§ garde-fou 1 de l'outil «
# Doublons de jeux ») -- l'utilisateur décoche sciemment pour agir pour
# de vrai, jamais l'inverse.
DEFAULT_DOUBLONS_SIMULATION_MODE = True


@dataclass
class AppConfig:
    ui_mode: str = DEFAULT_UI_MODE
    firmware: str = DEFAULT_FIRMWARE
    reset_card_filesystem: str = DEFAULT_RESET_CARD_FILESYSTEM
    consoles_diverses_server_url: str = DEFAULT_CONSOLES_DIVERSES_SERVER_URL
    doublons_ignored_folders: List[str] = field(default_factory=lambda: list(DEFAULT_DOUBLONS_IGNORED_FOLDERS))
    doublons_simulation_mode: bool = DEFAULT_DOUBLONS_SIMULATION_MODE


def config_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path.home() / ".config"
    path = base / "r36s-studio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppConfig()

    ui_mode = raw.get("ui_mode")
    if ui_mode not in _VALID_UI_MODES:
        ui_mode = DEFAULT_UI_MODE
    firmware = raw.get("firmware")
    if firmware not in _VALID_FIRMWARES:
        firmware = DEFAULT_FIRMWARE
    reset_card_filesystem = raw.get("reset_card_filesystem")
    if reset_card_filesystem not in _VALID_RESET_CARD_FILESYSTEMS:
        reset_card_filesystem = DEFAULT_RESET_CARD_FILESYSTEM
    consoles_diverses_server_url = raw.get("consoles_diverses_server_url")
    if not isinstance(consoles_diverses_server_url, str) or not consoles_diverses_server_url.strip():
        consoles_diverses_server_url = DEFAULT_CONSOLES_DIVERSES_SERVER_URL
    doublons_ignored_folders = raw.get("doublons_ignored_folders")
    if not isinstance(doublons_ignored_folders, list) or not all(
        isinstance(name, str) for name in doublons_ignored_folders
    ):
        doublons_ignored_folders = list(DEFAULT_DOUBLONS_IGNORED_FOLDERS)
    doublons_simulation_mode = raw.get("doublons_simulation_mode")
    if not isinstance(doublons_simulation_mode, bool):
        doublons_simulation_mode = DEFAULT_DOUBLONS_SIMULATION_MODE
    return AppConfig(
        ui_mode=ui_mode,
        firmware=firmware,
        reset_card_filesystem=reset_card_filesystem,
        consoles_diverses_server_url=consoles_diverses_server_url,
        doublons_ignored_folders=doublons_ignored_folders,
        doublons_simulation_mode=doublons_simulation_mode,
    )


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")


# Tuile « Web » personnelle (accueil, réservée à l'auteur du projet --
# jamais destinée à un client). Lue uniquement depuis cette variable
# d'environnement à chaque appel, jamais un champ d'`AppConfig` : un
# champ persisté finirait dans `config.json` sur le disque, copiable par
# erreur dans un rapport de bug ou une capture d'écran -- une variable
# d'environnement ne quitte jamais la machine qui la définit. Absente par
# défaut, y compris dans tout binaire empaqueté distribué (aucun script
# de `packaging/`, aucun `.spec`, ne la définit ni ne la code en dur) --
# `os.environ.get` se comporte identiquement en développement et dans un
# exécutable PyInstaller figé (`sys.frozen`), rien de spécifique à gérer
# pour ce dernier cas.
def personal_web_url() -> Optional[str]:
    """URL du tableau de bord personnel si configurée pour cette session,
    `None` si la variable est absente ou si elle n'est pas en https --
    jamais d'URL non sécurisée ouverte automatiquement."""
    url = os.environ.get("R36S_STUDIO_WEB_URL", "").strip()
    if not url.startswith("https://"):
        return None
    return url
