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


def _mark_as_studio_backup(image):
    """Sauvegarde faite par l'app : seule à recevoir un espace de jeux
    créé après le flash (`cmd_flash`, reconnue à son `.sha256blocks`)."""
    (image.parent / (image.name + ".sha256blocks")).write_text("")


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
    _mark_as_studio_backup(image)

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
    _mark_as_studio_backup(image)

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
    _mark_as_studio_backup(image)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert "Espace de jeux non recréé" in out
    assert '"level": "warning"' in out
    assert '"type": "done"' in out
    assert '"ok": true' in out


# --- carte SF3000 : jamais de partition de jeux séparée ----------------------
# Le système de la console ne lit que la première partition (`/mnt/sdcard`) :
# une EASYROMS y serait invisible. Détection sur la carte déjà écrite
# (`imaging/card_probe.py`), donc valable en mode expert comme dans le
# parcours guidé -- tous deux passent par `cmd_flash`.


@patch("r36s_studio.__main__.is_sf3000_card", return_value=True)
@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_sf3000_card_gets_no_separate_games_partition(
    mock_list, mock_confirm, mock_flash, mock_create_games, mock_probe, tmp_path, capsys
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "sf3000.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_probe.assert_called_once_with(device.path)
    mock_create_games.assert_not_called()
    out = capsys.readouterr().out
    assert "Carte de console SF3000 reconnue" in out
    assert "Espace de jeux recréé" not in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.is_sf3000_card", return_value=False)
@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile", return_value=None)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_other_cards_keep_the_automatic_games_partition(
    mock_list, mock_confirm, mock_flash, mock_create_games, mock_probe, tmp_path, capsys
):
    """Sauvegarde système (partition de jeux retirée) : espace de jeux créé."""
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "systeme.img"
    image.write_bytes(b"x" * 100)
    _mark_as_studio_backup(image)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    assert args.func(args) == 0

    mock_create_games.assert_called_once()
    assert "SF3000" not in capsys.readouterr().out


@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_downloaded_firmware_is_left_to_expand_whatever_its_partition_names(
    mock_list, mock_confirm, mock_flash, mock_create_games, tmp_path, capsys
):
    """Knulli sur RG40XXV (2026-10-17) : sa partition « SHARE » n'était pas
    reconnue, l'app a créé un espace de jeux derrière elle et bloqué son
    `autoresize`. Pas de `.sha256blocks` = pas une sauvegarde de l'app :
    rien n'est créé, quels que soient les noms des partitions."""
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "knulli-h700-rg40xx-v-scarab-20260511.img.gz"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    assert args.func(args) == 0

    mock_create_games.assert_not_called()
    out = capsys.readouterr().out
    assert "laissé libre" in out
    assert "post_flash_note" not in out


@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_firmware_with_an_unknown_games_label_gets_no_games_partition(
    mock_list, mock_confirm, mock_flash, mock_create_games, tmp_path, capsys
):
    """Firmware dont la partition de jeux porte un nom encore inconnu
    (« JEUX » ; muOS « ROMS » avant son ajout à `GAMES_LABELS`). Sondes
    réelles sur une carte factice (fichier) : l'étiquette n'est pas
    reconnue, mais l'image n'est pas une sauvegarde de l'app (pas de
    `.sha256blocks`) -- aucun espace de jeux créé derrière."""
    import struct

    from r36s_studio.imaging.card_probe import own_games_partition_bytes

    start_lba, sectors = 2048, 8
    card = bytearray((start_lba + sectors) * 512)
    card[446 + 4] = 0x83
    card[446 + 8 : 446 + 16] = struct.pack("<II", start_lba, sectors)
    card[510:512] = b"\x55\xaa"
    superblock = start_lba * 512 + 1024
    card[superblock + 56 : superblock + 58] = b"\x53\xef"
    card[superblock + 120 : superblock + 124] = b"JEUX"
    card_path = tmp_path / "carte-muos.bin"
    card_path.write_bytes(bytes(card))
    assert own_games_partition_bytes(str(card_path)) == 0  # étiquette inconnue

    mock_list.return_value = [_make_device(path=str(card_path))]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "muOS-RG40XXV.img.gz"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", str(card_path)])
    assert args.func(args) == 0

    mock_create_games.assert_not_called()
    assert "laissé libre" in capsys.readouterr().out


@patch("r36s_studio.__main__.is_darkosen_card", return_value=True)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_darkosen_card_sends_the_model_selection_note(
    mock_list, mock_confirm, mock_flash, mock_darkosen, tmp_path, capsys
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "darkosen.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    assert args.func(args) == 0

    mock_darkosen.assert_called_once_with(device.path)
    assert '{"type": "post_flash_note", "name": "darkosen_model_selection"}' in capsys.readouterr().out


@patch("r36s_studio.__main__._peek_free_games_partition_bytes", return_value=20 * 1024**3)
@patch("r36s_studio.__main__.own_games_partition_bytes", return_value=99 * 1024**2)
@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_firmware_with_its_own_games_partition_is_left_to_expand(
    mock_list, mock_confirm, mock_flash, mock_create_games, mock_probe, mock_free, tmp_path, capsys
):
    """dArkOSen (constaté deux fois) : une partition créée derrière EASYROMS
    l'empêchait de s'agrandir au premier démarrage."""
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "darkosen.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    assert args.func(args) == 0

    mock_create_games.assert_not_called()
    assert "agrandir sa partition de jeux toute seule" in capsys.readouterr().out


@patch("r36s_studio.__main__._peek_free_games_partition_bytes", return_value=96 * 1024**3)
@patch("r36s_studio.__main__.own_games_partition_bytes", return_value=29 * 1024**3)
@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_full_backup_on_a_bigger_card_warns_about_unused_space(
    mock_list, mock_confirm, mock_flash, mock_create_games, mock_probe, mock_free, tmp_path, capsys
):
    """Sauvegarde complète de 32 Go sur 128 Go : EASYROMS déjà agrandie une
    fois, la console ne le refera pas -- le dire, avec la marche à suivre."""
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "complete.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    assert args.func(args) == 0

    mock_create_games.assert_not_called()
    out = capsys.readouterr().out
    assert "96.0 Go restent inutilisés" in out
    assert "agrandir sa partition de jeux toute seule" not in out


@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_probes_the_real_card_content(
    mock_list, mock_confirm, mock_flash, mock_create_games, tmp_path, capsys
):
    """Sans mock de la détection : une « carte » (fichier) exFAT contenant
    cubegm/rkgame, telle que le flash l'a écrite, suffit à sauter la
    partition de jeux."""
    from tests.test_imaging_card_probe import _sf3000_exfat

    card = tmp_path / "carte.img"
    _sf3000_exfat(card)
    mock_list.return_value = [_make_device(path=str(card))]
    mock_flash.return_value = FlashResult(
        bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True
    )
    image = tmp_path / "sf3000.img"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", str(card)])
    assert args.func(args) == 0

    mock_create_games.assert_not_called()
    assert "Carte de console SF3000 reconnue" in capsys.readouterr().out


# --- carte ROCKNIX (§4.6) ------------------------------------------------------
# ROCKNIX agrandit lui-même sa partition de stockage au premier démarrage
# (`resizepart 2 100%`) : un espace de jeux créé derrière elle le bloque
# (« Can't have overlapping partitions », écran noir après le logo).


def _flash_ok(mock_list, mock_flash, tmp_path, device=None):
    mock_list.return_value = [device or _make_device()]
    mock_flash.return_value = FlashResult(bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True)
    image = tmp_path / "ROCKNIX-RK3326.aarch64-20261001-a.img.gz"
    image.write_bytes(b"x" * 100)
    return image


@patch("r36s_studio.__main__.is_rocknix_card", return_value=True)
@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_rocknix_card_gets_no_games_partition(
    mock_list, mock_confirm, mock_flash, mock_create_games, mock_probe, tmp_path, capsys
):
    image = _flash_ok(mock_list, mock_flash, tmp_path)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3"])
    assert args.func(args) == 0

    mock_create_games.assert_not_called()
    assert "Carte ROCKNIX" in capsys.readouterr().out


@patch("r36s_studio.__main__.unmount_forced")
@patch("r36s_studio.__main__.locate_mounted")
@patch("r36s_studio.__main__.is_rocknix_card", return_value=True)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_prepares_rocknix_for_r36s_before_eject(
    mock_list, mock_confirm, mock_flash, mock_probe, mock_locate, mock_unmount, tmp_path, capsys
):
    from r36s_studio.partitions import PartitionInfo

    image = _flash_ok(mock_list, mock_flash, tmp_path)
    root = tmp_path / "ROCKNIX"
    mock_locate.return_value = PartitionInfo(device_path="/dev/fake-disk-test-3s1", label="ROCKNIX", filesystem="fat32", mountpoint=str(root))
    order = []

    def prepare(partition_root, cache_dir, preferred):
        order.append(("prepare", partition_root, cache_dir, preferred))
        return preferred

    with patch("r36s_studio.__main__.prepare_r36s_card", side_effect=prepare), patch(
        "r36s_studio.__main__.eject_device", side_effect=lambda path: order.append(("eject", path))
    ):
        args = _parse(
            [
                "flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--eject-after",
                "--rocknix-r36s-panels", str(tmp_path / "panels"), "--rocknix-panel", "r36s-panel4",
            ]
        )
        assert args.func(args) == 0

    mock_locate.assert_called_once_with("/dev/fake-disk-test-3", "ROCKNIX")
    assert order == [
        ("prepare", str(root), str(tmp_path / "panels"), "r36s-panel4"),
        ("eject", "/dev/fake-disk-test-3"),
    ]
    out = capsys.readouterr().out
    assert "r36s-panel4" in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.locate_mounted", side_effect=OSError("partition introuvable"))
@patch("r36s_studio.__main__.is_rocknix_card", return_value=True)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_r36s_preparation_failure_warns_without_failing_the_flash(
    mock_list, mock_confirm, mock_flash, mock_probe, mock_locate, tmp_path, capsys
):
    image = _flash_ok(mock_list, mock_flash, tmp_path)

    args = _parse(
        ["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--rocknix-r36s-panels", str(tmp_path)]
    )
    assert args.func(args) == 0

    out = capsys.readouterr().out
    assert "Réglage R36S non fait" in out
    assert '"warning"' in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.locate_mounted")
@patch("r36s_studio.__main__.is_rocknix_card", return_value=False)
@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile", return_value=None)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_r36s_preparation_skipped_when_card_is_not_rocknix(
    mock_list, mock_confirm, mock_flash, mock_games, mock_probe, mock_locate, tmp_path, capsys
):
    image = _flash_ok(mock_list, mock_flash, tmp_path)

    args = _parse(
        ["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--rocknix-r36s-panels", str(tmp_path)]
    )
    assert args.func(args) == 0

    mock_locate.assert_not_called()
    assert "Réglage R36S non fait" in capsys.readouterr().out


# --- --eject-after (§4.6) ----------------------------------------------------
# Firmware Android : ses partitions sont illisibles pour Windows, qui propose
# de les formater dès qu'il les découvre -- éjecter tout de suite, dans le
# même worker déjà élevé, réduit la fenêtre pendant laquelle ça peut arriver.


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_without_flag_never_ejects(mock_list, mock_confirm, mock_flash, mock_eject, tmp_path, capsys):
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
    out = capsys.readouterr().out
    assert '"type": "eject_result"' not in out


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
    # Bug corrigé, confirmé sur du vrai matériel (§4.6) : sans cet
    # événement séparé, la GUI ne pouvait pas distinguer un succès d'un
    # échec silencieux de cette éjection chaînée -- elle masquait le
    # bouton Éjecter de fin d'opération dans tous les cas.
    assert '"type": "eject_result"' in out
    assert '"ok": true' in out.split('"type": "eject_result"')[-1]


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
    assert '"type": "eject_result"' in out
    assert '"ok": false' in out.split('"type": "eject_result"')[-1].split("\n")[0]


# --- --copy-after-flash (fiche du catalogue, ex. dtb.img ROCKNIX H700) ------

_DTB_RG40XXV = "device_trees/sun50i-h700-anbernic-rg40xx-v.dtb"


@patch("r36s_studio.__main__.unmount_forced")
@patch("r36s_studio.__main__.locate_mounted")
@patch("r36s_studio.__main__.is_rocknix_card", return_value=True)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_copies_dtb_after_flash_before_eject(
    mock_list, mock_confirm, mock_flash, mock_probe, mock_locate, mock_unmount, tmp_path, capsys
):
    from r36s_studio.partitions import PartitionInfo

    image = _flash_ok(mock_list, mock_flash, tmp_path)
    root = tmp_path / "ROCKNIX"
    (root / "device_trees").mkdir(parents=True)
    (root / _DTB_RG40XXV).write_bytes(b"dtb")
    partition = PartitionInfo(device_path="/dev/fake-disk-test-3s1", label="ROCKNIX", filesystem="fat32", mountpoint=str(root))
    mock_locate.return_value = partition
    order = []
    mock_unmount.side_effect = lambda p: order.append(("unmount", (root / "dtb.img").exists()))

    with patch("r36s_studio.__main__.eject_device", side_effect=lambda path: order.append(("eject", path))):
        args = _parse(
            [
                "flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--eject-after",
                "--copy-after-flash", "ROCKNIX", _DTB_RG40XXV, "dtb.img",
            ]
        )
        assert args.func(args) == 0

    mock_locate.assert_called_once_with("/dev/fake-disk-test-3", "ROCKNIX")
    assert (root / "dtb.img").read_bytes() == b"dtb"
    assert order == [("unmount", True), ("eject", "/dev/fake-disk-test-3")]
    out = capsys.readouterr().out
    assert "dtb.img posé sur ROCKNIX" in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.unmount_forced")
@patch("r36s_studio.__main__.locate_mounted")
@patch("r36s_studio.__main__.is_rocknix_card", return_value=True)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_copy_after_flash_missing_source_warns_without_failing(
    mock_list, mock_confirm, mock_flash, mock_probe, mock_locate, mock_unmount, tmp_path, capsys
):
    from r36s_studio.partitions import PartitionInfo

    image = _flash_ok(mock_list, mock_flash, tmp_path)
    root = tmp_path / "ROCKNIX"
    root.mkdir()
    mock_locate.return_value = PartitionInfo(device_path="/dev/fake-disk-test-3s1", label="ROCKNIX", filesystem="fat32", mountpoint=str(root))

    args = _parse(
        ["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--copy-after-flash", "ROCKNIX", _DTB_RG40XXV, "dtb.img"]
    )
    assert args.func(args) == 0

    out = capsys.readouterr().out
    assert "Réglage de la carte après installation non fait" in out
    assert '"ok": true' in out
    mock_unmount.assert_called_once()


@patch("r36s_studio.__main__.locate_mounted")
@patch("r36s_studio.__main__.is_rocknix_card", return_value=True)
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_copy_after_flash_refuses_unsafe_path_without_mounting(
    mock_list, mock_confirm, mock_flash, mock_probe, mock_locate, tmp_path, capsys
):
    image = _flash_ok(mock_list, mock_flash, tmp_path)

    args = _parse(
        ["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--copy-after-flash", "ROCKNIX", "../../x", "dtb.img"]
    )
    assert args.func(args) == 0

    mock_locate.assert_not_called()
    assert "Réglage de la carte après installation non fait" in capsys.readouterr().out


@patch("r36s_studio.__main__._peek_free_games_partition_bytes", return_value=60 * 1024**3)
@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile")
@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_flash_knulli_r36s_card_keeps_share_and_gets_no_easyroms(
    mock_list, mock_confirm, mock_flash, mock_create_games, mock_free, tmp_path, capsys
):
    """Disposition de `knulli-rk3326-r36s-scarab-20260510.img.gz` (MBR :
    FAT32 « KNULLI » puis ext4 « SHARE » de 512 Mio, réduites ici) : SHARE
    reconnue, aucun espace de jeux créé, aucun réglage ROCKNIX ni dArkOSen."""
    import struct

    from r36s_studio.imaging.card_probe import is_rocknix_card, own_games_partition_bytes

    fat_lba, fat_sectors, share_lba, share_sectors = 2048, 8, 4096, 8
    card = bytearray((share_lba + share_sectors) * 512)
    card[446 + 4] = 0x0C
    card[446 + 8 : 446 + 16] = struct.pack("<II", fat_lba, fat_sectors)
    card[462 + 4] = 0x83
    card[462 + 8 : 462 + 16] = struct.pack("<II", share_lba, share_sectors)
    card[510:512] = b"\x55\xaa"
    boot = fat_lba * 512
    card[boot + 71 : boot + 90] = b"KNULLI     FAT32   "
    superblock = share_lba * 512 + 1024
    card[superblock + 56 : superblock + 58] = b"\x53\xef"
    card[superblock + 120 : superblock + 125] = b"SHARE"
    card_path = tmp_path / "carte-knulli-r36s.bin"
    card_path.write_bytes(bytes(card))
    assert own_games_partition_bytes(str(card_path)) == share_sectors * 512
    assert is_rocknix_card(str(card_path)) is False

    mock_list.return_value = [_make_device(path=str(card_path))]
    mock_flash.return_value = FlashResult(bytes_written=100, source_sha256="abc", written_sha256="abc", verified=True)
    image = tmp_path / "knulli-rk3326-r36s-scarab-20260510.img.gz"
    image.write_bytes(b"x" * 100)

    args = _parse(["flash", "--image", str(image), "--device", str(card_path)])
    assert args.func(args) == 0

    mock_create_games.assert_not_called()
    out = capsys.readouterr().out
    assert "agrandir sa partition de jeux toute seule" in out
    assert "ROCKNIX" not in out and "post_flash_note" not in out
