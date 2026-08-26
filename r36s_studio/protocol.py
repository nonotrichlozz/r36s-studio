"""Émission d'événements JSON Lines sur stdout — protocole GUI ↔ worker du
brief (§3). Une ligne JSON par événement, pour que la future interface
graphique puisse lire `stdout` ligne par ligne."""

from __future__ import annotations

import json
import sys


def emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def emit_progress(done: int, total: int, speed: float) -> None:
    emit({"type": "progress", "done": done, "total": total, "speed": round(speed)})


def emit_log(msg: str, level: str = "info") -> None:
    emit({"type": "log", "level": level, "msg": msg})


def emit_error(code: str, msg: str) -> None:
    emit({"type": "error", "code": code, "msg": msg})


def emit_done(ok: bool) -> None:
    emit({"type": "done", "ok": ok})
