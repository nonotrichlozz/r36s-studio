# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Boucle de copie brute par blocs (§4.3) : lire, écrire, cumuler les
octets, émettre une progression réelle (jamais simulée — règle §2 non
négociable n°5), au maximum ~4 fois par seconde."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import BinaryIO, Callable, List, Optional

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
    # Passe en cours quand une opération en a plusieurs (« copy » par
    # défaut ; « verify_source »/« verify_image », `source_verify.py`) --
    # chaque passe a sa propre progression réelle, de 0 à `total`.
    phase: str = "copy"


ProgressCallback = Callable[[ProgressEvent], None]
CancelCheck = Callable[[], bool]


class ProgressThrottle:
    """Émission limitée à ~4/seconde pour les passes de relecture
    (`source_verify.py`), même cadence que `copy_range`. `total=None` :
    taille inconnue, `done` rapporté comme `total` (jamais une estimation
    trompeuse, règle §2 n°5)."""

    def __init__(self, on_progress: Optional[ProgressCallback], total: Optional[int], phase: str):
        self._on_progress = on_progress
        self._total = total
        self._phase = phase
        self._start = self._last_emit = time.monotonic()

    def _emit(self, done: int) -> None:
        elapsed = time.monotonic() - self._start
        speed = done / elapsed if elapsed > 0 else 0.0
        total = self._total if self._total is not None else done
        self._on_progress(ProgressEvent(done=done, total=total, speed=speed, phase=self._phase))

    def update(self, done: int) -> None:
        now = time.monotonic()
        if self._on_progress is not None and now - self._last_emit >= PROGRESS_INTERVAL:
            self._emit(done)
            self._last_emit = now

    def finish(self, done: int) -> None:
        if self._on_progress is not None:
            self._emit(done)


def copy_range(
    source: BinaryIO,
    destination: BinaryIO,
    total_bytes: Optional[int] = None,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
    sector_size: Optional[int] = None,
    should_cancel: Optional[CancelCheck] = None,
    block_digests: Optional[List[str]] = None,
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

    Si `block_digests` est fourni, le SHA-256 de chaque bloc *réellement
    lu* (avant tout remplissage) y est ajouté, dans l'ordre -- la première
    lecture de la double lecture de la source (`source_verify.py`).

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
        if block_digests is not None:
            block_digests.append(hashlib.sha256(chunk).hexdigest())

        write_chunk = chunk
        if sector_size and len(chunk) % sector_size != 0:
            pad = sector_size - (len(chunk) % sector_size)
            write_chunk = chunk + b"\x00" * pad
        try:
            destination.write(write_chunk)
        except OSError as exc:
            # Diagnostic non encore confirmé (Windows, `[Errno 9] Bad file
            # descriptor` observé y compris après verrouillage complet de
            # toutes les partitions du disque, §4.3) -- ce contexte
            # (octets déjà écrits, temps écoulé depuis le début de la
            # copie) atteint déjà le journal de bord via le chemin
            # existant (IO_ERROR -> str(exc), §5 vocabulaire : le message
            # brut suit toujours le message convivial) sans nouveau
            # mécanisme : de quoi confirmer si l'échec survient toujours
            # au même octet/délai caractéristique lors du prochain test
            # sur du vrai matériel, plutôt que de reguesser à l'aveugle.
            elapsed = time.monotonic() - start
            raise OSError(f"{exc} (après {done} octets écrits, {elapsed:.1f} s depuis le début de la copie)") from exc
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
