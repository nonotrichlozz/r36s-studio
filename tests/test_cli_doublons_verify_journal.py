# R36S Studio
"""Tests de la sous-commande CLI `doublons-verify-journal` (__main__.py) --
signalé explicitement : « donne-moi une commande pour comparer le journal
avec ce qui existe réellement à la source et à destination, pour vérifier
qu'aucun fichier n'a été perdu »."""

from __future__ import annotations

import json

from r36s_studio import __main__ as cli


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_journal(destination, entries):
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "journal.json").write_text(json.dumps(entries), encoding="utf-8")


def test_cmd_doublons_verify_journal_returns_zero_when_no_journal(tmp_path, capsys):
    args = _parse(["doublons-verify-journal", "--destination", str(tmp_path)])
    code = args.func(args)

    assert code == 0
    assert "Aucune entrée" in capsys.readouterr().out


def test_cmd_doublons_verify_journal_returns_zero_when_nothing_lost(tmp_path, capsys):
    destination = tmp_path / "backup"
    dest_file = destination / "moved.zip"
    _write_journal(
        destination,
        [{"source": str(tmp_path / "gone.zip"), "destination": str(dest_file), "moved_at": "t1"}],
    )
    _touch(dest_file)

    args = _parse(["doublons-verify-journal", "--destination", str(destination)])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert "Aucun fichier perdu" in out


def test_cmd_doublons_verify_journal_returns_one_and_lists_lost_files(tmp_path, capsys):
    destination = tmp_path / "backup"
    lost_source = tmp_path / "lost_src.zip"
    lost_dest = destination / "lost_dst.zip"
    _write_journal(
        destination,
        [{"source": str(lost_source), "destination": str(lost_dest), "moved_at": "t1"}],
    )

    args = _parse(["doublons-verify-journal", "--destination", str(destination)])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert str(lost_source) in out
    assert str(lost_dest) in out
    assert "perdu" in out.lower()
