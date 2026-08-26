"""Émission d'événements JSON Lines sur stdout — protocole GUI ↔ worker du
brief (§3). Une ligne JSON par événement, pour que la future interface
graphique puisse lire `stdout` ligne par ligne."""

from __future__ import annotations

import json
import sys

_stream = None  # None -> sys.stdout, résolu dynamiquement à chaque emit()


def configure(stream) -> None:
    """Redirige les événements vers `stream` au lieu de stdout. Utilisé par
    le worker élevé (`--progress-file`, voir `gui/elevate.py`) : une fois
    la frontière de privilège franchie (UAC, osascript, pkexec), le
    processus appelant ne peut plus lire le stdout du worker en flux sans
    mécanisme supplémentaire — un fichier partagé est la solution la plus
    simple et portable sur les trois OS."""
    global _stream
    _stream = stream


def emit(event: dict) -> None:
    stream = _stream if _stream is not None else sys.stdout
    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
    stream.flush()


def emit_progress(done: int, total: int, speed: float) -> None:
    emit({"type": "progress", "done": done, "total": total, "speed": round(speed)})


def emit_log(msg: str, level: str = "info") -> None:
    emit({"type": "log", "level": level, "msg": msg})


def emit_error(code: str, msg: str) -> None:
    emit({"type": "error", "code": code, "msg": msg})


def emit_done(ok: bool) -> None:
    emit({"type": "done", "ok": ok})
