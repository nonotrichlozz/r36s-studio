"""Tests du dispatch par OS de l'élévation (gui/elevate.py). `subprocess`
et les appels `ctypes.WinDLL` sont mockés — aucune élévation réelle n'est
demandée à l'utilisateur, sur aucun OS."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from r36s_studio.gui import elevate


@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Darwin")
def test_macos_uses_osascript_with_administrator_privileges(mock_system, mock_popen):
    argv = ["backup", "--device", "/dev/disk3", "--worker", "--progress-file", "/tmp/p.jsonl"]

    elevate.launch_elevated_worker(argv)

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "osascript"
    assert call_args[1] == "-e"
    assert "with administrator privileges" in call_args[2]
    assert "do shell script" in call_args[2]
    # La commande complète (python -m r36s_studio ...) doit être encodée
    # dans le script, correctement échappée.
    assert "r36s_studio" in call_args[2]
    assert "--progress-file" in call_args[2]


@patch("r36s_studio.gui.elevate.shutil.which", return_value="/usr/bin/pkexec")
@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Linux")
def test_linux_uses_pkexec_when_available(mock_system, mock_popen, mock_which):
    argv = ["flash", "--image", "x.img", "--device", "/dev/sdb", "--worker"]

    elevate.launch_elevated_worker(argv)

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "/usr/bin/pkexec"
    assert "r36s_studio" in call_args
    assert "flash" in call_args


@patch("r36s_studio.gui.elevate.shutil.which", return_value=None)
@patch("r36s_studio.gui.elevate.subprocess.Popen")
@patch("r36s_studio.gui.elevate.platform.system", return_value="Linux")
def test_linux_falls_back_to_sudo_without_pkexec(mock_system, mock_popen, mock_which):
    elevate.launch_elevated_worker(["backup", "--device", "/dev/sdb"])

    call_args = mock_popen.call_args.args[0]
    assert call_args[0] == "sudo"


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
def test_windows_elevated_process_poll_reports_still_active(mock_windll):
    kernel32 = MagicMock()

    def _get_exit_code(handle, ref):
        ref._obj.value = elevate.STILL_ACTIVE

    kernel32.GetExitCodeProcess.side_effect = _get_exit_code
    mock_windll.return_value = kernel32

    process = elevate.WindowsElevatedProcess(h_process=123)
    assert process.poll() is None


@patch("r36s_studio.gui.elevate.ctypes.WinDLL", create=True)
def test_windows_elevated_process_poll_reports_exit_code(mock_windll):
    kernel32 = MagicMock()

    def _get_exit_code(handle, ref):
        ref._obj.value = 0

    kernel32.GetExitCodeProcess.side_effect = _get_exit_code
    mock_windll.return_value = kernel32

    process = elevate.WindowsElevatedProcess(h_process=123)
    assert process.poll() == 0
