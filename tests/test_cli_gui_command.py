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
