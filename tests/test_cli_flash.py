"""Tests du CLI `flash` (__main__.py) : confirmation explicite obligatoire
(règle §2 n°6), résolution du périphérique via `safety`, gestion des
erreurs. `list_devices`, `_confirm_flash` et `flash_device` sont mockés —
aucun disque réel n'est touché, et aucun test ne lit sur stdin."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging.flash import FlashResult


def _make_device(path="/dev/fake-disk-test-3", size_bytes=32_000_000_000) -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=size_bytes,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


# --- confirmation (_confirm_flash) -----------------------------------------


def test_confirm_flash_accepts_exact_uppercase_oui():
    device = _make_device()
    assert cli._confirm_flash(device, prompt=lambda _msg: "OUI") is True


def test_confirm_flash_rejects_anything_else():
    device = _make_device()
    assert cli._confirm_flash(device, prompt=lambda _msg: "oui") is False
    assert cli._confirm_flash(device, prompt=lambda _msg: "y") is False
    assert cli._confirm_flash(device, prompt=lambda _msg: "") is False


def test_confirm_flash_shows_model_and_size(capsys):
    device = _make_device(size_bytes=31_914_983_424)
    device.display = "SanDisk Ultra 128 Go"
    cli._confirm_flash(device, prompt=lambda _msg: "OUI")

    out = capsys.readouterr().out
    assert "SanDisk Ultra 128 Go" in out
    assert "31.9 Go" in out
    assert device.path in out


# --- cmd_flash : bout en bout, IO mockée -----------------------------------


def _parse(argv):
    return cli.build_parser().parse_args(argv)


@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=False)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_refuses_without_confirmation(mock_list, mock_confirm, mock_flash, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_flash.assert_not_called()
    out = capsys.readouterr().out
    assert "CONFIRMATION_REFUSED" in out


@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_rejects_device_not_in_safe_list(mock_list, mock_confirm, mock_flash, tmp_path, capsys):
    mock_list.return_value = [_make_device(path="/dev/fake-disk-test-9")]  # un autre chemin que --device
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_flash.assert_not_called()
    mock_confirm.assert_not_called()  # jamais de confirmation pour un périphérique refusé
    out = capsys.readouterr().out
    assert "DEVICE_NOT_ALLOWED" in out


@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_rejects_missing_image_file(mock_list, capsys):
    args = _parse(["flash", "--image", "/nonexistent/sd.img", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_list.assert_not_called()  # échoue avant même de regarder les périphériques
    out = capsys.readouterr().out
    assert "IMAGE_NOT_FOUND" in out


@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_success_emits_done_true(mock_list, mock_confirm, mock_flash, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert '"type": "done"' in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_verification_failure_returns_error(mock_list, mock_confirm, mock_flash, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="def", verified=False
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "VERIFY_FAILED" in out
