"""Configuration utilisateur persistée (§6) : `~/.config/r36s-studio/
config.json` (`%APPDATA%\\r36s-studio\\config.json` sous Windows, même
convention que `gui/logs.py:log_dir()`). Contient uniquement des
préférences locales -- jamais de secret (§9).

Aujourd'hui : le mode d'interface choisi (assisté/expert, §5 mode
assisté), mémorisé d'un lancement à l'autre. Un fichier absent ou
corrompu retombe silencieusement sur les valeurs par défaut plutôt que de
lever -- une préférence perdue n'est jamais bloquante, contrairement à une
détection de carte ratée (§4.5), mais le principe est le même."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_UI_MODE = "assisted"
_VALID_UI_MODES = {"assisted", "expert"}


@dataclass
class AppConfig:
    ui_mode: str = DEFAULT_UI_MODE


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
    return AppConfig(ui_mode=ui_mode)


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")
