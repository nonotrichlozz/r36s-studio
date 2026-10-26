# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Worker élevé pour le bot : `sudo -n <WORKER_COMMAND> <commande> ...
--worker`, le bot restant en utilisateur normal (CLAUDE.md §3 : jamais le
bot entier en root). `WORKER_COMMAND` est un petit script appartenant à
root qui lance `python -m r36s_studio` depuis une copie du projet
appartenant à root ; une règle sudoers NOPASSWD ne vise que lui, et
seulement les commandes du bot (`backup`, `reset-card`) -- voir
docs/bot-telegram.md. Jamais installée automatiquement.

`-n` : sudo n'attend jamais de mot de passe ; règle absente -> échec
immédiat, `ELEVATION_FAILED` (message qui renvoie à la doc).

Le worker émet ses événements JSON Lines (`protocol.py`) sur stdout, lus
ligne par ligne ; Annuler crée le fichier `--cancel-file` (§5), que le
worker surveille. Toutes les vérifications de sécurité sont refaites par
le worker lui-même (`safety`, carte trop grosse ou disque système refusés)."""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

WORKER_COMMAND = "/usr/local/sbin/r36s-studio-worker"
# Seules commandes que le bot lance élevées (et que la règle sudoers autorise).
ALLOWED_COMMANDS = ("backup", "reset-card")

__all__ = ["ALLOWED_COMMANDS", "WORKER_COMMAND", "WorkerResult", "run_worker"]


@dataclass
class WorkerResult:
    ok: bool = False
    error_code: Optional[str] = None
    error_detail: str = ""
    estimate: Optional[int] = None
    logs: List[str] = field(default_factory=list)


def run_worker(
    argv: List[str],
    on_event: Optional[Callable[[dict], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    poll_seconds: float = 0.5,
) -> WorkerResult:
    """Bloquant. `on_event(événement)` pour chaque ligne JSON du worker."""
    if not argv or argv[0] not in ALLOWED_COMMANDS:
        raise ValueError(f"commande non autorisée pour le bot : {argv[:1]}")
    result = WorkerResult()
    with tempfile.TemporaryDirectory(prefix="r36s-bot-") as tmp:
        cancel_file = Path(tmp) / "annuler"
        command = ["sudo", "-n", WORKER_COMMAND, *argv, "--worker", "--cancel-file", str(cancel_file)]
        with open(Path(tmp) / "stderr.txt", "w+", encoding="utf-8", errors="replace") as stderr:
            try:
                process = subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=stderr, text=True, encoding="utf-8", errors="replace"
                )
            except OSError as exc:  # sudo absent
                return WorkerResult(error_code="ELEVATION_FAILED", error_detail=str(exc))
            finished = threading.Event()

            def watch_cancel() -> None:
                while not finished.wait(poll_seconds):
                    if should_cancel is not None and should_cancel():
                        cancel_file.touch()
                        return

            watcher = threading.Thread(target=watch_cancel, daemon=True)
            watcher.start()
            events = 0
            try:
                for line in process.stdout:
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    events += 1
                    kind = event.get("type")
                    if kind == "error" and result.error_code is None:
                        result.error_code = str(event.get("code") or "GENERIC")
                        result.error_detail = str(event.get("msg") or "")
                    elif kind == "done":
                        result.ok = bool(event.get("ok")) and result.error_code is None
                    elif kind == "estimate":
                        result.estimate = event.get("size_bytes")
                    elif kind == "log":
                        result.logs.append(str(event.get("msg") or ""))
                    if on_event is not None:
                        on_event(event)
                process.wait()
            finally:
                finished.set()
            if not result.ok and result.error_code is None:
                # Aucun événement : sudo a refusé (règle absente, mot de passe
                # demandé) ou le script est introuvable. Sinon : worker
                # interrompu sans `error` ni `done`.
                stderr.seek(0)
                result.error_code = "ELEVATION_FAILED" if events == 0 else "WORKER_FAILED"
                result.error_detail = stderr.read().strip() or f"code de sortie {process.returncode}"
    return result
