"""Préparation de l'accès en lecture brute à un périphérique, par OS.

Phase 2 : lecture seule uniquement — rien n'est jamais écrit sur un
périphérique ici (§4.3, §2 règle n°6)."""

from __future__ import annotations

import contextlib
import platform
import subprocess
from typing import Iterator


def raw_read_path(path: str) -> str:
    """Chemin à ouvrir pour la lecture brute. Sur macOS, `/dev/rdiskN`
    (accès caractère) est environ 10x plus rapide que `/dev/diskN` (accès
    bloc). Inchangé sur les autres OS."""
    if platform.system() == "Darwin" and path.startswith("/dev/disk"):
        return path.replace("/dev/disk", "/dev/rdisk", 1)
    return path


@contextlib.contextmanager
def prepared_source(path: str) -> Iterator[str]:
    """Démonte le périphérique si nécessaire, puis fournit le chemin de
    lecture brute à utiliser. Sur macOS, `diskutil unmountDisk` doit
    précéder la lecture de `/dev/rdiskN` — sans quoi macOS verrouille
    l'accès brut tant qu'une partition est montée.

    Le succès ne se juge que sur le code de retour (`check=True` lève
    `CalledProcessError` si et seulement s'il est non nul) — jamais sur la
    présence de texte sur stderr : `diskutil` y écrit parfois son message
    de succès (« Unmount of all volumes on diskN was successful »), qui ne
    doit surtout pas être pris pour un échec. `capture_output=True` évite
    en plus que ce message ne se retrouve mélangé à la sortie du worker
    lui-même, ce qui perturbait la remontée d'erreur d'`osascript` (`do
    shell script` utilise le texte du dernier flux non vide pour construire
    son message d'erreur quand la commande échoue plus loin)."""
    if platform.system() == "Darwin":
        subprocess.run(["diskutil", "unmountDisk", path], check=True, capture_output=True)
    yield raw_read_path(path)
