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
from dataclasses import asdict, dataclass
from pathlib import Path

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


@dataclass
class AppConfig:
    ui_mode: str = DEFAULT_UI_MODE
    firmware: str = DEFAULT_FIRMWARE


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
    return AppConfig(ui_mode=ui_mode, firmware=firmware)


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
