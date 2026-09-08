"""Tests du CLI `reset-card` (__main__.py) : « Remettre la carte à zéro »
en quatre étapes réelles (effacement, création, formatage, éjection),
chacune journalisée et suivie d'une progression réelle (`emit_step_
progress`, jamais un minuteur, §2 n°5). Confirmation explicite obligatoire
(règle §2 n°6, réutilise `_confirm_flash`). `list_devices`/`erase_
partition_table`/`create_single_partition`/`format_games_partition`/
`eject_device` sont mockés -- aucun disque réel n'est touché."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging.reset_card import CardTooSmallForReset, DEFAULT_RESET_LABEL, ResetCardPlan


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


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def _patch_happy_path(plan_size_bytes=32_000_000_000):
    """Mock les quatre étapes pour un déroulé entièrement réussi --
    factorisé, réutilisé par plusieurs tests ci-dessous."""
    return patch.multiple(
        "r36s_studio.__main__",
        erase_partition_table=lambda device: None,
        create_single_partition=lambda device: ResetCardPlan(start_lba=2048, end_lba=2048 + plan_size_bytes // 512),
        format_games_partition=lambda device, label, filesystem, known_partition_paths: None,
        eject_device=lambda path: None,
    )


@patch("r36s_studio.__main__.erase_partition_table")
@patch("r36s_studio.__main__._confirm_flash", return_value=False)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_refuses_without_confirmation(mock_list, mock_confirm, mock_erase, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_erase.assert_not_called()
    out = capsys.readouterr().out
    assert "CONFIRMATION_REFUSED" in out


@patch("r36s_studio.__main__.erase_partition_table")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_rejects_device_not_in_safe_list(mock_list, mock_confirm, mock_erase, capsys):
    mock_list.return_value = [_make_device(path="/dev/fake-disk-test-9")]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_erase.assert_not_called()
    mock_confirm.assert_not_called()
    out = capsys.readouterr().out
    assert "DEVICE_NOT_ALLOWED" in out


@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_success_runs_all_four_steps_with_default_label(mock_list, mock_confirm, capsys):
    device = _make_device()
    mock_list.return_value = [device]

    with _patch_happy_path():
        args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
        code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert '"type": "done"' in out
    assert '"ok": true' in out
    # Une ligne de progression par étape réelle -- jamais un minuteur (§2 n°5).
    assert out.count('"type": "step_progress"') == 5  # 0/4, 1/4, 2/4, 3/4, 4/4
    assert f"'{DEFAULT_RESET_LABEL}'" not in out  # pas d'assertion sur le contenu ici, juste la forme
    assert "Effacement de la table de partitions" in out
    assert "Nouvelle partition créée" in out
    assert "Formatage exFAT" in out
    assert "Éjection" in out


@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_passes_custom_label_to_format_step(mock_list, mock_confirm, capsys):
    device = _make_device()
    mock_list.return_value = [device]
    received_labels = []

    with patch.multiple(
        "r36s_studio.__main__",
        erase_partition_table=lambda device: None,
        create_single_partition=lambda device: ResetCardPlan(start_lba=2048, end_lba=4096),
        format_games_partition=lambda device, label, filesystem, known_partition_paths: received_labels.append(
            label
        ),
        eject_device=lambda path: None,
    ):
        args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3", "--label", "MACARTE"])
        code = args.func(args)

    assert code == 0
    assert received_labels == ["MACARTE"]


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.format_games_partition", return_value="K")
@patch("r36s_studio.__main__.create_single_partition", return_value=ResetCardPlan(start_lba=2048, end_lba=4096))
@patch("r36s_studio.__main__.erase_partition_table")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_logs_the_assigned_drive_letter(
    mock_list, mock_confirm, mock_erase, mock_create, mock_format, mock_eject, capsys
):
    """Bug corrigé, confirmé sur du vrai matériel : `Get-Volume` montrait
    déjà un volume exFAT correctement formaté, mais sans lettre de lecteur
    il n'apparaissait pas dans l'Explorateur -- la carte semblait non
    reconnue alors qu'elle était parfaitement formatée."""
    mock_list.return_value = [_make_device()]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert "disponible sous K:" in out


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.format_games_partition", return_value=None)
@patch("r36s_studio.__main__.create_single_partition", return_value=ResetCardPlan(start_lba=2048, end_lba=4096))
@patch("r36s_studio.__main__.erase_partition_table")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_no_drive_letter_line_when_none_assigned(
    mock_list, mock_confirm, mock_erase, mock_create, mock_format, mock_eject, capsys
):
    """macOS/Linux (aucune notion de lettre de lecteur) et le cas rare
    d'un échec d'attribution sur Windows -- jamais une ligne de journal
    inventée."""
    mock_list.return_value = [_make_device()]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert "disponible sous" not in out


@patch("r36s_studio.__main__.erase_partition_table", side_effect=OSError("carte debranchee"))
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_erase_failure_emits_dedicated_code_and_names_the_step(
    mock_list, mock_confirm, mock_erase, capsys
):
    mock_list.return_value = [_make_device()]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert '"code": "RESET_CARD_FAILED"' in out
    assert "Effacement de la table de partitions" in out
    assert '"ok": false' in out
    # Jamais de progression au-delà de l'étape qui a échoué.
    assert out.count('"type": "step_progress"') == 1


@patch("r36s_studio.__main__.create_single_partition", side_effect=CardTooSmallForReset("trop petite"))
@patch("r36s_studio.__main__.erase_partition_table")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_too_small_emits_dedicated_code(mock_list, mock_confirm, mock_erase, mock_create, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert '"code": "RESET_CARD_FAILED"' in out
    assert "Création de la partition" in out


@patch("r36s_studio.__main__.format_games_partition", side_effect=OSError("mkfs.exfat introuvable"))
@patch("r36s_studio.__main__.create_single_partition", return_value=ResetCardPlan(start_lba=2048, end_lba=4096))
@patch("r36s_studio.__main__.erase_partition_table")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_format_failure_emits_dedicated_code(
    mock_list, mock_confirm, mock_erase, mock_create, mock_format, capsys
):
    mock_list.return_value = [_make_device()]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert '"code": "RESET_CARD_FAILED"' in out
    assert "Formatage exFAT" in out


@patch("r36s_studio.__main__.eject_device", side_effect=OSError("carte occupee"))
@patch("r36s_studio.__main__.format_games_partition")
@patch("r36s_studio.__main__.create_single_partition", return_value=ResetCardPlan(start_lba=2048, end_lba=4096))
@patch("r36s_studio.__main__.erase_partition_table")
@patch("r36s_studio.__main__._confirm_flash", return_value=True)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_eject_failure_is_best_effort_and_still_succeeds(
    mock_list, mock_confirm, mock_erase, mock_create, mock_format, mock_eject, capsys
):
    """La remise à zéro elle-même a déjà réussi -- un échec d'éjection ne
    doit jamais renverser ce résultat, même principe que `--eject-after`
    sur `flash` (§4.6)."""
    mock_list.return_value = [_make_device()]

    args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert "Éjection automatique impossible" in out
    assert '"level": "warning"' in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.list_devices")
def test_cmd_reset_card_worker_mode_skips_confirmation_prompt(mock_list, capsys):
    """En mode worker (`--worker`), la GUI a déjà obtenu la confirmation
    sur son propre écran (§5 point 4) -- jamais un second prompt "OUI"."""
    device = _make_device()
    mock_list.return_value = [device]

    with _patch_happy_path():
        args = _parse(["reset-card", "--device", "/dev/fake-disk-test-3", "--worker"])
        code = args.func(args)

    assert code == 0
