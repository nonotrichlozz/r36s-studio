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
partagé plutôt que par ce module."""

from __future__ import annotations

import ctypes
import platform
import shlex
import shutil
import subprocess
import sys
from ctypes import wintypes
from typing import List, Optional

# Ces déclarations ne font qu'annoncer la forme de la structure Win32 aux
# ctypes ; elles ne touchent aucune DLL et restent donc importables sur
# macOS/Linux (utile pour les tests).
SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
STILL_ACTIVE = 259
WAIT_INFINITE = 0xFFFFFFFF


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
    tube stdout au processus appelant à travers la frontière d'élévation,
    d'où le fichier de progression."""

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


def launch_elevated_worker(argv: List[str]) -> object:
    """Démarre `python -m r36s_studio <argv>` avec les privilèges admin et
    retourne un handle exposant au moins `.poll()` (un vrai
    `subprocess.Popen` sur macOS/Linux, un `WindowsElevatedProcess` sous
    Windows). `argv` doit déjà contenir `--worker`, `--progress-file` et
    `--cancel-file` — c'est `worker_runner.py` qui les construit."""
    command = [sys.executable, "-m", "r36s_studio", *argv]

    system = platform.system()
    if system == "Darwin":
        return _launch_macos(command)
    if system == "Linux":
        return _launch_linux(command)
    if system == "Windows":
        return _launch_windows(command)
    raise NotImplementedError(f"OS non supporté pour l'élévation : {system}")


def _launch_macos(command: List[str]) -> subprocess.Popen:
    shell_command = " ".join(shlex.quote(part) for part in command)
    applescript = f'do shell script "{shell_command}" with administrator privileges'
    return subprocess.Popen(["osascript", "-e", applescript])


def _launch_linux(command: List[str]) -> subprocess.Popen:
    pkexec = shutil.which("pkexec")
    if pkexec:
        return subprocess.Popen([pkexec, *command])
    return subprocess.Popen(["sudo", *command])


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
