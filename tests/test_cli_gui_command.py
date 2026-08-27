"""Test de `python -m r36s_studio gui` (cmd_gui) : dispatch vers
`gui.app.run` sans importer PySide6 avant que la sous-commande ne soit
réellement invoquée (le CLI doit rester utilisable même sans PySide6
installé, pour `list`/`backup`/`flash`)."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio import __main__ as cli


def test_gui_subcommand_is_registered():
    parser = cli.build_parser()
    args = parser.parse_args(["gui"])
    assert args.func is cli.cmd_gui


@patch("r36s_studio.gui.app.run", return_value=0)
def test_cmd_gui_calls_app_run(mock_run):
    parser = cli.build_parser()
    args = parser.parse_args(["gui"])

    code = args.func(args)

    assert code == 0
    mock_run.assert_called_once()


@patch("r36s_studio.gui.app.run", return_value=0)
def test_main_with_explicit_empty_argv_defaults_to_gui(mock_run):
    """Nécessaire pour le binaire empaqueté (§7) : un double-clic depuis le
    Finder invoque l'exécutable sans le moindre argument -- sans ce repli,
    `argparse` exigerait une sous-commande sur une erreur invisible (aucune
    console), et l'appli semblerait juste ne rien faire."""
    code = cli.main([])

    assert code == 0
    mock_run.assert_called_once()


@patch("r36s_studio.gui.app.run", return_value=0)
@patch("r36s_studio.__main__.sys.argv", ["r36s_studio"])
def test_main_with_none_and_empty_sys_argv_defaults_to_gui(mock_run):
    code = cli.main(None)

    assert code == 0
    mock_run.assert_called_once()


def test_main_with_explicit_subcommand_is_unaffected():
    """Le repli sur la GUI ne doit jamais intercepter un usage CLI normal."""
    with patch("r36s_studio.__main__.list_devices", return_value=[]):
        code = cli.main(["list"])

    assert code == 0
