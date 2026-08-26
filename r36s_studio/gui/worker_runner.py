"""Pilote un worker élevé (backup ou flash) depuis la GUI : le lance via
`elevate.launch_elevated_worker`, surveille son fichier de progression et
traduit chaque ligne JSON (§3) en signaux Qt pour les écrans."""

from __future__ import annotations

import json
import os
import platform
import tempfile
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from . import elevate, logs

POLL_INTERVAL_MS = 200

# Limitation confirmée par test (voir CLAUDE.md §3) : `osascript … with
# administrator privileges` obtient les droits root pour le worker, mais TCC
# bloque quand même l'accès à /dev/rdiskN, le processus élevé n'ayant aucune
# identité TCC propre à autoriser en Accès complet au disque. Résolu en
# phase 7 seulement (appli packagée = identité TCC). En attendant, ce cas
# précis doit produire un message explicite plutôt que l'ELEVATION_FAILED
# générique.
MACOS_TCC_BLOCKED = "MACOS_TCC_BLOCKED"
_MACOS_TCC_HINT = (
    "macOS empêche l'accès à la carte SD même avec les droits administrateur : "
    "la protection TCC (Accès complet au disque) ne peut pas être accordée à un "
    "processus lancé de cette façon. Cette limitation sera levée quand "
    "l'application sera empaquetée. En attendant, utilise la ligne de commande "
    "depuis un Terminal auquel tu as accordé l'Accès complet au disque "
    "(Réglages Système → Confidentialité et sécurité) :\n"
    "    sudo python3 -m r36s_studio backup --device ... --output ...\n"
    "    sudo python3 -m r36s_studio flash --image ... --device ..."
)


def _is_macos_tcc_blocked(detail: str) -> bool:
    if platform.system() != "Darwin" or not detail:
        return False
    lowered = detail.lower()
    return "operation not permitted" in lowered and "rdisk" in lowered


class WorkerRunner(QObject):
    progress = Signal(int, int, float)  # done, total, speed
    log = Signal(str, str)  # level, msg
    error = Signal(str, str)  # code, msg
    finished = Signal(bool)  # ok

    def __init__(self, argv: List[str], parent=None):
        """`argv` : la commande worker sans `--worker`/`--progress-file`/
        `--cancel-file`, ex. `["backup", "--device", "/dev/disk3",
        "--output", "x.img"]` — ces trois options sont ajoutées par
        `start()`."""
        super().__init__(parent)
        self._argv = argv
        self._process = None
        self._progress_file: Optional[Path] = None
        self._cancel_file: Optional[Path] = None
        self._log_path: Optional[Path] = None
        self._offset = 0
        self._done_emitted = False
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._progress_file = _make_temp_path("r36s_studio_progress_", ".jsonl")
        self._cancel_file = _make_temp_path("r36s_studio_cancel_", ".flag")
        self._log_path = logs.elevation_log_path()
        full_argv = [
            *self._argv,
            "--worker",
            "--progress-file",
            str(self._progress_file),
            "--cancel-file",
            str(self._cancel_file),
        ]
        self._process = elevate.launch_elevated_worker(full_argv, stderr_log=self._log_path)
        self._timer.start()

    def cancel(self) -> None:
        """Crée le fichier que le worker surveille (`--cancel-file`) pour
        s'arrêter proprement à la prochaine itération de sa boucle de
        copie — plus sûr qu'un `kill()` du processus en pleine écriture
        brute. `kill()` reste un filet de sécurité best-effort si le
        worker ne répond pas (voir limite documentée sur `_process.kill`
        ci-dessous)."""
        if self._cancel_file is not None:
            self._cancel_file.touch(exist_ok=True)

    def force_kill(self) -> None:
        """Dernier recours si `cancel()` ne suffit pas. Sur macOS/Linux,
        `self._process` est le processus `osascript`/`pkexec` lui-même :
        le tuer ne termine pas nécessairement le worker élevé qu'il a
        lancé (limite connue de ce squelette — `cancel()` coopératif via
        le fichier d'annulation est la voie normale)."""
        if self._process is not None:
            try:
                self._process.kill()
            except Exception:
                pass
        self._stop()

    def _poll(self) -> None:
        self._read_new_lines()
        if self._done_emitted:
            self._stop()
            return
        if self._process is not None and self._process.poll() is not None:
            # Le processus élevé s'est terminé sans émettre "done" :
            # élévation refusée/annulée avant le premier événement, ou
            # plantage. On relit une dernière fois au cas où l'écriture du
            # dernier événement et la fin du process se chevauchaient.
            self._read_new_lines()
            if not self._done_emitted:
                detail = self._read_elevation_log()
                if _is_macos_tcc_blocked(detail):
                    self.error.emit(MACOS_TCC_BLOCKED, _MACOS_TCC_HINT)
                else:
                    msg = "L'opération a été annulée ou l'élévation a échoué."
                    if detail:
                        msg = f"{msg}\n{detail}"
                    self.error.emit("ELEVATION_FAILED", msg)
                self.finished.emit(False)
                self._done_emitted = True
            self._stop()

    def _read_elevation_log(self) -> str:
        """Contenu du journal d'élévation (stderr d'`osascript`/`pkexec`/
        `sudo`, voir `elevate.py`) — c'est souvent la seule trace de la
        cause réelle d'un échec d'élévation, le protocole JSON Lines du
        worker n'ayant jamais démarré dans ce cas."""
        if self._log_path is None:
            return ""
        try:
            return self._log_path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""

    def _read_new_lines(self) -> None:
        if self._progress_file is None or not self._progress_file.exists():
            return
        with open(self._progress_file, "r", encoding="utf-8") as f:
            f.seek(self._offset)
            new_data = f.read()
            self._offset = f.tell()
        for line in new_data.splitlines():
            line = line.strip()
            if line:
                self._dispatch(line)

    def _dispatch(self, line: str) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return
        etype = event.get("type")
        if etype == "progress":
            self.progress.emit(event.get("done", 0), event.get("total", 0), event.get("speed", 0.0))
        elif etype == "log":
            self.log.emit(event.get("level", "info"), event.get("msg", ""))
        elif etype == "error":
            self.error.emit(event.get("code", ""), event.get("msg", ""))
        elif etype == "done":
            self._done_emitted = True
            self.finished.emit(bool(event.get("ok")))

    def _stop(self) -> None:
        self._timer.stop()
        for path in (self._progress_file, self._cancel_file):
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass


def _make_temp_path(prefix: str, suffix: str) -> Path:
    """Réserve un nom de fichier temporaire unique sans laisser le fichier
    exister. Important pour `--cancel-file` : `_make_should_cancel` (dans
    `__main__.py`) teste `os.path.exists(...)`, donc un fichier créé vide
    dès le départ serait interprété comme une annulation immédiate."""
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=suffix)
    os.close(fd)
    os.unlink(path)
    return Path(path)
