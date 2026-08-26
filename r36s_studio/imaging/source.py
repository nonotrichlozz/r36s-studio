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
    l'accès brut tant qu'une partition est montée."""
    if platform.system() == "Darwin":
        subprocess.run(["diskutil", "unmountDisk", path], check=True)
    yield raw_read_path(path)
