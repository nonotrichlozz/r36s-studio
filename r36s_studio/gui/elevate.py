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
exactement comme le fait la GUI elle-même au premier lancement.

**macOS, phase 7 : `osascript` abandonné comme méthode principale.**
Confirmé sur du vrai matériel (voir CLAUDE.md §3) : une fois l'app
empaquetée ajoutée à Accès complet au disque, un worker relancé
directement depuis CE binaire (`AuthorizationExecuteWithPrivileges`,
`MacosAuthorizedProcess` ci-dessous) hérite de cette autorisation et
accède à `/dev/rdiskN` sans blocage TCC -- contrairement à un worker
relancé via `osascript … with administrator privileges`, un processus
système sans rapport avec le bundle de l'app, qui n'hérite d'aucune
identité TCC propre. `osascript` reste le chemin utilisé en développement
(pas de bundle, donc rien à hériter) et un repli si l'API historique
`AuthorizationExecuteWithPrivileges` (non documentée depuis macOS 10.7)
venait à disparaître d'une future version de macOS."""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import platform
import shlex
import shutil
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Callable, List, Optional

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


def launch_elevated_worker(
    argv: List[str],
    stderr_log: Optional[Path] = None,
    macos_auth_ref: Optional[AuthorizationRef] = None,
) -> object:
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
    élevé s'arrête sans avoir émis le moindre événement `done`.

    `macos_auth_ref` (`MacosAuthorizationSession.auth_ref`) permet de
    réutiliser une même autorisation entre plusieurs workers élevés sur
    macOS -- ignoré sur les autres OS (pas d'équivalent léger de ce genre
    pour `pkexec`/`sudo`/UAC dans ce squelette) et sans effet sur macOS en
    développement (`osascript`, qui ne consomme aucune `AuthorizationRef`)."""
    command = _worker_command(argv)

    system = platform.system()
    if system == "Darwin":
        return _launch_macos(command, stderr_log, macos_auth_ref)
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


def _launch_macos(
    command: List[str], stderr_log: Optional[Path], auth_ref: Optional[AuthorizationRef] = None
) -> object:
    """En développement, `command[0]` est un interpréteur `python3` nu, sans
    bundle : rien à hériter, `osascript` reste la seule option. Une fois
    empaquetée (`sys.frozen`), `command[0]` est CE binaire -- un enfant
    direct de celui-ci (`MacosAuthorizedProcess`) hérite de l'autorisation
    Accès complet au disque accordée au bundle (confirmé sur du vrai
    matériel, CLAUDE.md §3), ce qu'un enfant d'`osascript` ne peut pas.
    `_macos_native_supported()` ne fait qu'une vérification statique (aucune
    invite) ; si elle échoue -- API disparue d'une future version de macOS --
    on retombe sur `osascript` plutôt que de risquer un appel qui bloquerait
    sur une invite avant d'échouer. `auth_ref`, quand fourni, n'a de sens que
    pour ce chemin natif -- `osascript` n'en tient de toute façon aucun
    compte."""
    if getattr(sys, "frozen", False) and _macos_native_supported():
        return MacosAuthorizedProcess(command, stderr_log, auth_ref=auth_ref)
    return _launch_macos_osascript(command, stderr_log)


def _launch_macos_osascript(command: List[str], stderr_log: Optional[Path]) -> subprocess.Popen:
    applescript = _build_applescript(command)
    stderr_file = _open_stderr_target(stderr_log)
    try:
        return subprocess.Popen(["osascript", "-e", applescript], stderr=stderr_file)
    finally:
        if stderr_file is not None:
            stderr_file.close()  # dupliqué dans l'enfant par Popen ; notre copie est inutile ensuite


_SECURITY_FRAMEWORK_PATH = "/System/Library/Frameworks/Security.framework/Security"
_AUTHORIZATION_FLAG_DEFAULTS = 0
AuthorizationRef = ctypes.c_void_p


def _macos_native_supported() -> bool:
    """Vérification statique, sans jamais déclencher d'invite mot de passe :
    `AuthorizationExecuteWithPrivileges` existe-t-elle encore dans
    Security.framework ? Non documentée par Apple depuis macOS 10.7 mais
    toujours présente au moment du test qui a validé cette approche
    (macOS 12, CLAUDE.md §3). Si elle disparaît un jour, cette vérification
    échoue proprement ici -- jamais au milieu d'un appel réel, qui
    bloquerait sur une invite avant de découvrir l'échec."""
    try:
        security = ctypes.CDLL(_SECURITY_FRAMEWORK_PATH)
        security.AuthorizationCreate
        security.AuthorizationExecuteWithPrivileges
        security.AuthorizationFree
    except (OSError, AttributeError):
        return False
    return True


def _comm_pipe_fd(comm_pipe: ctypes.c_void_p) -> int:
    """Récupère le descripteur de fichier du `FILE*` que retourne
    `AuthorizationExecuteWithPrivileges` -- isolé dans sa propre fonction
    pour rester substituable en test par un vrai descripteur (`os.pipe`)
    sans avoir à simuler un `FILE*` C."""
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    libc.fileno.restype = ctypes.c_int
    libc.fileno.argtypes = [ctypes.c_void_p]
    return libc.fileno(comm_pipe)


def _bind_security_functions(security) -> None:
    """Déclare les signatures ctypes utilisées par `_run_authorized`/
    `MacosAuthorizationSession` -- factorisé pour n'écrire ces
    déclarations qu'une fois, que l'appelant crée son propre
    `AuthorizationRef` ou en réutilise un existant."""
    security.AuthorizationCreate.restype = ctypes.c_int
    security.AuthorizationCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(AuthorizationRef),
    ]
    security.AuthorizationExecuteWithPrivileges.restype = ctypes.c_int
    security.AuthorizationExecuteWithPrivileges.argtypes = [
        AuthorizationRef,
        ctypes.c_char_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_char_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.AuthorizationFree.restype = ctypes.c_int
    security.AuthorizationFree.argtypes = [AuthorizationRef, ctypes.c_uint32]


class MacosAuthorizationSession:
    """Conserve une seule `AuthorizationRef` vivante pour toute une
    session plutôt que d'en créer une nouvelle par worker élevé --
    correctif d'un comportement observé en usage réel : le parcours
    guidé (§5 mode assisté) redemandait l'invite mot de passe à chaque
    étape nécessitant l'élévation, alors qu'une seule autorisation pour
    tout le parcours suffit. `MainWindow` en crée une seule, lors du
    premier besoin d'élévation (jamais avant, §5 : ne jamais demander une
    permission avant d'en avoir réellement besoin), et la réutilise pour
    tous les workers élevés suivants (`MacosAuthorizedProcess`, via
    `auth_ref`) jusqu'à la fermeture de l'application (`close()`).

    Lève `OSError` si `AuthorizationCreate` échoue à la construction --
    l'appelant retombe alors sur le comportement d'origine (une
    `AuthorizationRef` par worker, voir `_run_authorized`)."""

    def __init__(self) -> None:
        self._security = ctypes.CDLL(_SECURITY_FRAMEWORK_PATH)
        _bind_security_functions(self._security)
        self._auth_ref = AuthorizationRef()
        status = self._security.AuthorizationCreate(
            None, None, _AUTHORIZATION_FLAG_DEFAULTS, ctypes.byref(self._auth_ref)
        )
        if status != 0:
            raise OSError(f"AuthorizationCreate a échoué (OSStatus {status})")
        self._closed = False

    @property
    def auth_ref(self) -> AuthorizationRef:
        return self._auth_ref

    def close(self) -> None:
        """Idempotent -- appelable plusieurs fois (fermeture de
        l'application, filet de sécurité `__del__` ci-dessous) sans
        risque de libérer deux fois la même référence."""
        if self._closed:
            return
        self._security.AuthorizationFree(self._auth_ref, _AUTHORIZATION_FLAG_DEFAULTS)
        self._closed = True

    def __del__(self) -> None:
        # Filet de sécurité si `close()` n'a jamais été appelé
        # explicitement -- ne doit jamais lever depuis un destructeur.
        try:
            self.close()
        except Exception:
            pass


def _run_authorized(
    tool_path: str,
    args: List[str],
    on_output: Callable[[bytes], None],
    auth_ref: Optional[AuthorizationRef] = None,
) -> None:
    """Lance `tool_path` élevé via `AuthorizationExecuteWithPrivileges`
    (Security.framework), en repassant tout ce qu'écrit l'enfant sur sa
    sortie combinée à `on_output` au fur et à mesure. Bloque jusqu'à la fin
    de l'enfant (fermeture de son tube de sortie) -- à appeler depuis un
    thread, jamais depuis le thread d'interface (voir
    `MacosAuthorizedProcess`). Lève `OSError` si `AuthorizationCreate` ou
    `AuthorizationExecuteWithPrivileges` échoue (mot de passe refusé ou
    invite annulée, la plupart du temps).

    Si `auth_ref` est fourni (`MacosAuthorizationSession.auth_ref`,
    réutilisée entre plusieurs appels), aucune nouvelle référence n'est
    créée ni libérée ici -- c'est l'appelant qui possède son cycle de vie.
    Sans `auth_ref` (usage ponctuel, comportement d'origine), une
    référence est créée puis libérée localement, comme avant."""
    security = ctypes.CDLL(_SECURITY_FRAMEWORK_PATH)
    _bind_security_functions(security)

    owns_ref = auth_ref is None
    if owns_ref:
        auth_ref = AuthorizationRef()
        status = security.AuthorizationCreate(None, None, _AUTHORIZATION_FLAG_DEFAULTS, ctypes.byref(auth_ref))
        if status != 0:
            raise OSError(f"AuthorizationCreate a échoué (OSStatus {status})")

    try:
        c_args = (ctypes.c_char_p * (len(args) + 1))()
        for i, arg in enumerate(args):
            c_args[i] = arg.encode()
        c_args[len(args)] = None

        comm_pipe = ctypes.c_void_p()
        status = security.AuthorizationExecuteWithPrivileges(
            auth_ref,
            tool_path.encode(),
            _AUTHORIZATION_FLAG_DEFAULTS,
            c_args,
            ctypes.byref(comm_pipe),
        )
        if status != 0:
            raise OSError(
                f"AuthorizationExecuteWithPrivileges a échoué (OSStatus {status}) : "
                "invite mot de passe refusée ou annulée"
            )

        fd = _comm_pipe_fd(comm_pipe)
        with os.fdopen(fd, "rb", closefd=True) as f:
            for chunk in iter(lambda: f.read(65536), b""):
                on_output(chunk)
    finally:
        if owns_ref:
            security.AuthorizationFree(auth_ref, _AUTHORIZATION_FLAG_DEFAULTS)


class MacosAuthorizedProcess:
    """Worker élevé lancé directement depuis CE binaire (`command[0]` ==
    `sys.executable`, donc `R36S Studio.app/Contents/MacOS/R36S Studio` une
    fois empaqueté) via `AuthorizationExecuteWithPrivileges`, plutôt que via
    `osascript`. Confirmé sur du vrai matériel (CLAUDE.md §3) : un enfant
    direct du binaire signé du bundle hérite de son autorisation Accès
    complet au disque -- ce qu'un enfant d'`osascript` (processus système
    sans rapport avec le bundle) ne peut pas.

    `AuthorizationExecuteWithPrivileges` est synchrone et bloque tant que
    l'utilisateur n'a pas répondu à l'invite mot de passe -- lancé ici dans
    un thread pour ne jamais geler la boucle d'événements Qt (contrairement
    à `osascript` : `subprocess.Popen` y rend la main immédiatement, c'est
    le processus `osascript` séparé qui attend l'invite).

    Cette API historique n'expose aucun PID : `.poll()` détecte la fin du
    worker par la fermeture de son tube de sortie plutôt que par un vrai
    code de sortie -- suffisant ici, `worker_runner.py` ne teste jamais que
    None/non-None (voir sa docstring `force_kill`). `.kill()` est donc un
    no-op documenté, comme la limite déjà connue de `force_kill()` sur
    macOS/Linux : sans PID, rien à tuer côté worker élevé -- `cancel()`
    coopératif via le fichier d'annulation reste la seule voie d'arrêt
    fiable pour ce chemin."""

    def __init__(
        self,
        command: List[str],
        stderr_log: Optional[Path],
        auth_ref: Optional[AuthorizationRef] = None,
    ):
        self._stderr_log = stderr_log
        self._auth_ref = auth_ref
        self._exited = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(command,), daemon=True)
        self._thread.start()

    def _run(self, command: List[str]) -> None:
        try:
            _run_authorized(command[0], command[1:], self._on_output, auth_ref=self._auth_ref)
        except Exception as exc:
            self._on_output(f"{exc}\n".encode())
        finally:
            self._exited.set()

    def _on_output(self, chunk: bytes) -> None:
        if not chunk or self._stderr_log is None:
            return
        with open(self._stderr_log, "ab") as f:
            f.write(chunk)

    def poll(self) -> Optional[int]:
        return 0 if self._exited.is_set() else None

    def wait(self, timeout: Optional[float] = None) -> Optional[int]:
        self._thread.join(timeout)
        return self.poll()

    def kill(self) -> None:
        """No-op documenté : voir la docstring de la classe -- cette API ne
        donne accès à aucun PID pour le worker élevé qu'elle a lancé."""


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
