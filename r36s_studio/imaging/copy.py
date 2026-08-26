"""Boucle de copie brute par blocs (§4.3) : lire, écrire, cumuler les
octets, émettre une progression réelle (jamais simulée — règle §2 non
négociable n°5), au maximum ~4 fois par seconde."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import BinaryIO, Callable, Optional

BLOCK_SIZE = 4 * 1024 * 1024  # 4 MiB
PROGRESS_INTERVAL = 0.25  # secondes -> au plus ~4 événements/seconde


@dataclass
class ProgressEvent:
    done: int
    total: int
    speed: float  # octets/seconde


ProgressCallback = Callable[[ProgressEvent], None]


def copy_range(
    source: BinaryIO,
    destination: BinaryIO,
    total_bytes: int,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
) -> int:
    """Copie jusqu'à `total_bytes` octets de `source` vers `destination`,
    par blocs de `block_size`. S'arrête plus tôt si `source` est épuisée
    (ex. fichier plus court que prévu). Termine par `flush` + `fsync`, comme
    prescrit par le brief. Retourne le nombre d'octets réellement copiés."""
    done = 0
    start = time.monotonic()
    last_emit = start

    while done < total_bytes:
        remaining = total_bytes - done
        chunk = source.read(min(block_size, remaining))
        if not chunk:
            break
        destination.write(chunk)
        done += len(chunk)

        now = time.monotonic()
        if on_progress is not None and (now - last_emit >= PROGRESS_INTERVAL or done >= total_bytes):
            elapsed = now - start
            speed = done / elapsed if elapsed > 0 else 0.0
            on_progress(ProgressEvent(done=done, total=total_bytes, speed=speed))
            last_emit = now

    destination.flush()
    try:
        os.fsync(destination.fileno())
    except (AttributeError, OSError):
        pass  # flux sans descripteur de fichier réel (ex. BytesIO en test)
    return done
