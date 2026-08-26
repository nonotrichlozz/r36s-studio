"""Emplacement du journal du worker élevé.

Utile quand l'élévation échoue silencieusement côté GUI : `osascript`
(macOS) et `pkexec`/`sudo` (Linux) n'écrivent l'erreur réelle que sur leur
propre `stderr`, jamais dans le fichier de progression du protocole (§3) —
sans ce journal, un échec comme "No module named r36s_studio" (le worker
lancé depuis un répertoire de travail qui n'a aucune raison de contenir le
projet) disparaissait complètement, remplacé par un message générique côté
GUI."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def log_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path.home() / ".config"
    path = base / "r36s-studio" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def elevation_log_path() -> Path:
    """Écrasé à chaque lancement élevé — reflète toujours la dernière
    tentative, pas un historique."""
    return log_dir() / "elevation.log"
