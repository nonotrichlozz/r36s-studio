# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Jeton du bot et liste blanche des conversations autorisées, lus dans
`telegram.json` à côté de `config.json` (`~/.config/r36s-studio/` sous
Linux) -- jamais dans le dépôt ni dans le code (CLAUDE.md §2 n°2) :

    {"token": "123456:ABC...", "chat_ids": [123456789]}

Sous Linux/macOS, le fichier doit n'être lisible que par son propriétaire
(`chmod 600`) : sinon il est refusé, le jeton n'est jamais lu. Le jeton
n'apparaît dans aucun message ni journal."""

from __future__ import annotations

import json
import os
import platform
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Optional

from r36s_studio import config as app_config

CONFIG_FILENAME = "telegram.json"

__all__ = ["BotConfig", "BotConfigError", "CONFIG_FILENAME", "load_bot_config", "telegram_config_path"]


class BotConfigError(Exception):
    """`key` : clé de `strings.py` du message à afficher (avec `path`)."""

    def __init__(self, key: str, path: Path):
        super().__init__(key)
        self.key = key
        self.path = path


@dataclass(frozen=True)
class BotConfig:
    token: str
    chat_ids: FrozenSet[int]

    def __repr__(self) -> str:  # jamais le jeton, même dans une trace
        return f"BotConfig(token=<masqué>, chat_ids={sorted(self.chat_ids)})"


def telegram_config_path() -> Path:
    return app_config.config_dir() / CONFIG_FILENAME


def load_bot_config(path: Optional[Path] = None) -> BotConfig:
    path = path or telegram_config_path()
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        raise BotConfigError("bot_config_missing", path) from None
    except OSError:
        raise BotConfigError("bot_config_invalid", path) from None
    if platform.system() != "Windows" and mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise BotConfigError("bot_config_permissions", path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise BotConfigError("bot_config_invalid", path) from None
    token = raw.get("token") if isinstance(raw, dict) else None
    chat_ids = raw.get("chat_ids") if isinstance(raw, dict) else None
    if not isinstance(token, str) or ":" not in token.strip():
        raise BotConfigError("bot_config_invalid", path)
    if (
        not isinstance(chat_ids, list)
        or not chat_ids
        or not all(isinstance(c, int) and not isinstance(c, bool) for c in chat_ids)
    ):
        raise BotConfigError("bot_config_invalid", path)
    return BotConfig(token=token.strip(), chat_ids=frozenset(chat_ids))


def write_template(path: Path) -> None:
    """Modèle à compléter, créé en 600 dès le départ (jamais un instant
    lisible par les autres comptes de la machine)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"token": "", "chat_ids": []}, handle, indent=2)
