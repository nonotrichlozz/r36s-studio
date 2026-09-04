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

# Confirmé sur du vrai matériel (CLAUDE.md §3) : une fois l'app empaquetée
# relancée directement depuis son propre binaire (`elevate.py`,
# `MacosAuthorizedProcess`, plutôt que via `osascript`), un enfant du binaire
# signé du bundle hérite bien de son autorisation Accès complet au disque --
# la limitation TCC documentée depuis la phase 4 est donc résolue, mais
# seulement une fois cette autorisation accordée à l'app. Ce code reste donc
# nécessaire : c'est exactement le message qu'on veut tant que l'utilisateur
# ne l'a pas encore fait (ou après une reconstruction de l'app, qui change sa
# signature ad hoc et invalide l'autorisation précédente -- voir l'écran
# Aide, `screens.HelpScreen`).
MACOS_TCC_BLOCKED = "MACOS_TCC_BLOCKED"
_MACOS_TCC_HINT = (
    "macOS empêche l'accès à la carte SD même avec les droits administrateur : "
    "R36S Studio n'a pas (ou plus) la permission Accès complet au disque. Va "
    "dans Réglages Système → Confidentialité et sécurité → Accès complet au "
    "disque, ajoute R36S Studio (ou retire-le puis rajoute-le s'il y figure "
    "déjà : la signature de l'app change à chaque reconstruction, ce qui "
    "invalide l'autorisation précédente), puis relance l'opération. Voir "
    "l'écran Aide depuis l'accueil pour le détail de la procédure."
)


def _is_macos_tcc_blocked(detail: str) -> bool:
    if platform.system() != "Darwin" or not detail:
        return False
    lowered = detail.lower()
    return "operation not permitted" in lowered and "rdisk" in lowered


# Cas confirmé sur du vrai matériel, distinct du blocage /dev/rdiskN
# ci-dessus : `[Errno 1] Operation not permitted` survient aussi sur des
# fichiers ordinaires (l'image à flasher, typiquement) quand ils se trouvent
# dans un des trois dossiers que macOS protège par TCC (Téléchargements,
# Bureau, Documents) — le worker élevé par `osascript` n'a pas la même
# autorisation que Terminal/Finder pour ces emplacements, même si l'un
# d'eux l'a. Ex. réels : '/Users/x/Downloads/ArkOS...img.xz',
# '/Users/x/Desktop/r36s/ArkOS...img.xz'.
MACOS_TCC_PROTECTED_FOLDER = "MACOS_TCC_PROTECTED_FOLDER"
_MACOS_PROTECTED_FOLDER_NAMES = ("downloads", "desktop", "documents")
_MACOS_PROTECTED_FOLDER_HINT = (
    "macOS bloque l'accès à ce fichier parce qu'il se trouve dans un dossier "
    "protégé (Téléchargements, Bureau ou Documents) : le worker élevé n'a pas "
    "la même autorisation que Terminal ou le Finder pour ces emplacements, "
    "même si l'un d'eux l'a. Déplace le fichier ailleurs — par exemple "
    "directement dans ton dossier personnel — puis réessaie."
)


def _is_macos_tcc_protected_folder(detail: str) -> bool:
    if platform.system() != "Darwin" or not detail:
        return False
    lowered = detail.lower()
    if "operation not permitted" not in lowered:
        return False
    return any(f"/{name}/" in lowered for name in _MACOS_PROTECTED_FOLDER_NAMES)


class WorkerRunner(QObject):
    # Bug corrigé, constaté en conditions réelles (flash d'une carte de
    # 32 Go) : `Signal(int, int, float)` mappe `int` sur un `int` C++ 32
    # bits (~2,1 milliards max), largement dépassé par un compte d'octets
    # au-delà de 2 Go. PySide6 échoue alors silencieusement à livrer le
    # signal (`libshiboken: Overflow`, `OverflowError`), ce qui se
    # manifestait côté GUI par un message trompeur, `AttributeError: Slot
    # '...(int,int,double)' not found` -- comme si le slot n'existait pas,
    # alors que le vrai problème est la conversion de l'argument avant même
    # d'atteindre le slot. `"qint64"` (entier 64 bits, jusqu'à ~9,2 * 10^18)
    # couvre toute taille de carte SD réaliste.
    progress = Signal("qint64", "qint64", float)  # done, total, speed
    log = Signal(str, str)  # level, msg
    error = Signal(str, str)  # code, msg
    finished = Signal(bool)  # ok
    # Repli élevé pour l'estimation de la sauvegarde système sans les jeux
    # (§4.3, `backup --system-only --estimate-only`) -- `"qint64"` pour la
    # même raison que `progress` ci-dessus (une taille peut dépasser 2 Go).
    estimate = Signal("qint64")  # size_bytes

    def __init__(self, argv: List[str], parent=None, macos_auth_session=None):
        """`argv` : la commande worker sans `--worker`/`--progress-file`/
        `--cancel-file`, ex. `["backup", "--device", "/dev/disk3",
        "--output", "x.img"]` — ces trois options sont ajoutées par
        `start()`.

        `macos_auth_session` (`elevate.MacosAuthorizationSession`,
        optionnel) : quand fournie, réutilise sa `AuthorizationRef` plutôt
        que d'en créer une nouvelle propre à cette seule opération --
        correctif d'un comportement observé en usage réel où le parcours
        guidé (§5 mode assisté) redemandait l'invite mot de passe à chaque
        étape élevée. `MainWindow` en possède une seule pour toute
        l'application (créée au premier besoin), passée à chaque
        `WorkerRunner` qu'elle construit. Ignoré hors macOS."""
        super().__init__(parent)
        self._argv = argv
        self._macos_auth_session = macos_auth_session
        self._process = None
        self._progress_file: Optional[Path] = None
        self._cancel_file: Optional[Path] = None
        self._log_path: Optional[Path] = None
        self._offset = 0
        self._done_emitted = False
        self._error_emitted = False
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
        macos_auth_ref = self._macos_auth_session.auth_ref if self._macos_auth_session is not None else None
        self._process = elevate.launch_elevated_worker(
            full_argv, stderr_log=self._log_path, macos_auth_ref=macos_auth_ref
        )
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
                # Bug corrigé, confirmé sur du vrai matériel : le worker élevé
                # avait bien émis un vrai événement "error" (ex.
                # GAMES_PARTITION_NOT_FOUND, une carte cible sans partition de
                # jeux -- refus légitime) dans le fichier de progression --
                # `emit_error` (protocol.py) y écrit toujours, `_dispatch`
                # ci-dessus l'avait donc déjà relayé via `self.error.emit(...)`
                # -- mais de nombreux chemins d'erreur de `__main__.py`
                # n'appellent jamais `emit_done(False)` après `emit_error`,
                # seulement `return 1`. Sans `_error_emitted`, cette branche ne
                # regardait que `_done_emitted` et écrasait systématiquement ce
                # vrai code d'erreur par un `ELEVATION_FAILED` générique dès
                # que le process élevé se terminait -- sur Windows en
                # particulier, `ShellExecuteW` ne fournit aucun tube
                # stdout/stderr (§3) : impossible de distinguer un worker qui a
                # échoué proprement d'une élévation refusée sans ce signal.
                if not self._error_emitted:
                    detail = self._read_elevation_log()
                    if _is_macos_tcc_blocked(detail):
                        self.error.emit(MACOS_TCC_BLOCKED, _MACOS_TCC_HINT)
                    elif _is_macos_tcc_protected_folder(detail):
                        self.error.emit(MACOS_TCC_PROTECTED_FOLDER, _MACOS_PROTECTED_FOLDER_HINT)
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
            self._error_emitted = True
            self.error.emit(event.get("code", ""), event.get("msg", ""))
        elif etype == "estimate":
            self.estimate.emit(event.get("size_bytes", 0))
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
