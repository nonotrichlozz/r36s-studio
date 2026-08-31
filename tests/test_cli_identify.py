"""Tests de la sous-commande CLI `identify` (__main__.py) : lance le module
`identify` sur un dossier local contenant des `.dtb`, sans carte physique --
pour valider le parseur et la future table de correspondance sur des
variantes de console fournies par d'autres utilisateurs (§5 mode assisté)."""

from __future__ import annotations

from r36s_studio import __main__ as cli


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def test_cmd_identify_prints_board_and_panel_on_success(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "board.dtb").write_bytes(_build_fake_dtb())

    args = _parse(["identify", "--boot-dir", str(tmp_path)])
    code = args.func(args)

    assert code == 0


def test_cmd_identify_prints_board_and_panel_on_success_output(tmp_path, capsys):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "board.dtb").write_bytes(_build_fake_dtb())

    args = _parse(["identify", "--boot-dir", str(tmp_path)])
    args.func(args)

    out = capsys.readouterr().out
    assert "rk3326-evb-lp3-v12" in out
    assert "sitronix,st7703" in out


def test_cmd_identify_lists_examined_files(tmp_path, capsys):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "board.dtb").write_bytes(_build_fake_dtb())
    (tmp_path / "other.dtb").write_bytes(b"garbage")

    args = _parse(["identify", "--boot-dir", str(tmp_path)])
    args.func(args)

    out = capsys.readouterr().out
    assert "board.dtb" in out
    assert "other.dtb" in out


def test_cmd_identify_reports_clone_console(tmp_path, capsys):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "rk3326-evb-lp3-v12-linux.dtb").write_bytes(_build_fake_dtb())

    args = _parse(["identify", "--boot-dir", str(tmp_path)])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert "clone" in out.lower()


def test_cmd_identify_does_not_mention_clone_for_a_standard_board(tmp_path, capsys):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "board.dtb").write_bytes(_build_fake_dtb())

    args = _parse(["identify", "--boot-dir", str(tmp_path)])
    args.func(args)

    out = capsys.readouterr().out
    assert "clone" not in out.lower()


def test_cmd_identify_reports_failure_and_nonzero_exit_when_no_dtb_found(tmp_path, capsys):
    args = _parse(["identify", "--boot-dir", str(tmp_path)])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "no_dtb_found" in out or "aucun" in out.lower()


def test_cmd_identify_reports_failure_when_all_dtb_invalid(tmp_path, capsys):
    (tmp_path / "broken.dtb").write_bytes(b"garbage, not a dtb at all")

    args = _parse(["identify", "--boot-dir", str(tmp_path)])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "all_dtb_invalid" in out or "invalide" in out.lower()


def test_cmd_identify_handles_nonexistent_directory_without_crashing(tmp_path, capsys):
    args = _parse(["identify", "--boot-dir", str(tmp_path / "does-not-exist")])
    code = args.func(args)

    assert code == 1
