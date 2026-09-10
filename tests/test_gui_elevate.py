"""Tests du dispatch par OS de l'élévation (gui/elevate.py). `subprocess`
et les appels `ctypes.WinDLL` sont mockés — aucune élévation réelle n'est
demandée à l'utilisateur, sur aucun OS.

Couvre aussi le bug corrigé : `osascript: No module named r36s_studio`,
causé par `-m r36s_studio` dépendant du répertoire de travail dans lequel
`osascript`/`pkexec`/`sudo` lancent la commande (pas forcément celui du
projet)."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from r36s_studio.gui import elevate


# --- _worker_command : indépendance du répertoire de travail ---------------


def test_worker_command_uses_absolute_interpreter_path():
    command = elevate._worker_command(["list"])
    assert os.path.isabs(command[0])
    assert command[0] == sys.executable


def test_worker_command_embeds_absolute_project_root_in_dev_mode():
    command = elevate._worker_command(["list"])
    assert command[1] == "-c"
    bootstrap = command[2]
    root = str(elevate._project_root())
    assert os.path.isabs(root)
    assert repr(root) in bootstrap  # sys.path.insert(0, '<root absolu>')
    assert command[3:] == ["list"]


def test_worker_command_is_independent_of_current_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # aucun rapport avec le projet
    command = elevate._worker_command(["backup", "--device", "/dev/fake-disk-test-3"])
    root = str(elevate._project_root())
    assert repr(root) in command[2]
    assert root != str(tmp_path)


@pytest.mark.real_subprocess
@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "exécute pour de vrai `list_devices()` (aucun mock ici) -- sous "
        "Windows, l'énumération réelle passe par PowerShell et peut échouer "
        "pour des raisons de politique d'exécution/droits propres au runner "
        "CI, sans rapport avec ce que ce test vérifie réellement (la "
        "résolution du module depuis un répertoire de travail quelconque)."
    ),
)
def test_worker_command_actually_resolves_module_from_unrelated_cwd(tmp_path):
    """Reproduit le bug tel quel : execute la commande construite depuis un
    répertoire de travail qui ne contient pas le projet, en vrai
    sous-processus (pas de mock) — la régression `No module named
    r36s_studio` ne peut être qu'ici, à ce niveau. Sous-processus réel mais
    sans risque : lance uniquement `python3 -m r36s_studio list`, une
    commande strictement en lecture seule (§4.5 : la détection ne monte ni
    n'écrit jamais rien)."""
    command = elevate._worker_command(["list"])

    result = subprocess.run(command, cwd=str(tmp_path), capture_output=True, text=True, timeout=30)

    assert "No module named" not in result.stderr
    assert result.returncode == 0


def test_worker_command_when_frozen_skips_module_bootstrap(monkeypatch):
    """Une fois packagé PyInstaller, `sys.executable` EST le binaire — pas
    un interpréteur `python3` générique sur lequel `-c`/`-m` a un sens."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    command = elevate._worker_command(["backup", "--device", "/dev/fake-disk-test-3", "--worker"])

    assert command == [sys.executable, "backup", "--device", "/dev/fake-disk-test-3", "--worker"]
    assert "-c" not in command
    assert "-m" not in command


# --- macOS -------------------------------------------------------------


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason=(
        "compare sys.executable (le vrai chemin de CE runner, jamais mocké) au "
        "script AppleScript échappé -- sur un chemin Windows (backslashes, lettre "
        "de lecteur), l'échappement de _build_applescript peut ne plus contenir la "
        "sous-chaîne brute non échappée, sans rapport avec le comportement macOS "
        "réellement testé ici."
    ),
)
@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_uses_osascript_with_administrator_privileges(mock_system, mock_popen):
    argv = ["backup", "--device", "/dev/fake-disk-test-3", "--worker", "--progress-file", "/tmp/p.jsonl"]

    elevate.launch_elevated_worker(argv)

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "osascript"
    assert call_args[1] == "-e"
    assert "with administrator privileges" in call_args[2]
    assert "do shell script" in call_args[2]
    # La commande complète (interpréteur, bootstrap, arguments) doit être
    # encodée dans le script, correctement échappée.
    assert "r36s_studio" in call_args[2]
    assert "--progress-file" in call_args[2]
    assert sys.executable in call_args[2]


@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_escapes_double_quotes_for_applescript(mock_system, mock_popen):
    """Un argument contenant un guillemet double (chemin de projet
    localisé avec apostrophe, ex. "Bureau de l'utilisateur" une fois passé
    par shlex.quote) ne doit jamais refermer prématurément la chaîne
    AppleScript `do shell script "..."`."""
    elevate.launch_elevated_worker(['--output', 'a"b.img'])

    applescript = mock_popen.call_args.args[0][2]
    # La partie entre "do shell script \"" et "\" with administrator..."
    # doit être exempte de guillemet double non échappé.
    quoted_region = applescript.split('do shell script "', 1)[1].rsplit(
        '" with administrator privileges', 1
    )[0]
    assert '\\"' in quoted_region  # le guillemet a bien été échappé
    # Aucun guillemet non précédé d'un antislash ne subsiste.
    assert re.search(r'(?<!\\)"', quoted_region) is None


@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_without_stderr_log_does_not_redirect(mock_system, mock_popen):
    elevate.launch_elevated_worker(["backup"])
    assert mock_popen.call_args.kwargs.get("stderr") is None


@patch("r36s_studio.gui.elevate.open", new_callable=mock_open)
@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_stderr_log_is_opened_and_passed_to_popen(mock_system, mock_popen, mock_file_open):
    log_path = Path("/tmp/r36s_studio_elevation.log")

    elevate.launch_elevated_worker(["backup"], stderr_log=log_path)

    mock_file_open.assert_called_once_with(log_path, "wb")
    assert mock_popen.call_args.kwargs["stderr"] is mock_file_open.return_value
    mock_file_open.return_value.close.assert_called_once()  # copie du parent refermée


# --- macOS empaquetée : AuthorizationExecuteWithPrivileges, pas osascript ---
#
# Confirmé sur du vrai matériel (CLAUDE.md §3) : une fois l'app empaquetée
# autorisée en Accès complet au disque, un enfant direct du binaire du
# bundle (lancé via AuthorizationExecuteWithPrivileges) hérite de cette
# autorisation, contrairement à un enfant d'osascript. `sys.frozen` bascule
# donc `_launch_macos` sur `MacosAuthorizedProcess` plutôt qu'osascript.


@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_frozen_and_native_supported_skips_osascript(mock_system, mock_supported, mock_popen, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    process = elevate.launch_elevated_worker(["backup"])

    assert isinstance(process, elevate.MacosAuthorizedProcess)
    mock_popen.assert_not_called()
    process._thread.join(timeout=5)  # laisse le thread d'arrière-plan se terminer avant la fin du test


@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=False)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_frozen_but_native_unsupported_falls_back_to_osascript(mock_system, mock_supported, mock_popen, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    elevate.launch_elevated_worker(["backup"])

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "osascript"


@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_dev_mode_never_uses_direct_launch(mock_system, mock_supported, mock_popen, monkeypatch):
    """En développement (`sys.frozen` absent), `command[0]` est un
    interpréteur `python3` nu sans identité de bundle -- rien à hériter, la
    branche `MacosAuthorizedProcess` ne doit jamais être prise même si
    l'API est disponible."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    elevate.launch_elevated_worker(["backup"])

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "osascript"


def test_macos_native_supported_true_when_symbols_resolve():
    with patch("r36s_studio.gui.elevate.ctypes.CDLL", return_value=MagicMock()):
        assert elevate._macos_native_supported() is True


def test_macos_native_supported_false_when_framework_missing():
    with patch("r36s_studio.gui.elevate.ctypes.CDLL", side_effect=OSError("introuvable")):
        assert elevate._macos_native_supported() is False


def _fake_security_cdll(*, create_status=0, execute_status=0, comm_pipe_value=1):
    """Mock de `ctypes.CDLL(Security.framework)` : `AuthorizationCreate` et
    `AuthorizationExecuteWithPrivileges` renvoient les OSStatus donnés ;
    `comm_pipe` (le `ctypes.byref(...)` reçu) est rempli avec
    `comm_pipe_value`, une valeur arbitraire non nulle -- seul son
    identité de pointeur compte, `_comm_pipe_fd` (mocké séparément dans ces
    tests) est ce qui en extrait un vrai descripteur."""
    security = MagicMock()

    def _create(rights, environment, flags, auth_ref_ptr):
        auth_ref_ptr._obj.value = 99  # AuthorizationRef factice non nul
        return create_status

    def _execute(auth_ref, tool_path, flags, args, comm_pipe_ptr):
        comm_pipe_ptr._obj.value = comm_pipe_value
        return execute_status

    security.AuthorizationCreate.side_effect = _create
    security.AuthorizationExecuteWithPrivileges.side_effect = _execute
    return security


# --- MacosAuthorizationSession : une seule AuthorizationRef pour toute --
# --- une session, réutilisée entre workers élevés (§5 mode assisté) -----


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_authorization_session_creates_ref_once(mock_cdll):
    security = _fake_security_cdll()
    mock_cdll.return_value = security

    session = elevate.MacosAuthorizationSession()

    security.AuthorizationCreate.assert_called_once()
    assert session.auth_ref.value == 99


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_authorization_session_close_frees_the_ref(mock_cdll):
    security = _fake_security_cdll()
    mock_cdll.return_value = security
    session = elevate.MacosAuthorizationSession()

    session.close()

    security.AuthorizationFree.assert_called_once()


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_authorization_session_close_is_idempotent(mock_cdll):
    """Appelable plusieurs fois (fermeture de l'application, filet de
    sécurité `__del__`) sans libérer deux fois la même référence."""
    security = _fake_security_cdll()
    mock_cdll.return_value = security
    session = elevate.MacosAuthorizationSession()

    session.close()
    session.close()

    security.AuthorizationFree.assert_called_once()


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_authorization_session_raises_on_create_failure(mock_cdll):
    mock_cdll.return_value = _fake_security_cdll(create_status=-60001)

    with pytest.raises(OSError):
        elevate.MacosAuthorizationSession()


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_run_authorized_reuses_provided_auth_ref_without_creating_or_freeing_one(mock_cdll):
    """Cœur du correctif : avec un `auth_ref` fourni (session partagée),
    `_run_authorized` ne doit ni créer ni libérer sa propre référence --
    c'est justement la création répétée qui forçait l'invite mot de passe
    à chaque étape élevée du parcours guidé."""
    security = _fake_security_cdll()
    mock_cdll.return_value = security
    shared_ref = elevate.AuthorizationRef(42)
    read_fd, write_fd = os.pipe()
    os.close(write_fd)

    with patch("r36s_studio.gui.elevate._comm_pipe_fd", return_value=read_fd):
        elevate._run_authorized("/path/to/tool", ["--worker"], lambda chunk: None, auth_ref=shared_ref)

    security.AuthorizationCreate.assert_not_called()
    security.AuthorizationFree.assert_not_called()
    # La référence partagée est bien celle transmise à ExecuteWithPrivileges.
    execute_call = security.AuthorizationExecuteWithPrivileges.call_args
    assert execute_call.args[0] == shared_ref


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_run_authorized_without_auth_ref_still_creates_and_frees_its_own(mock_cdll):
    """Comportement d'origine préservé pour un usage ponctuel (aucune
    session partagée fournie) : toujours une référence créée puis
    libérée localement."""
    security = _fake_security_cdll()
    mock_cdll.return_value = security
    read_fd, write_fd = os.pipe()
    os.close(write_fd)

    with patch("r36s_studio.gui.elevate._comm_pipe_fd", return_value=read_fd):
        elevate._run_authorized("/path/to/tool", ["--worker"], lambda chunk: None)

    security.AuthorizationCreate.assert_called_once()
    security.AuthorizationFree.assert_called_once()


def test_macos_authorized_process_passes_auth_ref_through():
    shared_ref = elevate.AuthorizationRef(42)
    with patch("r36s_studio.gui.elevate._run_authorized") as mock_run:
        process = elevate.MacosAuthorizedProcess(["/path/to/tool"], stderr_log=None, auth_ref=shared_ref)
        process.wait(timeout=5)

    mock_run.assert_called_once()
    assert mock_run.call_args.kwargs["auth_ref"] == shared_ref


@patch("r36s_studio.gui.elevate.MacosAuthorizedProcess")
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_launch_macos_forwards_auth_ref_to_authorized_process(
    mock_system, mock_supported, mock_process_class, monkeypatch
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    shared_ref = elevate.AuthorizationRef(42)

    elevate.launch_elevated_worker(["backup"], macos_auth_ref=shared_ref)

    mock_process_class.assert_called_once()
    assert mock_process_class.call_args.kwargs["auth_ref"] == shared_ref


@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_launch_macos_osascript_path_ignores_auth_ref(mock_system, mock_popen, monkeypatch):
    """`osascript` (développement, ou repli si l'API native disparaît) ne
    consomme aucune `AuthorizationRef` -- passer `macos_auth_ref` ne doit
    ni lever ni changer le chemin emprunté."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    elevate.launch_elevated_worker(["backup"], macos_auth_ref=elevate.AuthorizationRef(42))

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "osascript"


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_run_authorized_streams_child_output_via_real_pipe(mock_cdll):
    mock_cdll.return_value = _fake_security_cdll()
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"hello from child\n")
    os.close(write_fd)  # simule la fin de l'enfant (EOF sur le tube)

    with patch("r36s_studio.gui.elevate._comm_pipe_fd", return_value=read_fd):
        chunks = []
        elevate._run_authorized("/path/to/tool", ["--worker"], chunks.append)

    assert b"".join(chunks) == b"hello from child\n"


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_run_authorized_raises_on_create_failure(mock_cdll):
    mock_cdll.return_value = _fake_security_cdll(create_status=-60001)

    with pytest.raises(OSError):
        elevate._run_authorized("/path/to/tool", [], lambda chunk: None)


@patch("r36s_studio.gui.elevate.ctypes.CDLL")
def test_run_authorized_raises_when_user_cancels_prompt(mock_cdll):
    """OSStatus -60006 (`errAuthorizationCanceled`) : l'utilisateur a annulé
    l'invite mot de passe. `AuthorizationFree` doit quand même être appelé
    (pas de fuite de l'`AuthorizationRef`)."""
    security = _fake_security_cdll(execute_status=-60006)
    mock_cdll.return_value = security

    with pytest.raises(OSError):
        elevate._run_authorized("/path/to/tool", [], lambda chunk: None)

    security.AuthorizationFree.assert_called_once()


def test_macos_authorized_process_poll_transitions_to_exited():
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"output\n")
    os.close(write_fd)

    with patch("r36s_studio.gui.elevate.ctypes.CDLL", return_value=_fake_security_cdll()), patch(
        "r36s_studio.gui.elevate._comm_pipe_fd", return_value=read_fd
    ):
        process = elevate.MacosAuthorizedProcess(["/path/to/tool", "--worker"], stderr_log=None)
        assert process.wait(timeout=5) is not None
        assert process.poll() is not None


def test_macos_authorized_process_writes_child_output_to_stderr_log(tmp_path):
    log_path = tmp_path / "elevation.log"
    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"[IO_ERROR] Operation not permitted: /dev/rdisk9903\n")
    os.close(write_fd)

    with patch("r36s_studio.gui.elevate.ctypes.CDLL", return_value=_fake_security_cdll()), patch(
        "r36s_studio.gui.elevate._comm_pipe_fd", return_value=read_fd
    ):
        process = elevate.MacosAuthorizedProcess(["/path/to/tool"], stderr_log=log_path)
        process.wait(timeout=5)

    assert "Operation not permitted" in log_path.read_text()


def test_macos_authorized_process_kill_is_a_documented_noop():
    """Aucun PID n'est exposé par cette API -- `.kill()` ne doit jamais
    lever, mais ne peut rien arrêter côté worker élevé (voir sa
    docstring)."""
    with patch("r36s_studio.gui.elevate.threading.Thread") as mock_thread:
        mock_thread.return_value.start.return_value = None
        process = elevate.MacosAuthorizedProcess(["/path/to/tool"], stderr_log=None)
    process.kill()  # ne doit pas lever


# --- Linux ---------------------------------------------------------------


@patch("r36s_studio.gui.elevate.shutil.which", return_value="/usr/bin/pkexec")
@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Linux")
def test_linux_uses_pkexec_when_available(mock_system, mock_popen, mock_which):
    argv = ["flash", "--image", "x.img", "--device", "/dev/fake-disk-test-sdb", "--worker"]

    elevate.launch_elevated_worker(argv)

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "/usr/bin/pkexec"
    assert call_args[1] == sys.executable
    assert call_args[2] == "-c"
    assert "r36s_studio" in call_args[3]
    assert call_args[4:] == ["flash", "--image", "x.img", "--device", "/dev/fake-disk-test-sdb", "--worker"]


@patch("r36s_studio.gui.elevate.shutil.which", return_value=None)
@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Linux")
def test_linux_falls_back_to_sudo_without_pkexec(mock_system, mock_popen, mock_which):
    elevate.launch_elevated_worker(["backup", "--device", "/dev/fake-disk-test-sdb"])

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "sudo"


@patch("r36s_studio.gui.elevate.open", new_callable=mock_open)
@patch("r36s_studio.gui.elevate.shutil.which", return_value="/usr/bin/pkexec")
@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Linux")
def test_linux_stderr_log_is_opened_and_passed_to_popen(mock_system, mock_popen, mock_which, mock_file_open):
    log_path = Path("/tmp/r36s_studio_elevation.log")

    elevate.launch_elevated_worker(["backup"], stderr_log=log_path)

    mock_file_open.assert_called_once_with(log_path, "wb")
    assert mock_popen.call_args.kwargs["stderr"] is mock_file_open.return_value


# --- propagation du code de retour : pas de maillon intermédiaire ---------


@pytest.mark.real_subprocess
@pytest.mark.skipif(
    sys.platform != "linux",
    reason="script shebang #!/bin/sh + bit exécutable réels -- Linux uniquement (absents sous Windows).",
)
def test_linux_exit_code_propagates_through_pkexec_unaltered(tmp_path):
    """`pkexec` (et `sudo`) doivent se contenter de relayer tel quel le
    code de sortie du worker — jamais un maillon intermédiaire qui le
    réécrirait ou l'avalerait. Vérifié ici en sous-processus réel (aucun
    mock de `subprocess.Popen`), avec un faux `pkexec` qui se contente
    d'`exec`er ce qu'on lui donne, comme le vrai pkexec le fait pour la
    commande qu'il élève."""
    fake_pkexec = tmp_path / "pkexec"
    fake_pkexec.write_text('#!/bin/sh\nexec "$@"\n')
    fake_pkexec.chmod(0o755)

    # Code de sortie distinctif : ni 0 (succès), ni 1 (le générique que
    # cmd_backup/cmd_flash renvoient sur erreur) -- pour être sûr qu'il ne
    # s'agit pas d'une coïncidence si le test passe.
    marker_command = [sys.executable, "-c", "import sys; sys.exit(42)"]

    with patch("r36s_studio.gui.elevate.shutil.which", return_value=str(fake_pkexec)), patch(
        "r36s_studio.gui.elevate.platform.system", return_value="Linux"
    ), patch("r36s_studio.gui.elevate._worker_command", return_value=marker_command):
        process = elevate.launch_elevated_worker(["backup"])

    process.wait(timeout=10)

    assert process.returncode == 42


@pytest.mark.real_subprocess
@pytest.mark.skipif(sys.platform != "darwin", reason="binaire `osascript` réel -- macOS uniquement.")
def test_macos_do_shell_script_reports_real_stderr_not_incidental_stdout(tmp_path):
    """Reproduit le bug tel quel via `osascript` réel (mais SANS `with
    administrator privileges` : aucun mot de passe demandé, `do shell
    script` a le même comportement de choix du texte d'erreur avec ou sans
    élévation).

    Simule le worker : imprime un message anodin de succès sur stdout
    (comme `diskutil unmountDisk`, non capturé avant le correctif),
    imprime la vraie erreur sur stderr (comme `protocol.emit_error` depuis
    le correctif), puis sort en échec. Le message d'erreur qu'AppleScript
    construit doit refléter la vraie erreur, jamais le message anodin."""
    fake_worker = tmp_path / "fake_worker.py"
    fake_worker.write_text(
        "import sys\n"
        "print('Unmount of all volumes on fake-disk-test-3 was successful')\n"
        "print('[IO_ERROR] Permission denied: /dev/rfake-disk-test-3', file=sys.stderr)\n"
        "sys.exit(1)\n"
    )
    command = [sys.executable, str(fake_worker)]
    applescript = elevate._build_applescript(command, with_admin_privileges=False)

    result = subprocess.run(
        ["osascript", "-e", applescript], capture_output=True, text=True, timeout=10
    )

    assert result.returncode != 0
    assert "Permission denied: /dev/rfake-disk-test-3" in result.stderr
    assert "was successful" not in result.stderr


# --- OS non supporté ---------------------------------------------------


@patch("r36s_studio.gui.elevate.platform.system", return_value="Plan9")
def test_unsupported_os_raises(mock_system):
    try:
        elevate.launch_elevated_worker(["backup"])
        assert False, "aurait dû lever NotImplementedError"
    except NotImplementedError:
        pass


# --- Windows : ShellExecuteExW mocké (aucune vraie élévation) --------------


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_uses_shell_execute_ex_with_runas(mock_system, mock_windll):
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hProcess = 4242
        return 1  # succès

    shell32.ShellExecuteExW.side_effect = _shell_execute
    mock_windll.return_value = shell32

    process = elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"])

    assert shell32.ShellExecuteExW.called
    assert isinstance(process, elevate.WindowsElevatedProcess)


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_forwards_parent_hwnd_to_shell_execute(mock_system, mock_windll):
    """Signalé : une invite UAC pourrait rester invisible en arrière-plan.
    `hwnd` (propriétaire de l'invite pour `ShellExecuteExW`, jamais renseigné
    jusqu'ici) doit porter le handle transmis par l'appelant
    (`gui/worker_runner.py::_windows_parent_hwnd`, le handle natif de
    `MainWindow`) plutôt que rester toujours `None`."""
    captured = {}
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        captured["hwnd"] = info.hwnd
        info.hProcess = 4242
        return 1

    shell32.ShellExecuteExW.side_effect = _shell_execute
    mock_windll.return_value = shell32

    elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"], parent_hwnd=123456)

    assert captured["hwnd"] == 123456


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_without_parent_hwnd_keeps_none(mock_system, mock_windll):
    """Comportement historique inchangé quand l'appelant ne fournit rien
    (ex. hors GUI, ou `winId()` indisponible) -- jamais un handle inventé."""
    captured = {}
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        captured["hwnd"] = info.hwnd
        info.hProcess = 4242
        return 1

    shell32.ShellExecuteExW.side_effect = _shell_execute
    mock_windll.return_value = shell32

    elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"])

    assert captured["hwnd"] is None


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_hides_the_worker_console_window(mock_system, mock_windll):
    """`ShellExecuteW` ne fournit aucun tube stdout/stderr vers le worker
    élevé (§3) -- toute la communication passe déjà par `--progress-file`,
    cette fenêtre de console est donc vide en pratique et contraire à §1
    (« aucune ligne de commande, jamais »). `nShow` doit valoir `SW_HIDE`,
    pas `SW_SHOWNORMAL`."""
    shell32 = MagicMock()
    captured = {}

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hProcess = 4242
        captured["nShow"] = info.nShow
        return 1

    shell32.ShellExecuteExW.side_effect = _shell_execute
    mock_windll.return_value = shell32

    elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"])

    assert captured["nShow"] == elevate.SW_HIDE


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_raises_when_shell_execute_fails(mock_system, mock_windll):
    shell32 = MagicMock()
    shell32.ShellExecuteExW.return_value = 0  # échec (annulé par l'utilisateur, etc.)
    mock_windll.return_value = shell32

    try:
        elevate.launch_elevated_worker(["backup"])
        assert False, "aurait dû lever OSError"
    except OSError:
        pass


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_success_logs_pid_to_stderr_log(mock_system, mock_windll, tmp_path):
    """Journalise gui/elevate.py : le PID obtenu (`GetProcessId`) et le
    handle retourné par `ShellExecuteExW` sur un lancement réussi --
    testable sans la GUI en appelant `launch_elevated_worker` directement
    (voir aussi le script autonome en fin de fichier)."""
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hProcess = 4242
        return 1  # succès

    shell32.ShellExecuteExW.side_effect = _shell_execute
    shell32.GetProcessId.return_value = 9001
    mock_windll.return_value = shell32
    log_path = tmp_path / "elevation.log"

    elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"], stderr_log=log_path)

    content = log_path.read_text(encoding="utf-8")
    assert "9001" in content
    assert "4242" in content


# --- Job Object : tuer tout l'arbre de processus, pas juste le worker -----
#
# Bug corrigé, constaté sur du vrai matériel : fermer la fenêtre pendant
# qu'un worker élevé tournait encore laissait ce worker orphelin, PID
# survivant, verrou de fichiers maintenu -- et pire, les sous-processus
# PowerShell qu'il lance lui-même (`winprocess.py`) survivaient eux aussi,
# `TerminateProcess` seul ne terminant jamais les enfants d'un processus.
# `_launch_windows` assigne désormais le worker à un Job Object
# (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`) dès son lancement -- ces tests
# distinguent le mock "shell32" (ShellExecuteExW) du mock "kernel32"
# (Job Object) via un `side_effect` sur `ctypes.WinDLL`, contrairement aux
# tests existants ci-dessus qui n'ont besoin que d'un seul mock partagé.


def _windll_side_effect(shell32_mock, kernel32_mock):
    def _factory(name, use_last_error=True):
        return shell32_mock if name == "shell32" else kernel32_mock

    return _factory


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_assigns_process_to_kill_on_close_job(mock_system, mock_windll):
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hProcess = 4242
        return 1

    shell32.ShellExecuteExW.side_effect = _shell_execute
    shell32.GetProcessId.return_value = 9001

    kernel32 = MagicMock()
    kernel32.CreateJobObjectW.return_value = 555
    kernel32.SetInformationJobObject.return_value = 1
    kernel32.AssignProcessToJobObject.return_value = 1

    mock_windll.side_effect = _windll_side_effect(shell32, kernel32)

    process = elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"])

    kernel32.CreateJobObjectW.assert_called_once()
    kernel32.SetInformationJobObject.assert_called_once()
    kernel32.AssignProcessToJobObject.assert_called_once_with(555, 4242)
    assert process._job_handle == 555


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_succeeds_even_if_job_object_creation_fails(mock_system, mock_windll):
    """Best-effort : la création du Job Object est une amélioration de
    nettoyage, jamais une condition de l'élévation elle-même -- un échec
    ici (rarissime) ne doit jamais empêcher le worker de démarrer."""
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hProcess = 4242
        return 1

    shell32.ShellExecuteExW.side_effect = _shell_execute
    shell32.GetProcessId.return_value = 9001

    kernel32 = MagicMock()
    kernel32.CreateJobObjectW.return_value = 0  # échec

    mock_windll.side_effect = _windll_side_effect(shell32, kernel32)

    process = elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"])

    assert isinstance(process, elevate.WindowsElevatedProcess)
    assert process._job_handle is None
    kernel32.AssignProcessToJobObject.assert_not_called()


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_succeeds_even_if_job_object_assignment_fails(mock_system, mock_windll):
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hProcess = 4242
        return 1

    shell32.ShellExecuteExW.side_effect = _shell_execute
    shell32.GetProcessId.return_value = 9001

    kernel32 = MagicMock()
    kernel32.CreateJobObjectW.return_value = 555
    kernel32.SetInformationJobObject.return_value = 1
    kernel32.AssignProcessToJobObject.return_value = 0  # échec

    mock_windll.side_effect = _windll_side_effect(shell32, kernel32)

    process = elevate.launch_elevated_worker(["backup", "--device", "/dev/whatever"])

    assert isinstance(process, elevate.WindowsElevatedProcess)
    assert process._job_handle is None
    kernel32.CloseHandle.assert_called_once_with(555)


def test_windows_elevated_process_kill_terminates_the_whole_job_when_available():
    with patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True) as mock_windll:
        kernel32 = MagicMock()
        mock_windll.return_value = kernel32
        process = elevate.WindowsElevatedProcess(h_process=4242, job_handle=555)

        process.kill()

        kernel32.TerminateJobObject.assert_called_once_with(555, 1)
        kernel32.TerminateProcess.assert_not_called()


def test_windows_elevated_process_kill_falls_back_to_terminate_process_without_job():
    """Le job n'a pas pu être créé (`job_handle=None`, best-effort) --
    retombe sur le comportement d'avant ce correctif plutôt que de ne rien
    tuer du tout."""
    with patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True) as mock_windll:
        kernel32 = MagicMock()
        mock_windll.return_value = kernel32
        process = elevate.WindowsElevatedProcess(h_process=4242, job_handle=None)

        process.kill()

        kernel32.TerminateProcess.assert_called_once_with(4242, 1)
        kernel32.TerminateJobObject.assert_not_called()


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_failure_logs_last_error_to_stderr_log(mock_system, mock_windll, tmp_path):
    """Journalise gui/elevate.py : `GetLastError` et `hInstApp` sur un
    échec de `ShellExecuteExW` -- le seul indice disponible côté GUI
    quand l'élévation échoue avant même que le worker élevé n'existe."""
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hInstApp = 5  # SE_ERR_ACCESSDENIED
        return 0  # échec

    shell32.ShellExecuteExW.side_effect = _shell_execute
    mock_windll.return_value = shell32
    log_path = tmp_path / "elevation.log"

    with patch("r36s_studio.gui.elevate.ctypes.get_last_error", create=True, return_value=1223):
        try:
            elevate.launch_elevated_worker(["backup"], stderr_log=log_path)
            assert False, "aurait dû lever OSError"
        except OSError as exc:
            assert "1223" in str(exc)

    content = log_path.read_text(encoding="utf-8")
    assert "1223" in content
    assert "5" in content  # hInstApp


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_shell_execute_failure_with_error_cancelled_raises_elevation_refused_error(
    mock_system, mock_windll
):
    """Bug corrigé, confirmé sur du vrai matériel : une invite UAC refusée
    (`GetLastError() == ERROR_CANCELLED`, 1223) se confondait avec
    n'importe quel autre échec de `ShellExecuteExW` une fois remontée à
    l'appelant -- affichée côté GUI avec le message pensé pour l'éjection
    en général (« ferme les fichiers ouverts... »), sans rapport avec un
    refus d'élévation. `ElevationRefusedError` (sous-classe d'`OSError`,
    rien ne casse côté code qui attrape `OSError` génériquement, ex. le
    test ci-dessus) permet à l'appelant de distinguer ce cas précis."""
    shell32 = MagicMock()
    shell32.ShellExecuteExW.return_value = 0
    mock_windll.return_value = shell32

    with patch("r36s_studio.gui.elevate.ctypes.get_last_error", create=True, return_value=1223):
        try:
            elevate.launch_elevated_worker(["backup"])
            assert False, "aurait dû lever ElevationRefusedError"
        except elevate.ElevationRefusedError:
            pass


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_shell_execute_failure_with_other_error_raises_plain_oserror(mock_system, mock_windll):
    """Symétrique du test ci-dessus : un échec `ShellExecuteExW` pour une
    tout autre cause (ex. `ERROR_FILE_NOT_FOUND`, 2 -- exécutable
    introuvable) ne doit jamais être confondu avec un refus d'élévation."""
    shell32 = MagicMock()
    shell32.ShellExecuteExW.return_value = 0
    mock_windll.return_value = shell32

    with patch("r36s_studio.gui.elevate.ctypes.get_last_error", create=True, return_value=2):
        try:
            elevate.launch_elevated_worker(["backup"])
            assert False, "aurait dû lever OSError"
        except elevate.ElevationRefusedError:
            assert False, "ne doit pas être ElevationRefusedError pour ce code"
        except OSError:
            pass


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Windows")
def test_windows_launch_truncates_stderr_log_at_start_of_each_attempt(mock_system, mock_windll, tmp_path):
    """`stderr_log` reflète toujours la dernière tentative, jamais un
    historique qui s'accumule (même principe que macOS/Linux, `elevate.py`
    docstring)."""
    shell32 = MagicMock()

    def _shell_execute(info_ref):
        info = info_ref._obj if hasattr(info_ref, "_obj") else info_ref
        info.hProcess = 1
        return 1

    shell32.ShellExecuteExW.side_effect = _shell_execute
    shell32.GetProcessId.return_value = 1
    mock_windll.return_value = shell32
    log_path = tmp_path / "elevation.log"
    log_path.write_text("contenu d'une tentative précédente, très longue" * 50, encoding="utf-8")

    elevate.launch_elevated_worker(["backup"], stderr_log=log_path)

    content = log_path.read_text(encoding="utf-8")
    assert "tentative précédente" not in content


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
def test_windows_elevated_process_poll_reports_still_active(mock_windll):
    kernel32 = MagicMock()

    def _get_exit_code(handle, ref):
        ref._obj.value = elevate.STILL_ACTIVE
        return 1  # BOOL Win32 : succès

    kernel32.GetExitCodeProcess.side_effect = _get_exit_code
    mock_windll.return_value = kernel32

    process = elevate.WindowsElevatedProcess(h_process=123)
    assert process.poll() is None


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
def test_windows_elevated_process_poll_reports_exit_code(mock_windll):
    kernel32 = MagicMock()

    def _get_exit_code(handle, ref):
        ref._obj.value = 0
        return 1  # BOOL Win32 : succès

    kernel32.GetExitCodeProcess.side_effect = _get_exit_code
    mock_windll.return_value = kernel32

    process = elevate.WindowsElevatedProcess(h_process=123)
    assert process.poll() == 0


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
def test_windows_elevated_process_poll_reports_exit_code_only_once(mock_windll):
    """`_log_exit_once` ne doit journaliser qu'un seul diagnostic même si
    `poll()` est rappelé après la fin du processus (`worker_runner.py`
    interroge toutes les 200 ms, §3 -- répéter noierait le journal)."""
    kernel32 = MagicMock()

    def _get_exit_code(handle, ref):
        ref._obj.value = 1
        return 1

    kernel32.GetExitCodeProcess.side_effect = _get_exit_code
    mock_windll.return_value = kernel32

    process = elevate.WindowsElevatedProcess(h_process=123)
    process.poll()
    process.poll()

    assert process._exit_logged is True


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
def test_windows_elevated_process_poll_getexitcodeprocess_failure_treated_as_exited(mock_windll):
    """Un `GetExitCodeProcess` qui échoue lui-même (jamais rencontré en
    pratique, handle invalide) ne doit jamais faire croire que le
    processus est encore actif -- `worker_runner.py` interprète déjà
    `poll() is not None` comme "terminé"."""
    kernel32 = MagicMock()
    kernel32.GetExitCodeProcess.return_value = 0  # BOOL Win32 : échec

    mock_windll.return_value = kernel32

    process = elevate.WindowsElevatedProcess(h_process=123)
    assert process.poll() is not None


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
def test_windows_elevated_process_logs_pid_and_elapsed_time_on_exit(mock_windll, tmp_path):
    kernel32 = MagicMock()

    def _get_exit_code(handle, ref):
        ref._obj.value = 3
        return 1

    kernel32.GetExitCodeProcess.side_effect = _get_exit_code
    mock_windll.return_value = kernel32
    log_path = tmp_path / "elevation.log"
    log_path.write_text("", encoding="utf-8")

    process = elevate.WindowsElevatedProcess(h_process=123, stderr_log=log_path, pid=4242)
    process.poll()

    content = log_path.read_text(encoding="utf-8")
    assert "4242" in content
    assert "3" in content  # code de sortie


# --- run_privileged_mount : montage forcé élevé (macOS, cartes GPT/EFI, ----
# --- §4.4) -- confirmé sur du vrai matériel nécessiter les droits ---------
# --- administrateur (`sudo mount -t msdos ...`), même chemin d'élévation --
# --- que launch_elevated_worker mais synchrone, sans protocole JSON -------
# --- Lines/fichier de progression. ------------------------------------------


@patch("r36s_studio.gui.elevate.os.path.ismount", return_value=True)
@patch("r36s_studio.gui.elevate.subprocess.run")
def test_run_privileged_mount_dev_mode_uses_osascript_with_admin_privileges(mock_run, mock_ismount):
    result = elevate.run_privileged_mount("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")

    call_args = mock_run.call_args.args[0]
    assert call_args[0] == "osascript"
    applescript = call_args[2]
    assert "with administrator privileges" in applescript
    assert "/sbin/mount" in applescript
    assert "-t msdos" in applescript
    assert "/dev/fake-disk-test-2s1" in applescript
    assert "/tmp/r36s-studio-test" in applescript
    assert result is True


@patch("r36s_studio.gui.elevate.os.path.ismount", return_value=False)
@patch("r36s_studio.gui.elevate.subprocess.run")
def test_run_privileged_mount_returns_false_when_nothing_actually_mounted(mock_run, mock_ismount):
    """Ni `osascript`/`do shell script` ni `AuthorizationExecuteWithPrivileges`
    ne remontent de façon fiable le code de sortie de la commande élevée
    elle-même -- le succès est vérifié après coup via `os.path.ismount`,
    jamais supposé du simple fait qu'aucune exception n'a été levée."""
    result = elevate.run_privileged_mount("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")

    assert result is False


@patch("r36s_studio.gui.elevate.os.path.ismount", return_value=True)
@patch("r36s_studio.gui.elevate._run_authorized")
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=True)
def test_run_privileged_mount_frozen_and_native_supported_skips_osascript(
    mock_supported, mock_run_authorized, mock_ismount, monkeypatch
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    result = elevate.run_privileged_mount("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")

    mock_run_authorized.assert_called_once()
    assert mock_run_authorized.call_args.args[0] == "/sbin/mount"
    assert mock_run_authorized.call_args.args[1] == [
        "-t",
        "msdos",
        "/dev/fake-disk-test-2s1",
        "/tmp/r36s-studio-test",
    ]
    assert result is True


@patch("r36s_studio.gui.elevate.os.path.ismount", return_value=True)
@patch("r36s_studio.gui.elevate._run_authorized")
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=True)
def test_run_privileged_mount_forwards_auth_ref_to_shared_session(
    mock_supported, mock_run_authorized, mock_ismount, monkeypatch
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    shared_ref = elevate.AuthorizationRef(42)

    elevate.run_privileged_mount("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test", auth_ref=shared_ref)

    assert mock_run_authorized.call_args.kwargs["auth_ref"] is shared_ref


@patch("r36s_studio.gui.elevate.os.path.ismount", return_value=False)
@patch("r36s_studio.gui.elevate._run_authorized", side_effect=OSError("invite refusée"))
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=True)
def test_run_privileged_mount_prompt_refused_returns_false_instead_of_raising(
    mock_supported, mock_run_authorized, mock_ismount, monkeypatch
):
    """Une invite refusée/annulée (mot de passe incorrect...) ne doit
    jamais faire planter l'appelant -- `_force_mount_macos` (locate.py)
    retombe sur son comportement non élevé, comme un hook non installé."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    result = elevate.run_privileged_mount("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")

    assert result is False


@patch("r36s_studio.gui.elevate.os.path.ismount", return_value=True)
@patch("r36s_studio.gui.elevate.subprocess.run")
@patch("r36s_studio.gui.elevate._macos_native_supported", return_value=False)
def test_run_privileged_mount_frozen_but_native_unsupported_falls_back_to_osascript(
    mock_supported, mock_run, mock_ismount, monkeypatch
):
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    elevate.run_privileged_mount("/dev/fake-disk-test-2s1", "/tmp/r36s-studio-test")

    call_args = mock_run.call_args.args[0]
    assert call_args[0] == "osascript"


@pytest.mark.real_fda_probe  # exercice l'implémentation réelle, pas le stub autouse (tests/conftest.py)
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.elevate.os.listdir", return_value=["TCC.db"])
def test_has_full_disk_access_true_when_tcc_directory_listable(mock_listdir, mock_system):
    """Le dossier protégé par TCC (§3) n'est listable que si ce processus a
    reçu l'autorisation Accès complet au disque -- une lecture réussie en
    est donc une preuve positive."""
    assert elevate.has_full_disk_access() is True
    mock_listdir.assert_called_once_with(elevate._TCC_PROBE_PATH)


@pytest.mark.real_fda_probe
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.elevate.os.listdir", side_effect=PermissionError())
def test_has_full_disk_access_false_when_tcc_directory_permission_denied(mock_listdir, mock_system):
    assert elevate.has_full_disk_access() is False


@pytest.mark.real_fda_probe
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.elevate.os.listdir", side_effect=FileNotFoundError())
def test_has_full_disk_access_false_when_tcc_directory_missing(mock_listdir, mock_system):
    """Absence du dossier (macOS très ancien, profil inhabituel...) : ne
    jamais affirmer l'autorisation sans preuve positive, §3."""
    assert elevate.has_full_disk_access() is False


@pytest.mark.real_fda_probe
@patch("r36s_studio.gui.elevate.os.listdir")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Linux")
def test_has_full_disk_access_true_on_non_macos_without_filesystem_check(mock_system, mock_listdir):
    """Ce blocage est spécifique à macOS (§3) -- sur les deux autres OS,
    toujours `True`, sans même tenter de lire le système de fichiers."""
    assert elevate.has_full_disk_access() is True
    mock_listdir.assert_not_called()
