"""Tests de `tri/plan.py` -- aperçu du tri, en lecture seule
(docs/tri-roms.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from r36s_studio.tri.plan import SortCancelled, SortRootRefused, TooManyFiles, build_plan

from . import tri_fixtures as fx


def _names(moves):
    return sorted(member.name for move in moves for member in move.members)


def test_files_are_routed_to_the_firmware_folder(tmp_path):
    fx.write(tmp_path / "Mario.sfc", fx.raw())
    fx.write(tmp_path / "Sonic.md", fx.megadrive())
    fx.write(tmp_path / "sous/Zelda.gba", fx.gba())

    plan = build_plan(str(tmp_path), "rocknix")

    by_folder = {folder: _names(moves) for folder, moves in plan.moves_by_folder().items()}
    assert by_folder == {"gba": ["Zelda.gba"], "megadrive": ["Sonic.md"], "snes": ["Mario.sfc"]}
    assert plan.unidentified == []


def test_folder_names_depend_on_the_target_firmware(tmp_path):
    fx.write(tmp_path / "Sonic.md", fx.megadrive())
    fx.write(tmp_path / "Pac.col", fx.coleco())

    assert set(build_plan(str(tmp_path), "rocknix").moves_by_folder()) == {"megadrive", "coleco"}
    assert set(build_plan(str(tmp_path), "treefrogui").moves_by_folder()) == {"sega", "col"}


def test_unidentified_files_go_to_non_identifies_with_a_reason(tmp_path):
    fx.write(tmp_path / "faux.nes", fx.raw())
    fx.write(tmp_path / "mystere.bin", fx.raw())

    plan = build_plan(str(tmp_path), "arkos")

    assert plan.moves == []
    reasons = {move.members[0].name: (move.folder, move.reason) for move in plan.unidentified}
    assert reasons == {
        "faux.nes": ("_non_identifies", "header_mismatch"),
        "mystere.bin": ("_non_identifies", "bin_unknown"),
    }


def test_system_missing_from_firmware_table_is_not_sorted(tmp_path):
    # dArkOS n'a pas de système Famicom Disk System (es_systems.cfg).
    fx.write(tmp_path / "jeu.fds", fx.fds())
    plan = build_plan(str(tmp_path), "arkos")
    assert plan.moves == []
    assert plan.unidentified[0].reason == "system_not_supported"


def test_existing_system_folders_are_never_scanned(tmp_path):
    fx.write(tmp_path / "snes/Deja.sfc", fx.raw())
    fx.write(tmp_path / "collection/gba/Deja.gba", fx.gba())
    fx.write(tmp_path / "Nouveau.sfc", fx.raw())

    plan = build_plan(str(tmp_path), "rocknix")

    assert _names(plan.moves) == ["Nouveau.sfc"]
    assert sorted(plan.kept_folders) == ["collection/gba", "snes"]


def test_folders_named_after_any_system_of_the_target_firmware_are_kept(tmp_path):
    # Rangement manuel antérieur, sans rapport avec cet outil : `megadrive`
    # contient un jeu GBA, il ne doit pas bouger quand même.
    fx.write(tmp_path / "megadrive/erreur.gba", fx.gba())
    plan = build_plan(str(tmp_path), "rocknix")
    assert plan.moves == [] and plan.unidentified == []


def test_non_identifies_and_ignored_folders_are_skipped(tmp_path):
    fx.write(tmp_path / "_non_identifies/ancien.bin", fx.raw())
    fx.write(tmp_path / "bios/scph1001.bin", fx.raw())
    fx.write(tmp_path / ".cache/x.nes", fx.nes())
    plan = build_plan(str(tmp_path), "rocknix", ignored_dirs=["bios"])
    assert plan.files_seen == 0


def test_differently_cased_system_folder_is_reported_and_blocks_sorting_into_it(tmp_path):
    fx.write(tmp_path / "SNES/Deja.sfc", fx.raw())
    fx.write(tmp_path / "Nouveau.sfc", fx.raw())
    fx.write(tmp_path / "Zelda.gba", fx.gba())

    plan = build_plan(str(tmp_path), "rocknix")

    assert plan.case_warnings == [("SNES", "snes")]
    assert _names(plan.left_in_place) == ["Nouveau.sfc"]
    assert plan.left_in_place[0].reason == "folder_case_conflict"
    assert _names(plan.moves) == ["Zelda.gba"]


def test_cue_and_bin_stay_together_as_one_unidentified_group(tmp_path):
    fx.write(tmp_path / "jeu/Jeu.cue", b'FILE "Jeu (Track 1).bin" BINARY\nFILE "Jeu (Track 2).bin" BINARY\n')
    # Piste 1 porte un en-tête Mega Drive : ne doit pas partir seule vers
    # megadrive, elle appartient au groupe du .cue.
    fx.write(tmp_path / "jeu/Jeu (Track 1).bin", fx.megadrive())
    fx.write(tmp_path / "jeu/Jeu (Track 2).bin", fx.raw())

    plan = build_plan(str(tmp_path), "rocknix")

    assert plan.moves == []
    assert len(plan.unidentified) == 1
    group = plan.unidentified[0]
    assert group.reason == "disc_image"
    assert _names([group]) == ["Jeu (Track 1).bin", "Jeu (Track 2).bin", "Jeu.cue"]


def test_m3u_chain_groups_every_disc(tmp_path):
    fx.write(tmp_path / "Jeu.m3u", b"Jeu (Disc 1).cue\nJeu (Disc 2).cue\n")
    fx.write(tmp_path / "Jeu (Disc 1).cue", b'FILE "Jeu (Disc 1).bin" BINARY\n')
    fx.write(tmp_path / "Jeu (Disc 2).cue", b'FILE "Jeu (Disc 2).bin" BINARY\n')
    fx.write(tmp_path / "Jeu (Disc 1).bin", fx.raw())
    fx.write(tmp_path / "Jeu (Disc 2).bin", fx.raw())

    plan = build_plan(str(tmp_path), "rocknix")

    assert len(plan.unidentified) == 1
    assert len(plan.unidentified[0].members) == 5


def test_cue_with_missing_bin_is_reported(tmp_path):
    fx.write(tmp_path / "Jeu.cue", b'FILE "Absent.bin" BINARY\n')
    plan = build_plan(str(tmp_path), "rocknix")
    assert plan.unidentified[0].reason == "disc_image_missing_files"
    assert plan.unidentified[0].detail == "Absent.bin"


def test_root_named_like_a_system_folder_is_refused(tmp_path):
    root = tmp_path / "snes"
    fx.write(root / "Jeu.sfc", fx.raw())
    with pytest.raises(SortRootRefused) as excinfo:
        build_plan(str(root), "rocknix")
    assert excinfo.value.reason == "system_folder"


def test_filesystem_root_is_refused():
    with pytest.raises(SortRootRefused):
        build_plan(str(Path.cwd().anchor), "rocknix")


def test_journal_file_at_root_is_not_sorted(tmp_path):
    fx.write(tmp_path / "_rangement_journal.json", b"{}")
    assert build_plan(str(tmp_path), "rocknix").files_seen == 0


def test_cancel_stops_the_scan(tmp_path):
    fx.write(tmp_path / "a.sfc", fx.raw())
    with pytest.raises(SortCancelled):
        build_plan(str(tmp_path), "rocknix", should_cancel=lambda: True)


def test_too_many_files_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.tri.plan.LARGE_FOLDER_FILE_THRESHOLD", 2)
    for index in range(3):
        fx.write(tmp_path / f"{index}.sfc", fx.raw())
    with pytest.raises(TooManyFiles):
        build_plan(str(tmp_path), "rocknix")


def test_progress_reports_every_file(tmp_path):
    for index in range(3):
        fx.write(tmp_path / f"{index}.sfc", fx.raw())
    seen = []
    build_plan(str(tmp_path), "rocknix", on_progress=seen.append)
    assert seen == [1, 2, 3]


# --- destination libre --------------------------------------------------------


def test_separate_destination_receives_sorted_games_and_is_checked_for_case_conflicts(tmp_path):
    source, destination = tmp_path / "telechargements", tmp_path / "bibliotheque"
    fx.write(source / "Mario.sfc", fx.raw())
    fx.write(source / "Sonic.md", fx.megadrive())
    (destination / "SNES").mkdir(parents=True)  # autre casse que « snes » attendu

    plan = build_plan(str(source), "rocknix", destination=str(destination))

    assert plan.destination == destination.resolve()
    assert _names(plan.moves) == ["Sonic.md"]
    assert _names(plan.left_in_place) == ["Mario.sfc"]
    assert plan.case_warnings == [(str(destination.resolve() / "SNES"), "snes")]


def test_destination_named_like_a_system_folder_is_refused(tmp_path):
    fx.write(tmp_path / "jeux/Mario.sfc", fx.raw())

    with pytest.raises(SortRootRefused) as excinfo:
        build_plan(str(tmp_path / "jeux"), "rocknix", destination=str(tmp_path / "snes"))
    assert excinfo.value.reason == "destination_system_folder"
