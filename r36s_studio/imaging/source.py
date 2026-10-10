# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Préparation de l'accès en lecture brute à un périphérique, par OS.

Phase 2 : lecture seule uniquement — rien n'est jamais écrit sur un
périphérique ici (§4.3, §2 règle n°6)."""

from __future__ import annotations

import contextlib
import platform
import queue
import subprocess
import threading
import time
from typing import Callable, Iterator

from .copy import OperationCancelled


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


# --- Chien de garde de lecture ------------------------------------------------
#
# Cas réel : la carte noname (fabricant SD 0xFE) bloque parfois une lecture
# pendant des heures, sans erreur et sans données -- la barre restait figée
# en silence. Un `read()` bloqué dans le noyau ne s'interrompt pas depuis le
# même thread : chaque lecture part dans un thread daemon, et le thread
# appelant attend son résultat par petites tranches.

DEFAULT_STALL_TIMEOUT_SECONDS = 60
# Délai avant de signaler l'attente (`on_stall`) : une lecture de 4 Mio
# prend moins d'une seconde même sur une carte lente (~6 Mo/s), quelques
# secondes sans réponse sont déjà anormales.
STALL_NOTICE_SECONDS = 5.0
_WAIT_TICK_SECONDS = 1.0

StallCallback = Callable[[float, float], None]  # (secondes d'attente, délai d'abandon)
_READ_THREAD_NAME = "r36s-source-read"


def has_stuck_reads() -> bool:
    """Un thread de lecture abandonné (blocage ou annulation pendant un
    blocage) est encore vivant -- `__main__.main` termine alors le worker
    par `os._exit`."""
    return any(t.name == _READ_THREAD_NAME and t.is_alive() for t in threading.enumerate())


class SourceNotResponding(OSError):
    """Aucun octet lu depuis `seconds` secondes : la carte source ne répond
    plus (probablement défaillante)."""

    def __init__(self, seconds: float, done: int):
        super().__init__(f"la carte source ne répond plus : aucune donnée depuis {seconds:.0f} s (après {done} octets lus)")
        self.seconds = seconds
        self.done = done


class StallWatchedReader:
    """Enveloppe un flux de lecture brute : `read()` lève
    `SourceNotResponding` si aucune donnée n'arrive en `timeout` secondes,
    appelle `on_stall(secondes_d_attente, timeout)` environ chaque seconde
    au-delà de `STALL_NOTICE_SECONDS` (la GUI montre qu'on est bloqué, pas
    une barre figée), et reste annulable pendant l'attente (`should_cancel`
    -> `OperationCancelled`).

    Possède le flux (gestionnaire de contexte) : après un blocage, il n'est
    **pas** refermé -- le thread bloqué tient encore le verrou interne du
    flux, `close()` resterait bloqué lui aussi. Le descripteur est libéré
    à la fin du processus worker, qui s'arrête juste après l'erreur.
    ponytail: un thread par lecture (~2 500 pour 10 Go, coût négligeable
    face à 4 Mio lus) ; un thread persistant si ça devait compter."""

    def __init__(self, stream, timeout: float = DEFAULT_STALL_TIMEOUT_SECONDS, on_stall=None, should_cancel=None):
        self._stream = stream
        self._timeout = timeout
        self._on_stall = on_stall
        self._should_cancel = should_cancel
        self._bytes_read = 0
        self._stuck = False

    def read(self, n: int = -1) -> bytes:
        results: "queue.Queue" = queue.Queue(maxsize=1)

        def run() -> None:
            try:
                results.put((True, self._stream.read(n)))
            except BaseException as exc:  # relancée dans le thread appelant
                results.put((False, exc))

        threading.Thread(target=run, daemon=True, name=_READ_THREAD_NAME).start()
        start = time.monotonic()
        while True:
            try:
                ok, value = results.get(timeout=_WAIT_TICK_SECONDS)
                break
            except queue.Empty:
                waited = time.monotonic() - start
                if self._should_cancel is not None and self._should_cancel():
                    self._stuck = True
                    raise OperationCancelled(self._bytes_read)
                if waited >= self._timeout:
                    self._stuck = True
                    raise SourceNotResponding(waited, self._bytes_read)
                if waited >= STALL_NOTICE_SECONDS and self._on_stall is not None:
                    self._on_stall(waited, self._timeout)
        if not ok:
            raise value
        self._bytes_read += len(value)
        return value

    def seek(self, *args):
        return self._stream.seek(*args)

    def tell(self):
        return self._stream.tell()

    def fileno(self):
        return self._stream.fileno()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        if not self._stuck:
            self._stream.close()
        return False
