"""Tests de `doublons/move.py` -- déplacement des doublons écartés vers
`_doublons/`, jamais une suppression. Couvre les garde-fous ajoutés
après validation du plan (mode simulation, volume différent, lecture
seule, espace insuffisant, journal écrit au fil de l'eau)."""

from __future__ import annotations

import json
import os

import pytest

from r36s_studio.doublons.move import (
    DestinationNotWritable,
    DuplicatesOutsideRoot,
    InsufficientDiskSpace,
    MoveCancelled,
    VolumeMismatch,
    move_duplicates,
)
from r36s_studio.doublons.scan import Unit


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _single_file_unit(path, content=b"x"):
    _touch(path, content)
    return Unit(representative=path, members=[path], total_size_bytes=len(content), is_linked=False)


def test_move_duplicates_moves_file_under_doublons_preserving_relative_path(tmp_path):
    game = tmp_path / "SNES" / "Game.zip"
    unit = _single_file_unit(game, b"x" * 10)

    moved = move_duplicates(str(tmp_path), [unit])

    assert moved == 1
    assert not game.exists()
    assert (tmp_path / "_doublons" / "SNES" / "Game.zip").exists()


def test_move_duplicates_moves_an_entire_linked_unit_never_partially(tmp_path):
    cue = tmp_path / "PSX" / "Game.cue"
    bin_ = tmp_path / "PSX" / "Game.bin"
    _touch(cue, b"cue")
    _touch(bin_, b"bin" * 10)
    unit = Unit(representative=cue, members=[cue, bin_], total_size_bytes=33, is_linked=True)

    moved = move_duplicates(str(tmp_path), [unit])

    assert moved == 2
    assert (tmp_path / "_doublons" / "PSX" / "Game.cue").exists()
    assert (tmp_path / "_doublons" / "PSX" / "Game.bin").exists()


def test_move_duplicates_resolves_name_collision_with_a_numeric_suffix(tmp_path):
    unit = _single_file_unit(tmp_path / "Game.zip")
    _touch(tmp_path / "_doublons" / "Game.zip", b"already there")

    move_duplicates(str(tmp_path), [unit])

    assert (tmp_path / "_doublons" / "Game_2.zip").exists()
    assert (tmp_path / "_doublons" / "Game.zip").read_bytes() == b"already there"


def test_move_duplicates_dry_run_touches_nothing(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)

    moved = move_duplicates(str(tmp_path), [unit], dry_run=True)

    assert moved == 1
    assert game.exists()
    assert not (tmp_path / "_doublons").exists()


def test_move_duplicates_writes_journal_incrementally_so_a_crash_mid_batch_leaves_it_accurate(tmp_path):
    paths = []
    units = []
    for name in ("A.zip", "B.zip", "C.zip"):
        path = tmp_path / name
        units.append(_single_file_unit(path))
        paths.append(path)

    def flaky_progress(done, total):
        if done == 2:
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError):
        move_duplicates(str(tmp_path), units, on_progress=flaky_progress)

    journal = json.loads((tmp_path / "_doublons" / "journal.json").read_text(encoding="utf-8"))
    assert len(journal) == 2
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[2].exists()  # jamais atteint, l'exception a interrompu avant


def test_move_duplicates_aborts_before_any_move_when_doublons_is_on_a_different_volume(tmp_path, monkeypatch):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path).endswith("_doublons"):

            class FakeStat:
                st_dev = result.st_dev + 1

            return FakeStat()
        return result

    monkeypatch.setattr("r36s_studio.doublons.move.os.stat", fake_stat)

    with pytest.raises(VolumeMismatch):
        move_duplicates(str(tmp_path), [unit])

    assert game.exists()


def test_move_duplicates_reports_destination_not_writable_before_moving(tmp_path, monkeypatch):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)

    def fail_open(*args, **kwargs):
        raise OSError("simulated read-only volume")

    monkeypatch.setattr("r36s_studio.doublons.move.open", fail_open, raising=False)

    with pytest.raises(DestinationNotWritable):
        move_duplicates(str(tmp_path), [unit])

    assert game.exists()


def test_move_duplicates_reports_insufficient_disk_space_before_moving(tmp_path, monkeypatch):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game, b"x" * 100)

    class FakeUsage:
        free = 10

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.disk_usage", lambda path: FakeUsage())

    with pytest.raises(InsufficientDiskSpace):
        move_duplicates(str(tmp_path), [unit])

    assert game.exists()


def test_move_duplicates_rejects_a_file_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "Game.zip"
    unit = _single_file_unit(outside)

    with pytest.raises(DuplicatesOutsideRoot):
        move_duplicates(str(root), [unit])


def test_move_duplicates_cooperative_cancel_stops_mid_batch(tmp_path):
    paths = []
    units = []
    for name in ("A.zip", "B.zip"):
        path = tmp_path / name
        units.append(_single_file_unit(path))
        paths.append(path)

    with pytest.raises(MoveCancelled):
        move_duplicates(str(tmp_path), units, should_cancel=lambda: True)

    assert paths[0].exists()
    assert paths[1].exists()


def test_move_duplicates_reports_progress_per_file(tmp_path):
    units = [_single_file_unit(tmp_path / name) for name in ("A.zip", "B.zip")]

    events = []
    move_duplicates(str(tmp_path), units, on_progress=lambda done, total: events.append((done, total)))

    assert events == [(1, 2), (2, 2)]
