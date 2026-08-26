"""Lance le worker (même binaire, argument `--worker`, §3) avec les
privilèges administrateur, par OS :

| OS      | Méthode                                                        |
|---------|-----------------------------------------------------------------|
| Windows | `ShellExecuteExW` verbe `runas` → invite UAC                    |
| macOS   | `osascript … with administrator privileges`                     |
| Linux   | `pkexec` (repli `sudo` si absent)                                |

Ce module ne s'occupe que de franchir la frontière de privilège ; c'est
`worker_runner.py` qui construit `argv` (avec `--worker`, `--progress-file`,
`--cancel-file`) et interprète le fichier de progression. Une fois la
frontière franchie, le processus appelant ne peut pas lire le stdout du
worker en flux sans mécanisme supplémentaire (tube nommé, RPC…) de façon
fiable sur les trois OS — c'est pourquoi le protocole passe par un fichier
partagé plutôt que par ce module.

**Répertoire de travail** — `osascript`/`pkexec`/`sudo` lancent la commande
depuis un répertoire qui n'a aucune raison de contenir le projet (bug
observé : `python3: No module named r36s_studio`, `-m r36s_studio`
dépendant du dossier courant). En développement, `_worker_command` insère
donc explicitement la racine du projet dans `sys.path` via un script `-c`
plutôt que de compter sur `-m` — indépendant du répertoire de travail sur
les trois OS, sans dépendre d'un `cd` (impossible à faire traverser
`pkexec`/`ShellExecuteExW`, qui n'exécutent pas via un shell) ni d'un
`PYTHONPATH` (filtré par certaines configurations `pkexec`/`sudo`).

**PyInstaller** — une fois packagée, l'appli est un binaire autonome :
`sys.executable` pointe alors vers CE binaire (`sys.frozen` vaut True), pas
vers un interpréteur `python3` générique. `-m r36s_studio` ni `-c` n'ont
alors de sens : le binaire est rappelé directement avec les arguments CLI,
exactement comme le fait la GUI elle-même au premier lancement."""

from __future__ import annotations

import ctypes
import platform
import shlex
import shutil
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import List, Optional

# Ces déclarations ne font qu'annoncer la forme de la structure Win32 aux
# ctypes ; elles ne touchent aucune DLL et restent donc importables sur
# macOS/Linux (utile pour les tests).
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
STILL_ACTIVE = 259
WAIT_INFINITE = 0xFFFFFFFF

_BOOTSTRAP = "import sys; sys.path.insert(0, {root!r}); from r36s_studio.__main__ import main; sys.exit(main(sys.argv[1:]))"


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", ctypes.c_ulong),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hKeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIcon", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


class WindowsElevatedProcess:
    """Enveloppe minimale autour du handle retourné par `ShellExecuteExW`
    (verbe `runas`), exposant juste ce dont `worker_runner.py` a besoin.
    Ce n'est pas un `subprocess.Popen` : `ShellExecuteW` ne fournit pas de
    tube stdout/stderr au processus appelant à travers la frontière
    d'élévation (contrairement à `osascript`/`pkexec`/`sudo`, lancés via
    `subprocess.Popen`) — le fichier de progression et le journal
    d'élévation (`logs.py`) ne sont donc pas alimentés sous Windows dans ce
    squelette ; une implémentation complète demanderait `CreateProcessW`
    avec des handles de tube explicites plutôt que `ShellExecuteExW`."""

    def __init__(self, h_process: int):
        self._h_process = h_process

    def poll(self) -> Optional[int]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        exit_code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(self._h_process, ctypes.byref(exit_code))
        if exit_code.value == STILL_ACTIVE:
            return None
        return exit_code.value

    def wait(self) -> Optional[int]:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject(self._h_process, WAIT_INFINITE)
        return self.poll()

    def kill(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        PROCESS_TERMINATE_EXIT_CODE = 1
        kernel32.TerminateProcess(self._h_process, PROCESS_TERMINATE_EXIT_CODE)


def _project_root() -> Path:
    """Dossier qui contient le paquet `r36s_studio` — jamais supposé être
    le répertoire de travail courant."""
    import r36s_studio

    return Path(r36s_studio.__file__).resolve().parent.parent


def _worker_command(argv: List[str]) -> List[str]:
    """Commande à exécuter, élevée, pour `argv` (déjà muni de `--worker`,
    `--progress-file`, `--cancel-file`). Chemins absolus uniquement :
    `sys.executable` l'est déjà (c'est un interpréteur ou un binaire, jamais
    résolu via `PATH`) ; en développement, la racine du projet insérée dans
    `sys.path` l'est aussi (`_project_root()` résout depuis `__file__`, pas
    depuis le répertoire de travail)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *argv]
    bootstrap = _BOOTSTRAP.format(root=str(_project_root()))
    return [sys.executable, "-c", bootstrap, *argv]


def launch_elevated_worker(argv: List[str], stderr_log: Optional[Path] = None) -> object:
    """Démarre le worker élevé pour `argv` et retourne un handle exposant
    au moins `.poll()` (un vrai `subprocess.Popen` sur macOS/Linux, un
    `WindowsElevatedProcess` sous Windows).

    Si `stderr_log` est fourni (macOS/Linux uniquement, voir
    `WindowsElevatedProcess`), la sortie d'erreur du lanceur d'élévation y
    est redirigée : sur macOS, `do shell script` transforme l'échec de la
    commande en erreur AppleScript dont le texte (repris de la commande)
    ressort sur le `stderr` d'`osascript` lui-même ; sur Linux, `pkexec`/
    `sudo` laissent passer directement le `stderr` du worker. Dans les deux
    cas, c'est ce fichier qui permet à `worker_runner.py` d'afficher
    l'erreur réelle plutôt qu'un message générique quand le processus
    élevé s'arrête sans avoir émis le moindre événement `done`."""
    command = _worker_command(argv)

    system = platform.system()
    if system == "Darwin":
        return _launch_macos(command, stderr_log)
    if system == "Linux":
        return _launch_linux(command, stderr_log)
    if system == "Windows":
        return _launch_windows(command)
    raise NotImplementedError(f"OS non supporté pour l'élévation : {system}")


def _open_stderr_target(stderr_log: Optional[Path]):
    if stderr_log is None:
        return None
    return open(stderr_log, "wb")


def _build_applescript(command: List[str], with_admin_privileges: bool = True) -> str:
    """Construit le script `do shell script "..."` pour `command`.
    `with_admin_privileges=False` sert uniquement aux tests : ça permet de
    vérifier le comportement réel d'`osascript`/`do shell script` (choix du
    texte d'erreur, propagation du code de sortie) sans déclencher de vraie
    invite mot de passe."""
    shell_command = " ".join(shlex.quote(part) for part in command)
    # `shell_command` est échappé pour le shell (via shlex.quote), pas pour
    # AppleScript : un argument contenant un guillemet double ou une
    # apostrophe (chemin de projet localisé, ex. "Bureau de l'utilisateur")
    # produirait un `"` littéral qui refermerait prématurément la chaîne
    # AppleScript ci-dessous si on ne l'échappait pas séparément ici.
    escaped = shell_command.replace("\\", "\\\\").replace('"', '\\"')
    suffix = " with administrator privileges" if with_admin_privileges else ""
    return f'do shell script "{escaped}"{suffix}'


def _launch_macos(command: List[str], stderr_log: Optional[Path]) -> subprocess.Popen:
    applescript = _build_applescript(command)
    stderr_file = _open_stderr_target(stderr_log)
    try:
        return subprocess.Popen(["osascript", "-e", applescript], stderr=stderr_file)
    finally:
        if stderr_file is not None:
            stderr_file.close()  # dupliqué dans l'enfant par Popen ; notre copie est inutile ensuite


def _launch_linux(command: List[str], stderr_log: Optional[Path]) -> subprocess.Popen:
    pkexec = shutil.which("pkexec")
    launcher = [pkexec] if pkexec else ["sudo"]
    stderr_file = _open_stderr_target(stderr_log)
    try:
        return subprocess.Popen([*launcher, *command], stderr=stderr_file)
    finally:
        if stderr_file is not None:
            stderr_file.close()


def _launch_windows(command: List[str]) -> WindowsElevatedProcess:
    exe, *rest = command
    params = subprocess.list2cmdline(rest)

    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = exe
    info.lpParameters = params
    info.lpDirectory = None
    info.nShow = SW_SHOWNORMAL

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ok = shell32.ShellExecuteExW(ctypes.byref(info))
    if not ok:
        raise OSError("ShellExecuteW (runas) a échoué : élévation refusée ou annulée")

    return WindowsElevatedProcess(info.hProcess)
