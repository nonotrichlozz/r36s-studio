"""Tests de `tri/apply.py` -- déplacement confirmé et annulation
(docs/tri-roms.md). Déplacer, jamais supprimer."""

from __future__ import annotations

import json

import pytest

from r36s_studio.doublons.move import REASON_ACCESS_DENIED, MoveFileFailed
from r36s_studio.tri.apply import MAX_CONSECUTIVE_FAILURES, apply_plan, has_journal, journal_path, undo_sort
from r36s_studio.tri.plan import build_plan
from r36s_studio.tri.regions import RegionFilter

from . import tri_fixtures as fx


def _all_files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_apply_moves_sorted_and_unidentified_files_and_undo_restores_them(tmp_path):
    fx.write(tmp_path / "Mario.sfc", fx.raw())
    fx.write(tmp_path / "sous/Zelda.gba", fx.gba())
    fx.write(tmp_path / "sous/mystere.bin", fx.raw())
    before = _all_files(tmp_path)

    result = apply_plan(build_plan(str(tmp_path), "rocknix"))

    assert result.moved_files == 3
    assert result.failures == [] and not result.cancelled
    files = _all_files(tmp_path)
    assert "snes/Mario.sfc" in files
    assert "gba/Zelda.gba" in files
    # Chemin d'origine conservé sous _non_identifies
    assert "_non_identifies/sous/mystere.bin" in files
    assert has_journal(str(tmp_path))

    undo = undo_sort(str(tmp_path))

    assert undo.restored == 3 and undo.conflicts == []
    assert _all_files(tmp_path) == before
    assert not journal_path(str(tmp_path)).exists()


def test_existing_file_is_never_overwritten(tmp_path):
    fx.write(tmp_path / "snes/Mario.sfc", b"ancien")
    fx.write(tmp_path / "nouveau/Mario.sfc", b"nouveau")

    apply_plan(build_plan(str(tmp_path), "rocknix"))

    assert (tmp_path / "snes/Mario.sfc").read_bytes() == b"ancien"
    assert (tmp_path / "snes/Mario_2.sfc").read_bytes() == b"nouveau"


def test_unidentified_group_is_left_in_place_rather_than_renamed(tmp_path):
    # Renommer un .bin casserait la référence du .cue : le groupe entier
    # reste à sa place si _non_identifies contient déjà l'un des fichiers.
    fx.write(tmp_path / "_non_identifies/Jeu.cue", b"ancien")
    fx.write(tmp_path / "Jeu.cue", b'FILE "Jeu.bin" BINARY\n')
    fx.write(tmp_path / "Jeu.bin", fx.raw())

    result = apply_plan(build_plan(str(tmp_path), "rocknix"))

    assert result.moved_files == 0
    assert len(result.skipped_existing) == 1
    assert (tmp_path / "Jeu.cue").exists() and (tmp_path / "Jeu.bin").exists()


def test_files_blocked_by_case_conflict_are_not_moved(tmp_path):
    fx.write(tmp_path / "SNES/Deja.sfc", fx.raw())
    fx.write(tmp_path / "Nouveau.sfc", fx.raw())

    result = apply_plan(build_plan(str(tmp_path), "rocknix"))

    assert result.moved_files == 0
    assert (tmp_path / "Nouveau.sfc").exists()


def test_journal_is_written_one_line_per_file(tmp_path):
    fx.write(tmp_path / "a.sfc", fx.raw())
    fx.write(tmp_path / "b.sfc", fx.raw())

    apply_plan(build_plan(str(tmp_path), "rocknix"))

    lines = journal_path(str(tmp_path)).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all({"source", "destination", "moved_at"} <= set(json.loads(line)) for line in lines)


def test_truncated_last_journal_line_is_ignored_by_undo(tmp_path):
    fx.write(tmp_path / "a.sfc", fx.raw())
    apply_plan(build_plan(str(tmp_path), "rocknix"))
    with open(journal_path(str(tmp_path)), "a", encoding="utf-8") as handle:
        handle.write('{"source": "coup')

    assert undo_sort(str(tmp_path)).restored == 1
    assert (tmp_path / "a.sfc").exists()


def test_undo_never_overwrites_a_recreated_original(tmp_path):
    fx.write(tmp_path / "a.sfc", b"jeu")
    apply_plan(build_plan(str(tmp_path), "rocknix"))
    fx.write(tmp_path / "a.sfc", b"recree")

    result = undo_sort(str(tmp_path))

    assert result.restored == 0
    assert result.conflicts[0].reason == "source_occupied"
    assert (tmp_path / "a.sfc").read_bytes() == b"recree"
    assert (tmp_path / "snes/a.sfc").read_bytes() == b"jeu"
    # L'entrée reste au journal pour un futur essai.
    assert has_journal(str(tmp_path))


def test_second_sort_after_first_leaves_sorted_games_alone(tmp_path):
    fx.write(tmp_path / "a.sfc", fx.raw())
    apply_plan(build_plan(str(tmp_path), "rocknix"))

    plan = build_plan(str(tmp_path), "rocknix")

    assert plan.moves == [] and plan.unidentified == []


def test_cancel_stops_before_next_unit(tmp_path):
    fx.write(tmp_path / "a.sfc", fx.raw())
    fx.write(tmp_path / "b.sfc", fx.raw())
    plan = build_plan(str(tmp_path), "rocknix")

    result = apply_plan(plan, should_cancel=lambda: True)

    assert result.cancelled and result.moved_files == 0


def test_source_removed_after_preview_is_reported(tmp_path):
    path = fx.write(tmp_path / "a.sfc", fx.raw())
    plan = build_plan(str(tmp_path), "rocknix")
    path.unlink()

    result = apply_plan(plan)

    assert result.missing_sources == [path.resolve()] or result.missing_sources == [path]


def test_failures_are_collected_and_repeated_failures_abort(tmp_path, monkeypatch):
    for index in range(MAX_CONSECUTIVE_FAILURES + 5):
        fx.write(tmp_path / f"{index}.sfc", fx.raw())
    plan = build_plan(str(tmp_path), "rocknix")

    def failing_move(member, destination, expected_sha256, cross_volume):
        raise MoveFileFailed(str(member), "rename", REASON_ACCESS_DENIED, "refusé")

    monkeypatch.setattr("r36s_studio.tri.apply._move_one_file", failing_move)

    result = apply_plan(plan)

    assert result.aborted
    assert len(result.failures) == MAX_CONSECUTIVE_FAILURES
    assert result.moved_files == 0


def test_undo_without_journal_does_nothing(tmp_path):
    assert undo_sort(str(tmp_path)).restored == 0
    assert not (tmp_path / "_rangement_journal.json").exists()


@pytest.mark.parametrize("firmware", ["arkos", "rocknix", "emuelec", "treefrogui"])
def test_every_firmware_table_sorts_a_gba_game(tmp_path, firmware):
    fx.write(tmp_path / "Zelda.gba", fx.gba())
    result = apply_plan(build_plan(str(tmp_path), firmware))
    assert result.moved_files == 1
    assert (tmp_path / "gba" / "Zelda.gba").exists()


def test_apply_to_a_separate_destination_sets_aside_near_the_source_and_undo_restores(tmp_path):
    source, destination = tmp_path / "telechargements", tmp_path / "carte"
    fx.write(source / "Sonic (Europe).md", fx.megadrive())
    fx.write(source / "sous/Streets (Japan).md", fx.megadrive())
    fx.write(source / "mystere.bin", fx.raw())
    before = _all_files(source)

    criteria = RegionFilter(regions=frozenset({"Europe"}))
    result = apply_plan(build_plan(str(source), "rocknix", destination=str(destination), region_filter=criteria))

    assert result.moved_files == 3 and result.failures == []
    # La destination ne reçoit que les jeux rangés ; le reste reste près de la source.
    assert _all_files(destination) == ["megadrive/Sonic (Europe).md"]
    assert _all_files(source) == [
        "_hors_filtre/sous/Streets (Japan).md",
        "_non_identifies/mystere.bin",
        "_rangement_journal.json",
    ]

    undo = undo_sort(str(source))

    assert undo.restored == 3 and undo.conflicts == []
    assert _all_files(source) == before
    assert _all_files(destination) == []


def test_destination_on_another_drive_uses_verified_copy_and_checks_space_first(tmp_path):
    from unittest.mock import patch

    from r36s_studio.doublons.move import InsufficientDiskSpace

    source, destination = tmp_path / "pc", tmp_path / "carte"
    fx.write(source / "Sonic (Europe).md", fx.megadrive())
    fx.write(source / "Streets (Japan).md", fx.megadrive())
    plan = build_plan(str(source), "rocknix", destination=str(destination), region_filter=RegionFilter(regions=frozenset({"Europe"})))

    with patch("r36s_studio.tri.apply.is_cross_volume_destination", return_value=True), patch(
        "r36s_studio.tri.apply._check_disk_space", side_effect=InsufficientDiskSpace(str(destination), 10, 1)
    ):
        with pytest.raises(InsufficientDiskSpace):
            apply_plan(plan)
    assert _all_files(source) == ["Sonic (Europe).md", "Streets (Japan).md"]  # rien n'a bougé

    calls = []
    with patch("r36s_studio.tri.apply.is_cross_volume_destination", return_value=True), patch(
        "r36s_studio.tri.apply._move_one_file", side_effect=lambda member, dest, sha, cross_volume: calls.append((member.name, cross_volume))
    ):
        apply_plan(plan)
    # Le jeu rangé passe par la copie vérifiée ; le jeu écarté reste sur le disque de la source.
    assert sorted(calls) == [("Sonic (Europe).md", True), ("Streets (Japan).md", False)]
