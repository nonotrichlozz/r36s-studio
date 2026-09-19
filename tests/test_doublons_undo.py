"""Tests de `doublons/undo.py` -- « Tout annuler », à partir du journal
écrit par `move.py`."""

from __future__ import annotations

import json

from r36s_studio.doublons.move import move_duplicates
from r36s_studio.doublons.scan import Unit
from r36s_studio.doublons.undo import undo_all


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _single_file_unit(path, content=b"x"):
    _touch(path, content)
    return Unit(representative=path, members=[path], total_size_bytes=len(content), is_linked=False)


def test_undo_all_restores_moved_files(tmp_path):
    game = tmp_path / "SNES" / "Game.zip"
    unit = _single_file_unit(game)
    move_duplicates(str(tmp_path), [unit])
    assert not game.exists()

    result = undo_all(str(tmp_path))

    assert result.restored == 1
    assert result.conflicts == []
    assert game.exists()


def test_undo_all_removes_restored_entries_from_the_journal(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)
    move_duplicates(str(tmp_path), [unit])

    undo_all(str(tmp_path))

    journal = json.loads((tmp_path / "_doublons" / "journal.json").read_text(encoding="utf-8"))
    assert journal == []


def test_undo_all_restores_every_session_ever_recorded_not_just_the_last(tmp_path):
    first = _single_file_unit(tmp_path / "First.zip")
    move_duplicates(str(tmp_path), [first])
    second = _single_file_unit(tmp_path / "Second.zip")
    move_duplicates(str(tmp_path), [second])

    result = undo_all(str(tmp_path))

    assert result.restored == 2
    assert (tmp_path / "First.zip").exists()
    assert (tmp_path / "Second.zip").exists()


def test_undo_all_reports_conflict_when_original_path_is_occupied_again(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)
    move_duplicates(str(tmp_path), [unit])
    _touch(game, b"a new file was placed here since")

    result = undo_all(str(tmp_path))

    assert result.restored == 0
    assert len(result.conflicts) == 1
    assert result.conflicts[0].reason == "source_occupied"
    journal = json.loads((tmp_path / "_doublons" / "journal.json").read_text(encoding="utf-8"))
    assert len(journal) == 1  # jamais retirée du journal, un futur essai reste possible


def test_undo_all_reports_conflict_when_the_moved_file_is_gone(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)
    move_duplicates(str(tmp_path), [unit])
    (tmp_path / "_doublons" / "Game.zip").unlink()

    result = undo_all(str(tmp_path))

    assert result.restored == 0
    assert result.conflicts[0].reason == "destination_missing"


def test_undo_all_never_overwrites_an_existing_file(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game, b"original")
    move_duplicates(str(tmp_path), [unit])
    _touch(game, b"different content placed after the move")

    undo_all(str(tmp_path))

    assert game.read_bytes() == b"different content placed after the move"


def test_undo_all_with_no_journal_restores_nothing(tmp_path):
    result = undo_all(str(tmp_path))

    assert result.restored == 0
    assert result.conflicts == []
