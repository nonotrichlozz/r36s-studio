# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

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
from .strings import tr

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
    # Progression par étapes réelles (§2 n°5, §4.3 bis « Remettre la carte
    # à zéro ») -- distinct de `progress` ci-dessus (bytes/débit), pour une
    # opération qui n'a rien à copier mais dont chaque étape terminée est
    # un jalon réel.
    step_progress = Signal(int, int, str)  # step_index, step_count, step_name
    # Résultat d'une éjection chaînée dans ce même worker (§5 mode assisté,
    # `backup --eject-after`) -- distinct de `error`/`finished` : la
    # sauvegarde elle-même peut réussir même si cette éjection échoue,
    # `_on_wizard_source_eject_result` (main_window.py) en a besoin
    # séparément pour décider d'enchaîner ou de retomber sur un worker
    # d'éjection dédié.
    eject_result = Signal(bool, str)  # ok, msg

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
            full_argv, stderr_log=self._log_path, macos_auth_ref=macos_auth_ref, parent_hwnd=self._windows_parent_hwnd()
        )
        self._timer.start()

    def _windows_parent_hwnd(self) -> Optional[int]:
        """Handle de fenêtre natif du parent (`MainWindow`, toujours passé
        en `parent=` à la construction, §3) -- transmis à `ShellExecuteExW`
        (`elevate.py::_launch_windows`) comme propriétaire de l'invite UAC.

        Signalé : une invite UAC pourrait rester en arrière-plan (deux
        minutes avant l'échec observé, sans que l'utilisateur ne la voie
        apparaître). `ShellExecuteExW` reçoit `hwnd=None` depuis toujours --
        Microsoft documente ce paramètre comme le propriétaire de la
        fenêtre affichée, utilisé pour son rattachement au bon endroit
        (z-order, association dans la barre des tâches) même si l'invite de
        consentement s'affiche elle-même sur le Bureau sécurisé (un
        mécanisme Windows séparé, qui prend déjà la main sur tout l'écran
        indépendamment de ce paramètre -- donc *pas* la cause la plus
        probable d'une invite invisible ; un second écran sur lequel
        l'invite apparaîtrait hors du champ de vision de l'utilisateur est
        une explication au moins aussi plausible, non vérifiable sans du
        vrai matériel multi-écran). Passer ce handle est la pratique
        recommandée par Microsoft pour `ShellExecuteEx`, sans inconvénient
        connu -- amélioration raisonnable en l'absence d'une cause confirmée,
        pas un correctif garanti.

        `None` hors Windows (le paramètre est ignoré par `elevate.py` sur
        les autres OS) et si `winId()` échoue pour une raison quelconque
        (ex. widget pas encore affiché) -- `ShellExecuteExW` accepte déjà
        `hwnd=None` comme absence de propriétaire, comportement inchangé
        dans ce cas."""
        if platform.system() != "Windows":
            return None
        parent_widget = self.parent()
        if parent_widget is None:
            return None
        try:
            return int(parent_widget.winId())
        except Exception:
            return None

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
                        self.error.emit(MACOS_TCC_BLOCKED, tr("macos_tcc_hint"))
                    elif _is_macos_tcc_protected_folder(detail):
                        self.error.emit(MACOS_TCC_PROTECTED_FOLDER, tr("macos_protected_folder_hint"))
                    else:
                        msg = tr("cancelled_or_elevation_failed")
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
        elif etype == "step_progress":
            self.step_progress.emit(event.get("step_index", 0), event.get("step_count", 0), event.get("step_name", ""))
        elif etype == "eject_result":
            self.eject_result.emit(bool(event.get("ok")), event.get("msg", ""))
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
