# R36S Studio
"""Tests de `doublons/journal_check.py` -- signalé explicitement :
« donne-moi une commande pour comparer le journal avec ce qui existe
réellement à la source et à destination, pour vérifier qu'aucun fichier
n'a été perdu »."""

from __future__ import annotations

import json

import pytest

from r36s_studio.doublons.journal_check import verify_journal
from r36s_studio.doublons.move import move_duplicates
from r36s_studio.doublons.scan import Unit


@pytest.fixture(autouse=True)
def _no_fat_check_by_default(monkeypatch):
    """Même garde-fou que `tests/test_doublons_move.py::_no_fat_check_by_
    default` -- voir sa docstring."""
    monkeypatch.setattr("r36s_studio.doublons.move.destination_filesystem_kind", lambda path: None)
    yield


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _single_file_unit(path, content=b"x"):
    _touch(path, content)
    return Unit(representative=path, members=[path], total_size_bytes=len(content), is_linked=False)


def _write_journal(destination, entries):
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "journal.json").write_text(json.dumps(entries), encoding="utf-8")


def test_verify_journal_empty_when_no_journal_file(tmp_path):
    report = verify_journal(str(tmp_path))

    assert report.entries == []
    assert report.ok is True


def test_verify_journal_classifies_a_real_move_as_moved(tmp_path):
    root = tmp_path / "root"
    unit = _single_file_unit(root / "Game.zip", b"x" * 10)

    move_duplicates(str(root), [unit])

    report = verify_journal(str(root / "_doublons"))

    assert len(report.entries) == 1
    assert report.entries[0].status == "MOVED"
    assert report.ok is True
    assert report.lost == []


def test_verify_journal_classifies_a_restored_file_as_restored(tmp_path):
    """`undo_all` retire normalement l'entrée du journal une fois la
    restauration réussie (`undo.py`, § « une entrée retirée du journal »)
    -- le statut `RESTORED` couvre plutôt le cas résiduel d'un journal
    qui n'a pas suivi une restauration menée autrement (remise en place
    manuelle, `undo_all` interrompu avant sa propre réécriture)."""
    destination = tmp_path / "backup"
    source_file = tmp_path / "back_at_source.zip"
    dest_file = destination / "no_longer_here.zip"
    _write_journal(
        destination,
        [{"source": str(source_file), "destination": str(dest_file), "moved_at": "2026-01-01T00:00:00+00:00"}],
    )
    _touch(source_file, b"x")

    report = verify_journal(str(destination))

    assert len(report.entries) == 1
    assert report.entries[0].status == "RESTORED"
    assert report.ok is True


def test_verify_journal_flags_a_file_missing_from_both_sides_as_lost(tmp_path):
    destination = tmp_path / "backup"
    _write_journal(
        destination,
        [
            {
                "source": str(tmp_path / "gone_source.zip"),
                "destination": str(destination / "gone_dest.zip"),
                "moved_at": "2026-01-01T00:00:00+00:00",
            }
        ],
    )

    report = verify_journal(str(destination))

    assert len(report.entries) == 1
    assert report.entries[0].status == "LOST"
    assert report.ok is False
    assert report.lost == report.entries


def test_verify_journal_flags_a_file_present_on_both_sides_as_duplicated(tmp_path):
    destination = tmp_path / "backup"
    source_file = tmp_path / "still_here.zip"
    dest_file = destination / "also_here.zip"
    _touch(source_file, b"x")
    _write_journal(
        destination,
        [{"source": str(source_file), "destination": str(dest_file), "moved_at": "2026-01-01T00:00:00+00:00"}],
    )
    _touch(dest_file, b"x")

    report = verify_journal(str(destination))

    assert len(report.entries) == 1
    assert report.entries[0].status == "DUPLICATED"
    # Une copie en double n'est pas une perte -- ne fait jamais échouer `ok`.
    assert report.ok is True
    assert report.duplicated == report.entries
    assert report.lost == []


def test_verify_journal_mixed_entries_reports_correctly(tmp_path):
    destination = tmp_path / "backup"
    moved_source = tmp_path / "moved_src.zip"
    moved_dest = destination / "moved_dst.zip"
    _touch(moved_source, b"x")
    lost_source = tmp_path / "lost_src.zip"
    lost_dest = destination / "lost_dst.zip"
    _write_journal(
        destination,
        [
            {"source": str(moved_source), "destination": str(moved_dest), "moved_at": "t1"},
            {"source": str(lost_source), "destination": str(lost_dest), "moved_at": "t2"},
        ],
    )
    _touch(moved_dest, b"x")
    moved_source.unlink()  # déplacement réel simulé -- la source a bien disparu

    report = verify_journal(str(destination))

    statuses = {entry.destination: entry.status for entry in report.entries}
    assert statuses[str(moved_dest)] == "MOVED"
    assert statuses[str(lost_dest)] == "LOST"
    assert report.ok is False
    assert len(report.lost) == 1
