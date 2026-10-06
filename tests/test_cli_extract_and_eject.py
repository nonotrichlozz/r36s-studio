"""Tests des CLI `extract-boot`, `extract-easyroms` et `eject`
(__main__.py, workflow à deux cartes §4.4/§4.5). `list_devices`,
`extract_boot`/`extract_easyroms`/`eject_device` sont mockés — aucune carte
réelle n'est touchée."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from r36s_studio import __main__ as cli
from r36s_studio import protocol
from r36s_studio.devices import Device
from r36s_studio.imaging import OperationCancelled
from r36s_studio.partitions.copy import MountpointNotWritable
from r36s_studio.partitions.locate import PartitionNotFound, PartitionNotMounted


def teardown_function() -> None:
    # `eject --progress-file` (ci-dessous) reconfigure la destination
    # globale du protocole JSON Lines (`protocol.py::configure`) -- la
    # remettre à `None` évite qu'un test suivant, dans ce fichier ou un
    # autre, écrive sans le savoir dans un fichier déjà refermé (même
    # principe que `tests/test_cli_worker.py::teardown_function`).
    protocol.configure(None)


@pytest.fixture(autouse=True)
def _card_accepted_for_arkos_steps():
    """Le refus d'une carte non ArkOS (`arkos_step_refusal`) lirait les
    vraies partitions du chemin factice -- neutralisé ici, testé à part."""
    with patch("r36s_studio.__main__.arkos_step_refusal", return_value=None):
        yield


def _make_device(path="/dev/fake-disk-test-3") -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


def _parse(argv):
    return cli.build_parser().parse_args(argv)


# --- extract-boot ------------------------------------------------------


@patch("r36s_studio.__main__.extract_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_refuses_emuelec_card_with_a_clear_code_before_touching_it(mock_list, mock_extract, capsys):
    """Revérification côté worker (CLAUDE.md, vérifications avant
    élévation) : code dédié, jamais PARTITION_NOT_FOUND sur une carte saine
    d'un autre système."""
    from r36s_studio.detect import CardSystem

    mock_list.return_value = [_make_device()]

    with patch("r36s_studio.__main__.arkos_step_refusal", return_value=CardSystem.EMUELEC) as mock_refusal:
        args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
        code = args.func(args)

    assert code == 1
    mock_refusal.assert_called_once()
    assert mock_refusal.call_args.args[1] == "extract_boot"
    mock_extract.assert_not_called()
    out = capsys.readouterr().out
    assert "CARD_SYSTEM_INCOMPATIBLE" in out
    assert "PARTITION_NOT_FOUND" not in out


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_boot", return_value=42)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_success_emits_done_true_with_archive_path(
    mock_list, mock_extract, mock_new_path, tmp_path, capsys
):
    mock_list.return_value = [_make_device()]
    dest = tmp_path / "BOOT_2026-07-06_00-21"
    mock_new_path.return_value = dest

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[1] == str(dest)
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert "BOOT_2026-07-06_00-21" in out


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_passes_output_dir_to_new_archive_path(mock_list, mock_extract, mock_new_path, tmp_path):
    mock_list.return_value = [_make_device()]
    custom_dir = tmp_path / "custom"

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3", "--output-dir", str(custom_dir)])
    args.func(args)

    from pathlib import Path

    mock_new_path.assert_called_once_with("BOOT", base_dir=Path(custom_dir))


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_without_output_dir_passes_none_as_base_dir(mock_list, mock_extract, mock_new_path):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    args.func(args)

    mock_new_path.assert_called_once_with("BOOT", base_dir=None)


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_boot", side_effect=PartitionNotFound("BOOT", "/dev/fake-disk-test-3"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_reports_partition_not_found(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "PARTITION_NOT_FOUND" in capsys.readouterr().out


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_boot", side_effect=OperationCancelled(1024))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_reports_cancellation(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "CANCELLED" in out
    assert '"ok": false' in out


@patch("r36s_studio.__main__.extract_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_rejects_device_not_in_safe_list(mock_list, mock_extract, capsys):
    mock_list.return_value = [_make_device(path="/dev/fake-disk-test-9")]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_extract.assert_not_called()
    assert "DEVICE_NOT_ALLOWED" in capsys.readouterr().out


# --- extract-easyroms ----------------------------------------------------


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_easyroms", return_value=99)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_easyroms_success_emits_done_true(mock_list, mock_extract, mock_new_path, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    dest = tmp_path / "EASYROMS_2026-07-06_00-21"
    mock_new_path.return_value = dest

    args = _parse(["extract-easyroms", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_new_path.assert_called_once()
    assert mock_new_path.call_args.args[0] == "EASYROMS"
    out = capsys.readouterr().out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_easyroms", side_effect=MountpointNotWritable("dest", "boom"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_easyroms_reports_mountpoint_not_writable(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-easyroms", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "MOUNTPOINT_NOT_WRITABLE" in capsys.readouterr().out


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_easyroms", side_effect=PartitionNotMounted("EASYROMS", "/dev/fake-disk-test-3"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_easyroms_reports_partition_not_mounted(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-easyroms", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "PARTITION_NOT_MOUNTED" in capsys.readouterr().out


# --- eject -----------------------------------------------------------------


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_success_emits_safe_to_remove_confirmation(mock_list, mock_eject, capsys):
    device = _make_device()
    mock_list.return_value = [device]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_eject.assert_called_once_with(device.path)
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert "retirée en toute sécurité" in out


@patch("r36s_studio.__main__.eject_device", side_effect=NotImplementedError("pas sous Windows"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_unsupported_os_reports_error(mock_list, mock_eject, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "UNSUPPORTED_OS" in capsys.readouterr().out


@patch("r36s_studio.__main__.eject_device", side_effect=OSError("carte occupée"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_os_error_reports_dedicated_eject_failed_code(mock_list, mock_eject, capsys):
    """Bug corrigé : retombait auparavant sur le générique IO_ERROR
    (« vérifie que la carte est branchée »), faux dans ce cas précis --
    `EJECT_FAILED` (déjà utilisé côté GUI) invite plutôt à fermer les
    fichiers ouverts ou à retirer la carte manuellement."""
    mock_list.return_value = [_make_device()]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert '"code": "EJECT_FAILED"' in out
    assert "IO_ERROR" not in out


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_supports_worker_progress_file(mock_list, mock_eject, tmp_path):
    """Bug corrigé, confirmé sur du vrai matériel : l'éjection Windows exige
    l'élévation (`ERROR_ACCESS_DENIED` en s'exécutant dans le processus GUI
    à privilèges normaux) -- `eject` doit donc pouvoir tourner comme worker
    élevé, comme `backup`/`flash` (§3), en écrivant le protocole JSON Lines
    dans `--progress-file` plutôt que sur stdout."""
    device = _make_device()
    mock_list.return_value = [device]
    progress_file = tmp_path / "progress.jsonl"

    args = _parse(
        [
            "eject",
            "--device",
            "/dev/fake-disk-test-3",
            "--worker",
            "--progress-file",
            str(progress_file),
        ]
    )
    code = args.func(args)

    assert code == 0
    content = progress_file.read_text(encoding="utf-8")
    assert '"type": "done"' in content
    assert '"ok": true' in content


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_rejects_device_not_in_safe_list(mock_list, mock_eject, capsys):
    mock_list.return_value = [_make_device(path="/dev/fake-disk-test-9")]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_eject.assert_not_called()
    assert "DEVICE_NOT_ALLOWED" in capsys.readouterr().out
