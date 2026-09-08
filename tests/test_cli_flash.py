"""Tests du CLI `flash` (__main__.py) : confirmation explicite obligatoire
(règle §2 n°6), résolution du périphérique via `safety`, gestion des
erreurs. `list_devices`, `_confirm_flash` et `flash_device` sont mockés —
aucun disque réel n'est touché, et aucun test ne lit sur stdin."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging.flash import FlashResult
from r36s_studio.imaging.image_source import SevenZipArchiveError, UnsupportedImageFormatError
from r36s_studio.imaging.winlock import VolumeInUseError


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


# --- capacité affichée (_capacity_go) ---------------------------------------
# Bug corrigé, signalé sur du vrai matériel : la capacité d'une carte était
# calculée en base 1000 (`/ 1_000_000_000`) alors que `gui/screens.py::
# _format_size` (octets copiés/archivés) utilise déjà la base 1024, tout
# comme l'Explorateur Windows -- deux conventions différentes dans la même
# app, en plus du désaccord avec Windows.


def test_capacity_go_uses_base_1024():
    assert cli._capacity_go(2 * 1024**3) == 2.0
    # Carte réelle "32 Go" -- 31,9 Go en base 1000 (l'ancien calcul), 29,7
    # Go en base 1024 (Explorateur Windows, valeur confirmée sur du vrai
    # matériel).
    assert round(cli._capacity_go(31_914_983_424), 1) == 29.7


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
    """Base 1024 (comme l'Explorateur Windows), pas 1000 -- bug corrigé,
    signalé sur du vrai matériel : ce même compte d'octets s'affichait
    « 31,9 Go » ici contre « 29,7 Go » dans l'Explorateur pour la même
    carte."""
    device = _make_device(size_bytes=31_914_983_424)
    device.display = "SanDisk Ultra 128 Go"
    cli._confirm_flash(device, prompt=lambda _msg: "OUI")

    out = capsys.readouterr().out
    assert "SanDisk Ultra 128 Go" in out
    assert "29.7 Go" in out
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


# --- format d'image invalide (§5, image_source.py) -------------------------
# `flash_device` valide le format avant même de toucher le périphérique
# (règle §2 n°6) -- ici mocké pour lever directement l'exception
# correspondante, comme il le ferait pour un vrai fichier .7z.


@patch("r36s_studio.__main__.flash_device", side_effect=SevenZipArchiveError("archive 7-Zip"))
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_seven_zip_archive_emits_dedicated_code(mock_list, mock_confirm, mock_flash, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    image = tmp_path / "ArkOS.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert '"code": "SEVEN_ZIP_ARCHIVE"' in out


@patch("r36s_studio.__main__.flash_device", side_effect=UnsupportedImageFormatError("format non supporté"))
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_unsupported_format_emits_dedicated_code(mock_list, mock_confirm, mock_flash, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    image = tmp_path / "sd.img.zip"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert '"code": "UNSUPPORTED_IMAGE_FORMAT"' in out


@patch(
    "r36s_studio.__main__.flash_device",
    side_effect=VolumeInUseError("impossible de verrouiller le volume -- probablement utilisé par un autre programme"),
)
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_volume_in_use_emits_dedicated_code_not_io_error(mock_list, mock_confirm, mock_flash, tmp_path, capsys):
    """Bug corrigé, confirmé sur du vrai matériel : `FSCTL_LOCK_VOLUME`
    refusé (ERROR_ACCESS_DENIED) par un autre programme (Explorateur,
    indexeur, antivirus) tombait auparavant dans le repli générique
    IO_ERROR (`except (OSError, ...)`, VolumeInUseError étant une sous-
    classe d'OSError) -- doit être intercepté avant, avec son propre code,
    puisque le message générique ("vérifie que la carte est branchée")
    est faux dans ce cas précis."""
    mock_list.return_value = [_make_device()]
    image = tmp_path / "ArkOS.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert '"code": "VOLUME_IN_USE"' in out
    assert '"code": "IO_ERROR"' not in out


# --- partition de jeux, décision automatique post-écriture (§4.3) ----------
# Plus de drapeau `--create-games-partition` (retiré, §1 : l'utilisateur ne
# peut pas savoir à l'avance si une image laissera de l'espace libre) --
# `create_and_format_games_partition_if_worthwhile` est appelée pour tout
# flash réussi, décide seule (taille réelle de la carte, seuil de 1 Go) et
# ne fait jamais échouer un flash déjà réussi pour ce motif. Mockée ici --
# couverte séparément dans `tests/test_imaging_games_partition.py`.


@patch(
    "r36s_studio.__main__.create_and_format_games_partition_if_worthwhile",
    return_value=None,
)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_logs_when_not_enough_free_space_for_games_partition(
    mock_list, mock_confirm, mock_flash, mock_create_games, tmp_path, capsys
):
    """`None` = pas assez d'espace libre (moins de 1 Go, ou aucun espace du
    tout) -- jamais un échec du flash déjà réussi et vérifié, mais jamais
    une décision silencieuse non plus (§4.4)."""
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_create_games.assert_called_once()
    out = capsys.readouterr().out
    assert "Pas assez d'espace libre" in out
    assert '"type": "done"' in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_creates_games_partition_automatically_when_worthwhile(
    mock_list, mock_confirm, mock_flash, mock_create_games, tmp_path, capsys
):
    from r36s_studio.imaging.games_partition import GamesPartitionResult

    device = _make_device()
    mock_list.return_value = [device]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    mock_create_games.return_value = GamesPartitionResult(start_bytes=100, size_bytes=200, is_gpt=False)
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_create_games.assert_called_once()
    out = capsys.readouterr().out
    assert "Espace de jeux recréé" in out
    assert '"type": "done"' in out
    assert '"ok": true' in out


@patch(
    "r36s_studio.__main__.create_and_format_games_partition_if_worthwhile",
    side_effect=OSError("mkfs.exfat introuvable"),
)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_games_partition_failure_is_best_effort_and_does_not_fail_the_flash(
    mock_list, mock_confirm, mock_flash, mock_create_games, tmp_path, capsys
):
    """Le flash lui-même a déjà réussi et a été vérifié -- un échec de ce
    bonus (formatage natif indisponible...) ne doit jamais renverser ce
    résultat, même principe déjà établi pour `--eject-after`."""
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
    assert "Espace de jeux non recréé" in out
    assert '"level": "warning"' in out
    assert '"type": "done"' in out
    assert '"ok": true' in out


# --- --eject-after (§4.6) ----------------------------------------------------
# Firmware Android : ses partitions sont illisibles pour Windows, qui propose
# de les formater dès qu'il les découvre -- éjecter tout de suite, dans le
# même worker déjà élevé, réduit la fenêtre pendant laquelle ça peut arriver.


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_without_flag_never_ejects(mock_list, mock_confirm, mock_flash, mock_eject, tmp_path):
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_eject.assert_not_called()


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_with_eject_after_ejects_on_success(mock_list, mock_confirm, mock_flash, mock_eject, tmp_path, capsys):
    device = _make_device()
    mock_list.return_value = [device]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(
        ["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--eject-after"]
    )
    code = args.func(args)

    assert code == 0
    mock_eject.assert_called_once_with(device.path)
    out = capsys.readouterr().out
    assert '"type": "done"' in out
    assert '"ok": true' in out


@patch(
    "r36s_studio.__main__.eject_device",
    side_effect=OSError("carte occupée"),
)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_eject_after_failure_does_not_fail_the_flash(
    mock_list, mock_confirm, mock_flash, mock_eject, tmp_path, capsys
):
    """Le flash lui-même a réussi -- un échec d'éjection best-effort ne
    doit jamais rendre l'opération globale en échec (§4.6)."""
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 100)

    args = _parse(
        ["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--eject-after"]
    )
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert "carte occupée" in out
