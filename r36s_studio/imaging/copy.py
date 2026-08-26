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


class OperationCancelled(Exception):
    """Levée par `copy_range` quand `should_cancel` répond True — l'écran
    Exécution (§5 point 5) exige un bouton Annuler actif pendant la
    copie."""

    def __init__(self, done: int):
        super().__init__(f"opération annulée après {done} octets")
        self.done = done


@dataclass
class ProgressEvent:
    done: int
    total: int
    speed: float  # octets/seconde


ProgressCallback = Callable[[ProgressEvent], None]
CancelCheck = Callable[[], bool]


def copy_range(
    source: BinaryIO,
    destination: BinaryIO,
    total_bytes: Optional[int] = None,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
    sector_size: Optional[int] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> int:
    """Copie `source` vers `destination`, par blocs de `block_size`.

    Si `total_bytes` est fourni, la copie s'arrête au plus tôt entre cette
    limite et l'épuisement de `source` (sauvegarde bornée à la fin de la
    dernière partition, cf. `imaging/backup.py`). Si `total_bytes` vaut
    None, la copie continue jusqu'à épuisement de `source` (écriture d'une
    image dont la taille décompressée n'est pas connue à l'avance, cf.
    `imaging/flash.py`) ; la progression rapporte alors `done` comme
    `total`, jamais une estimation trompeuse (règle §2 n°5).

    Si `sector_size` est fourni (écriture Windows, §4.3), le dernier bloc
    est complété par des zéros jusqu'au prochain multiple de cette taille
    avant l'écriture — Windows exige des écritures brutes alignées sur le
    secteur. `done` ne compte que les octets réels de la source, jamais le
    remplissage.

    Si `should_cancel` est fourni, il est consulté avant chaque bloc ; s'il
    répond True, lève `OperationCancelled` (avec `done` déjà écrit et
    fsync-é) plutôt que de s'arrêter silencieusement — l'appelant doit
    pouvoir distinguer une annulation d'une copie terminée normalement.

    Termine par `flush` + `fsync`. Retourne le nombre d'octets réellement
    copiés (lus depuis `source`)."""
    done = 0
    start = time.monotonic()
    last_emit = start
    bounded = total_bytes is not None

    def emit() -> None:
        if on_progress is None:
            return
        elapsed = time.monotonic() - start
        speed = done / elapsed if elapsed > 0 else 0.0
        on_progress(ProgressEvent(done=done, total=(total_bytes if bounded else done), speed=speed))

    cancelled = False
    while not bounded or done < total_bytes:
        if should_cancel is not None and should_cancel():
            cancelled = True
            break

        read_size = min(block_size, total_bytes - done) if bounded else block_size
        chunk = source.read(read_size)
        if not chunk:
            break

        write_chunk = chunk
        if sector_size and len(chunk) % sector_size != 0:
            pad = sector_size - (len(chunk) % sector_size)
            write_chunk = chunk + b"\x00" * pad
        destination.write(write_chunk)
        done += len(chunk)

        now = time.monotonic()
        if now - last_emit >= PROGRESS_INTERVAL:
            emit()
            last_emit = now

    destination.flush()
    try:
        os.fsync(destination.fileno())
    except (AttributeError, OSError):
        pass  # flux sans descripteur de fichier réel (ex. BytesIO en test)

    emit()  # garantit un dernier événement avec le compte final exact

    if cancelled:
        raise OperationCancelled(done)

    return done
