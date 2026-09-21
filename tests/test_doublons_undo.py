"""Tests de `doublons/undo.py` -- « Tout annuler », à partir du/des
journal(aux) écrit(s) par `move.py` dans le(s) dossier(s) de destination.
`undo_all` balaie une liste de destinations (signalé explicitement :
« pour que Tout annuler retrouve le journal même si la destination a
changé »)."""

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

    result = undo_all([str(tmp_path / "_doublons")])

    assert result.restored == 1
    assert result.conflicts == []
    assert game.exists()


def test_undo_all_removes_restored_entries_from_the_journal(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)
    move_duplicates(str(tmp_path), [unit])

    undo_all([str(tmp_path / "_doublons")])

    journal = json.loads((tmp_path / "_doublons" / "journal.json").read_text(encoding="utf-8"))
    assert journal == []


def test_undo_all_restores_every_session_ever_recorded_not_just_the_last(tmp_path):
    first = _single_file_unit(tmp_path / "First.zip")
    move_duplicates(str(tmp_path), [first])
    second = _single_file_unit(tmp_path / "Second.zip")
    move_duplicates(str(tmp_path), [second])

    result = undo_all([str(tmp_path / "_doublons")])

    assert result.restored == 2
    assert (tmp_path / "First.zip").exists()
    assert (tmp_path / "Second.zip").exists()


def test_undo_all_reports_conflict_when_original_path_is_occupied_again(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)
    move_duplicates(str(tmp_path), [unit])
    _touch(game, b"a new file was placed here since")

    result = undo_all([str(tmp_path / "_doublons")])

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

    result = undo_all([str(tmp_path / "_doublons")])

    assert result.restored == 0
    assert result.conflicts[0].reason == "destination_missing"


def test_undo_all_never_overwrites_an_existing_file(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game, b"original")
    move_duplicates(str(tmp_path), [unit])
    _touch(game, b"different content placed after the move")

    undo_all([str(tmp_path / "_doublons")])

    assert game.read_bytes() == b"different content placed after the move"


def test_undo_all_with_no_journal_restores_nothing(tmp_path):
    result = undo_all([str(tmp_path / "_doublons")])

    assert result.restored == 0
    assert result.conflicts == []


def test_undo_all_with_no_destinations_restores_nothing(tmp_path):
    result = undo_all([])

    assert result.restored == 0
    assert result.conflicts == []


# --- Plusieurs destinations (signalé explicitement) -------------------------


def test_undo_all_sweeps_every_known_destination_even_if_not_the_last_used(tmp_path):
    """La même carte peut avoir été traitée avec des destinations
    différentes d'une session à l'autre -- « Tout annuler » doit
    retrouver le journal de chacune, pas seulement celle de la session en
    cours."""
    destination_a = tmp_path / "backup_a"
    destination_b = tmp_path / "backup_b"
    game_a = tmp_path / "root" / "A.zip"
    game_b = tmp_path / "root" / "B.zip"
    move_duplicates(str(tmp_path / "root"), [_single_file_unit(game_a)], destination=str(destination_a))
    move_duplicates(str(tmp_path / "root"), [_single_file_unit(game_b)], destination=str(destination_b))
    assert not game_a.exists()
    assert not game_b.exists()

    result = undo_all([str(destination_a), str(destination_b)])

    assert result.restored == 2
    assert game_a.exists()
    assert game_b.exists()


def test_undo_all_restores_from_a_destination_different_from_the_current_one(tmp_path):
    """Signalé explicitement : « annulation depuis une autre destination »
    -- la session en cours utilise `destination_current`, mais un journal
    non traité existe encore à `destination_old` (session précédente) ;
    balayer les deux doit restaurer les deux."""
    destination_old = tmp_path / "old_backup"
    destination_current = tmp_path / "current_backup"
    old_game = tmp_path / "root" / "Old.zip"
    move_duplicates(str(tmp_path / "root"), [_single_file_unit(old_game)], destination=str(destination_old))
    assert not old_game.exists()

    # La session en cours n'a encore rien déplacé vers `destination_current`
    # (dossier jamais créé) -- balayer les deux destinations connues ne
    # doit ni échouer ni ignorer celle qui a réellement un journal.
    result = undo_all([str(destination_current), str(destination_old)])

    assert result.restored == 1
    assert old_game.exists()


def test_undo_all_deduplicates_the_same_destination_listed_twice(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)
    move_duplicates(str(tmp_path), [unit])

    result = undo_all([str(tmp_path / "_doublons"), str(tmp_path / "_doublons")])

    assert result.restored == 1  # jamais compté deux fois


def test_undo_all_aggregates_conflicts_across_destinations(tmp_path):
    destination_a = tmp_path / "backup_a"
    destination_b = tmp_path / "backup_b"
    game_a = tmp_path / "root" / "A.zip"
    game_b = tmp_path / "root" / "B.zip"
    move_duplicates(str(tmp_path / "root"), [_single_file_unit(game_a)], destination=str(destination_a))
    move_duplicates(str(tmp_path / "root"), [_single_file_unit(game_b)], destination=str(destination_b))
    (destination_a / "A.zip").unlink()
    (destination_b / "B.zip").unlink()

    result = undo_all([str(destination_a), str(destination_b)])

    assert result.restored == 0
    assert len(result.conflicts) == 2
    assert {conflict.reason for conflict in result.conflicts} == {"destination_missing"}
