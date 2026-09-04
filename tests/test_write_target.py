"""Tests du dispatch par OS de la préparation à l'écriture
(imaging/write_target.py). `subprocess` et le module `winlock` sont mockés —
aucun périphérique réel n'est démonté, verrouillé ni ouvert."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.imaging.write_target import _windows_all_volume_paths, prepared_write_target, reunmount_before_verify


def _make_device(path: str, mountpoints=None) -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=mountpoints or [],
    )


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Darwin")
def test_macos_unmounts_disk_and_yields_rdisk(mock_system, mock_run):
    device = _make_device("/dev/disk9903")

    with prepared_write_target(device) as path:
        assert path == "/dev/rdisk9903"

    mock_run.assert_called_once_with(
        ["diskutil", "unmountDisk", "/dev/disk9903"], check=True, capture_output=True
    )


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Darwin")
def test_macos_succeeds_when_diskutil_writes_success_message_to_stderr(mock_system, mock_run):
    """Reproduit le bug : `diskutil unmountDisk` écrit parfois son message
    de succès sur stderr avec un code de retour 0 -- ça reste un succès,
    jamais une erreur, quel que soit le flux où le texte atterrit."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["diskutil", "unmountDisk", "/dev/disk9903"],
        returncode=0,
        stdout=b"",
        stderr=b"Unmount of all volumes on disk9903 was successful\n",
    )
    device = _make_device("/dev/disk9903")

    with prepared_write_target(device) as path:
        assert path == "/dev/rdisk9903"  # aucune exception levée


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Linux")
def test_linux_unmounts_each_mountpoint_and_yields_device_path(mock_system, mock_run):
    device = _make_device("/dev/fake-disk-test-sdb", mountpoints=["/media/BOOT", "/media/EASYROMS"])

    with prepared_write_target(device) as path:
        assert path == "/dev/fake-disk-test-sdb"

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls == [["umount", "/media/BOOT"], ["umount", "/media/EASYROMS"]]


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Linux")
def test_linux_with_no_mountpoints_does_not_call_umount(mock_system, mock_run):
    device = _make_device("/dev/fake-disk-test-sdb", mountpoints=[])

    with prepared_write_target(device) as path:
        assert path == "/dev/fake-disk-test-sdb"

    mock_run.assert_not_called()


def _mock_powershell_volume_paths(mock_run, volume_paths):
    """`_windows_all_volume_paths` (write_target.py) appelle `subprocess.run`
    directement -- même mock que les tests macOS/Linux ci-dessus, une
    seule ligne de chemin GUID par volume sur stdout."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["powershell"], returncode=0, stdout="\n".join(volume_paths) + "\n", stderr=""
    )


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.winlock.refresh_disk_properties")
@patch("r36s_studio.imaging.winlock.unlock_volumes")
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes", return_value=[111])
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Windows")
def test_windows_locks_dismounts_then_unlocks_and_refreshes(
    mock_system, mock_lock, mock_unlock, mock_refresh, mock_run
):
    # `from . import winlock` se fait à l'intérieur de la fonction : on
    # patch les fonctions du vrai module winlock (comme test_winlock.py),
    # plutôt que de tenter de substituer le module entier -- une fois
    # importé, `r36s_studio.imaging.winlock` est mis en cache comme
    # attribut du package, ce qui rendrait un remplacement via
    # `sys.modules` peu fiable.
    _mock_powershell_volume_paths(mock_run, [r"\\?\Volume{guid-d}\\"])
    device = _make_device(r"\\.\PhysicalDrive9902", mountpoints=["D:\\"])

    with prepared_write_target(device) as path:
        assert path == r"\\.\PhysicalDrive9902"

    mock_lock.assert_called_once_with([r"\\?\Volume{guid-d}\\"])
    mock_unlock.assert_called_once_with([111])
    mock_refresh.assert_called_once_with(r"\\.\PhysicalDrive9902")


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.winlock.refresh_disk_properties")
@patch("r36s_studio.imaging.winlock.unlock_volumes")
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes", return_value=[111])
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Windows")
def test_windows_unlocks_even_if_write_raises(mock_system, mock_lock, mock_unlock, mock_refresh, mock_run):
    _mock_powershell_volume_paths(mock_run, [r"\\?\Volume{guid-d}\\"])
    device = _make_device(r"\\.\PhysicalDrive9902", mountpoints=["D:\\"])

    try:
        with prepared_write_target(device):
            raise RuntimeError("écriture simulée en échec")
    except RuntimeError:
        pass

    mock_unlock.assert_called_once_with([111])


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.winlock.refresh_disk_properties")
@patch("r36s_studio.imaging.winlock.unlock_volumes")
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes", return_value=[111, 222, 333])
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Windows")
def test_windows_locks_letterless_boot_partition_too(mock_system, mock_lock, mock_unlock, mock_refresh, mock_run):
    """Bug corrigé, confirmé sur du vrai matériel : sur une carte ArkOS
    complète (BOOT sans lettre, root ext4 sans lettre, EASYROMS lettrée),
    `device.mountpoints` (utilisé par le code précédent) ne contenait que
    la lettre d'EASYROMS -- BOOT restait monté pendant l'écriture brute,
    et Windows invalidait le handle `\\\\.\\PhysicalDriveN` en cours
    d'écriture (`[Errno 9] Bad file descriptor`) pour protéger ce volume
    encore monté. Toutes les partitions du disque (`Get-Partition`, pas
    `device.mountpoints`) doivent désormais être verrouillées, lettrées ou
    non."""
    boot_guid = r"\\?\Volume{boot-guid}\\"
    root_guid = r"\\?\Volume{root-guid}\\"
    easyroms_guid = r"\\?\Volume{easyroms-guid}\\"
    _mock_powershell_volume_paths(mock_run, [boot_guid, root_guid, easyroms_guid])
    # EASYROMS a une lettre côté `devices/windows.py` -- mais BOOT/root
    # (ext4) n'y figurent jamais (Device.mountpoints, lettres uniquement) :
    # exactement le scénario réel qui a provoqué le bug.
    device = _make_device(r"\\.\PhysicalDrive1", mountpoints=["E:\\"])

    with prepared_write_target(device):
        pass

    mock_lock.assert_called_once_with([boot_guid, root_guid, easyroms_guid])


# --- _windows_all_volume_paths (bug corrigé : verrouiller/démonter tous --
# les volumes du disque, pas seulement ceux avec une lettre de lecteur) ---


@patch("r36s_studio.imaging.write_target.subprocess.run")
def test_windows_all_volume_paths_queries_correct_disk_number_and_parses_output(mock_run):
    boot_guid = r"\\?\Volume{boot-guid}\\"
    easyroms_guid = r"\\?\Volume{easyroms-guid}\\"
    _mock_powershell_volume_paths(mock_run, [boot_guid, easyroms_guid])

    result = _windows_all_volume_paths(r"\\.\PhysicalDrive1")

    assert result == [boot_guid, easyroms_guid]
    command = mock_run.call_args.args[0]
    assert command[0] == "powershell"
    joined = " ".join(command)
    assert "-DiskNumber 1" in joined


@patch("r36s_studio.imaging.write_target.subprocess.run")
def test_windows_all_volume_paths_empty_disk_returns_empty_list(mock_run):
    _mock_powershell_volume_paths(mock_run, [])

    assert _windows_all_volume_paths(r"\\.\PhysicalDrive3") == []


def test_windows_all_volume_paths_rejects_unexpected_device_path():
    try:
        _windows_all_volume_paths("/dev/not-a-windows-path")
        assert False, "aurait dû lever ValueError"
    except ValueError:
        pass


@patch("r36s_studio.imaging.write_target.platform.system", return_value="Plan9")
def test_unsupported_os_raises(mock_system):
    device = _make_device("/dev/whatever")
    try:
        with prepared_write_target(device):
            pass
        assert False, "aurait dû lever NotImplementedError"
    except NotImplementedError:
        pass


# --- reunmount_before_verify : bug corrigé (vérification faussée par un ---
# remontage automatique macOS entre l'écriture et la relecture) -----------


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Darwin")
def test_reunmount_before_verify_unmounts_again_on_macos(mock_system, mock_run):
    device = _make_device("/dev/disk9903")

    reunmount_before_verify(device)

    mock_run.assert_called_once_with(
        ["diskutil", "unmountDisk", "/dev/disk9903"], check=False, capture_output=True
    )


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Darwin")
def test_reunmount_before_verify_does_not_raise_when_nothing_to_unmount(mock_system, mock_run):
    """`check=False` : contrairement à l'unmount initial (où un échec
    signale un vrai problème), rien à démonter ici -- le remontage
    automatique n'a peut-être pas encore eu lieu -- est un résultat normal,
    pas une erreur."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["diskutil", "unmountDisk", "/dev/disk9903"],
        returncode=1,
        stdout=b"",
        stderr=b"No such disk could be unmounted\n",
    )
    device = _make_device("/dev/disk9903")

    reunmount_before_verify(device)  # ne doit lever aucune exception


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Linux")
def test_reunmount_before_verify_is_a_noop_outside_macos(mock_system, mock_run):
    device = _make_device("/dev/fake-disk-test-sdb")

    reunmount_before_verify(device)

    mock_run.assert_not_called()
