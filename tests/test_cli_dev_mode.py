"""Tests du mode développement CLI (`--allow-disk-image` / `R36S_STUDIO_DEV`)
qui lève l'exclusion des disk images/loop pour tester `backup`/`flash`/
`inject-boot`/`copy-games` sans carte SD réelle. `list_devices` est mocké —
aucun `diskutil`/`lsblk` réel n'est appelé.

Point central : ce mode ne doit JAMAIS être atteignable depuis la GUI, même
si `R36S_STUDIO_DEV` traîne dans l'environnement du shell qui l'a lancée --
d'où le garde-fou `--worker` testé ici indépendamment de l'environnement."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device


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


@pytest.fixture(autouse=True)
def _clean_dev_env(monkeypatch):
    """Isole chaque test de l'environnement réel du poste qui exécute la
    suite : sans ça, un `R36S_STUDIO_DEV` déjà présent dans le shell
    fausserait silencieusement les tests "désactivé par défaut"."""
    monkeypatch.delenv(cli.DEV_MODE_ENV_VAR, raising=False)


# --- désactivé par défaut ---------------------------------------------------


def test_dev_mode_disabled_by_default():
    args = _parse(["list"])
    assert cli._dev_mode_enabled(args) is False


def test_dev_mode_disabled_for_backup_by_default():
    args = _parse(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
    assert cli._dev_mode_enabled(args) is False


def test_dev_mode_disabled_for_inject_boot_by_default():
    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", "x"])
    assert cli._dev_mode_enabled(args) is False


def test_dev_mode_disabled_for_copy_games_by_default():
    args = _parse(["copy-games", "--device", "/dev/fake-disk-test-3", "--games-source", "x"])
    assert cli._dev_mode_enabled(args) is False


# --- activation par --allow-disk-image / variable d'environnement ----------


def test_allow_disk_image_flag_enables_dev_mode():
    args = _parse(["list", "--allow-disk-image"])
    assert cli._dev_mode_enabled(args) is True


def test_env_var_enables_dev_mode(monkeypatch):
    monkeypatch.setenv(cli.DEV_MODE_ENV_VAR, "1")
    args = _parse(["list"])
    assert cli._dev_mode_enabled(args) is True


@pytest.mark.parametrize("value", ["", "0", "false", "False"])
def test_env_var_falsy_values_keep_dev_mode_disabled(monkeypatch, value):
    monkeypatch.setenv(cli.DEV_MODE_ENV_VAR, value)
    args = _parse(["list"])
    assert cli._dev_mode_enabled(args) is False


# --- jamais accessible depuis la GUI (mode worker) --------------------------


def test_worker_mode_disables_dev_mode_even_with_flag():
    args = _parse(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img", "--worker", "--allow-disk-image"]
    )
    assert cli._dev_mode_enabled(args) is False


def test_worker_mode_disables_dev_mode_even_with_env_var(monkeypatch):
    """Le scénario que la GUI doit éviter à tout prix : `R36S_STUDIO_DEV`
    est présent dans l'environnement du shell qui l'a lancée (un
    développeur qui a oublié de le retirer), mais le worker qu'elle
    invoque tourne quand même en toute sécurité."""
    monkeypatch.setenv(cli.DEV_MODE_ENV_VAR, "1")
    args = _parse(["flash", "--image", "x.img", "--device", "/dev/fake-disk-test-3", "--worker"])
    assert cli._dev_mode_enabled(args) is False


def test_no_worker_attribute_does_not_crash_dev_mode_check():
    """`inject-boot`/`copy-games` n'ont pas d'attribut `worker` du tout
    (pas de passage par le worker élevé, §3) — la vérification doit s'en
    accommoder plutôt que planter."""
    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", "x", "--allow-disk-image"])
    assert cli._dev_mode_enabled(args) is True


# --- avertissement visible --------------------------------------------------


def test_warn_dev_mode_prints_warning_to_stderr_when_enabled(capsys):
    args = _parse(["list", "--allow-disk-image"])

    enabled = cli._warn_dev_mode_if_enabled(args)

    assert enabled is True
    err = capsys.readouterr().err
    assert "MODE DÉVELOPPEMENT" in err


def test_warn_dev_mode_silent_when_disabled(capsys):
    args = _parse(["list"])

    enabled = cli._warn_dev_mode_if_enabled(args)

    assert enabled is False
    assert capsys.readouterr().err == ""


# --- effet de bout en bout sur cmd_list/cmd_backup --------------------------


@patch("r36s_studio.__main__.list_devices")
def test_cmd_list_passes_dev_mode_to_list_devices(mock_list):
    mock_list.return_value = []
    args = _parse(["list", "--allow-disk-image"])

    cli.cmd_list(args)

    mock_list.assert_called_once_with(allow_disk_image=True)


@patch("r36s_studio.__main__.list_devices")
def test_cmd_list_defaults_to_dev_mode_disabled(mock_list):
    mock_list.return_value = []
    args = _parse(["list"])

    cli.cmd_list(args)

    mock_list.assert_called_once_with(allow_disk_image=False)


@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_backup_worker_mode_never_passes_dev_mode_to_list_devices(mock_list, mock_backup, tmp_path):
    """Même avec `--allow-disk-image` explicitement passé (ce que la GUI ne
    fait jamais, mais on vérifie le garde-fou lui-même) : en mode worker,
    `list_devices` ne doit jamais recevoir `allow_disk_image=True`."""
    mock_list.return_value = [_make_device()]
    mock_backup.return_value = 10

    args = _parse(
        [
            "backup",
            "--device",
            "/dev/fake-disk-test-3",
            "--output",
            str(tmp_path / "out.img"),
            "--worker",
            "--allow-disk-image",
        ]
    )
    cli.cmd_backup(args)

    mock_list.assert_called_once_with(allow_disk_image=False)
