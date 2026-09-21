"""Tests de `doublons/scan.py` -- détection des jeux en double sur un
dossier quelconque (docs/doublons.md). Purement lecture seule sur de
vrais dossiers/fichiers temporaires (`tmp_path`) -- pas de Qt, pas de
mock : le comportement du vrai système de fichiers est ce qu'on veut
vérifier ici, en particulier la règle critique des fichiers liés."""

from __future__ import annotations

import hashlib

import pytest

from r36s_studio.doublons.scan import OperationCancelled, find_duplicates


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_cue(path, filenames):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f'FILE "{name}" BINARY' for name in filenames]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_m3u(path, filenames):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(filenames) + "\n", encoding="utf-8")


def _write_gdi(path, track_filenames):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [str(len(track_filenames))]
    for index, name in enumerate(track_filenames, start=1):
        lines.append(f"{index} 0 4 2352 {name} 0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- Palier 1 : copies identiques -------------------------------------


def test_identical_content_same_size_is_an_exact_duplicate(tmp_path):
    _touch(tmp_path / "SNES" / "Game (USA).sfc", b"identical-content")
    _touch(tmp_path / "SNES" / "Game (Europe).sfc", b"identical-content")

    result = find_duplicates(str(tmp_path))

    assert len(result.exact_duplicate_groups) == 1
    group = result.exact_duplicate_groups[0]
    names = {unit.representative.name for unit in group.units}
    assert names == {"Game (USA).sfc", "Game (Europe).sfc"}
    # § affichée à côté du titre du groupe -- doit être la vraie empreinte
    # du contenu, pas une valeur arbitraire.
    assert group.sha256 == hashlib.sha256(b"identical-content").hexdigest()
    # Réutilisée par move.py pour un déplacement vers un autre disque
    # (copie + vérifie + supprime la source, jamais recalculée) -- déjà
    # posée sur chaque `Unit` du groupe, pas seulement sur le groupe.
    for unit in group.units:
        assert unit.known_sha256 == group.sha256


def test_units_in_a_version_group_have_no_known_sha256(tmp_path):
    """Palier 2 (versions différentes) -- jamais de hachage déjà connu,
    contrairement au palier 1 ci-dessus : ces unités ont un contenu
    différent par construction, aucune empreinte commune à réutiliser."""
    _touch(tmp_path / "SNES" / "Game (USA).sfc", b"contenu americain")
    _touch(tmp_path / "SNES" / "Game (Europe).sfc", b"contenu different, taille differente aussi!")

    result = find_duplicates(str(tmp_path))

    assert result.exact_duplicate_groups == []
    assert len(result.version_groups) == 1
    assert all(unit.known_sha256 is None for unit in result.version_groups[0].units)


def test_same_size_different_content_is_never_an_exact_duplicate(tmp_path):
    _touch(tmp_path / "SNES" / "Game (USA).sfc", b"aaaaaaaaaa")
    _touch(tmp_path / "SNES" / "Game (Europe).sfc", b"bbbbbbbbbb")

    result = find_duplicates(str(tmp_path))

    assert result.exact_duplicate_groups == []
    assert len(result.version_groups) == 1  # reste couvert par le palier 2


def test_single_file_is_never_an_exact_duplicate_group(tmp_path):
    _touch(tmp_path / "GBA" / "Solo.gba")

    result = find_duplicates(str(tmp_path))

    assert result.exact_duplicate_groups == []
    assert result.version_groups == []


# --- Palier 2 : versions du même jeu -----------------------------------


def test_same_title_in_different_system_folders_is_never_grouped(tmp_path):
    _touch(tmp_path / "SNES" / "Aladdin.zip")
    _touch(tmp_path / "Megadrive" / "Aladdin.zip")

    result = find_duplicates(str(tmp_path))

    assert result.version_groups == []


def test_case_and_accent_insensitive_title_match_within_same_system(tmp_path):
    _touch(tmp_path / "GBA" / "Pokémon (USA).gba", b"a" * 10)
    _touch(tmp_path / "GBA" / "POKEMON (Europe).gba", b"b" * 20)

    result = find_duplicates(str(tmp_path))

    assert len(result.version_groups) == 1
    assert result.version_groups[0].normalized_title == "pokemon"


def test_version_group_suggests_keeping_highest_priority_region(tmp_path):
    """France/Fr > Europe > World > USA > Japan > autre."""
    _touch(tmp_path / "SNES" / "Game (USA).sfc", b"a" * 10)
    _touch(tmp_path / "SNES" / "Game (Europe).sfc", b"b" * 20)
    _touch(tmp_path / "SNES" / "Game (France).sfc", b"c" * 5)

    result = find_duplicates(str(tmp_path))

    assert len(result.version_groups) == 1
    assert result.version_groups[0].suggested_keep.representative.name == "Game (France).sfc"


def test_version_group_tie_broken_by_revision_then_size(tmp_path):
    _touch(tmp_path / "SNES" / "Game (Europe).sfc", b"a" * 5)
    _touch(tmp_path / "SNES" / "Game (Europe) (Rev A).sfc", b"b" * 5)
    _touch(tmp_path / "SNES" / "Game (Europe) (Rev B).sfc", b"c" * 1)  # plus petit, mais révision plus haute

    result = find_duplicates(str(tmp_path))

    assert len(result.version_groups) == 1
    assert result.version_groups[0].suggested_keep.representative.name == "Game (Europe) (Rev B).sfc"


def test_root_level_files_use_empty_system_folder(tmp_path):
    _touch(tmp_path / "Loose (USA).zip", b"a" * 10)
    _touch(tmp_path / "Loose (Europe).zip", b"b" * 10)

    result = find_duplicates(str(tmp_path))

    assert len(result.version_groups) == 1
    assert result.version_groups[0].system_folder == ""


def test_box_art_image_is_never_grouped_with_a_matching_rom_name(tmp_path):
    _touch(tmp_path / "SNES" / "Game.zip", b"a" * 10)
    _touch(tmp_path / "SNES" / "Game.png", b"b" * 10)

    result = find_duplicates(str(tmp_path))

    assert result.version_groups == []


def test_unknown_extension_is_never_treated_as_a_candidate(tmp_path):
    _touch(tmp_path / "SNES" / "Readme.txt", b"a" * 10)
    _touch(tmp_path / "SNES" / "Notes.txt", b"a" * 10)

    result = find_duplicates(str(tmp_path))

    assert result.exact_duplicate_groups == []
    assert result.version_groups == []


# --- Règle critique : fichiers liés -------------------------------------


def test_cue_and_bin_are_never_separated_when_deduplicating(tmp_path):
    _write_cue(tmp_path / "PSX" / "Game (USA).cue", ["Game (USA).bin"])
    _touch(tmp_path / "PSX" / "Game (USA).bin", b"x" * 500)
    _write_cue(tmp_path / "PSX" / "Game (Europe).cue", ["Game (Europe).bin"])
    _touch(tmp_path / "PSX" / "Game (Europe).bin", b"y" * 500)

    result = find_duplicates(str(tmp_path))

    assert result.exact_duplicate_groups == []  # palier 1 limité aux fichiers uniques (v1)
    assert len(result.version_groups) == 1
    group = result.version_groups[0]
    assert len(group.units) == 2
    for unit in group.units:
        assert unit.is_linked is True
        assert {member.name for member in unit.members} == {unit.representative.name, unit.representative.stem + ".bin"}


def test_orphan_bin_without_a_cue_is_never_a_candidate(tmp_path):
    _touch(tmp_path / "PSX" / "Track.bin", b"x" * 10)
    _touch(tmp_path / "PSX" / "Track2.bin", b"x" * 10)  # même contenu, mais orphelins

    result = find_duplicates(str(tmp_path))

    assert result.exact_duplicate_groups == []
    assert result.version_groups == []


def test_m3u_and_its_discs_are_never_separated(tmp_path):
    _write_m3u(
        tmp_path / "PSX" / "Game (USA).m3u",
        ["Game (USA) (Disc 1).chd", "Game (USA) (Disc 2).chd"],
    )
    _touch(tmp_path / "PSX" / "Game (USA) (Disc 1).chd", b"1" * 10)
    _touch(tmp_path / "PSX" / "Game (USA) (Disc 2).chd", b"2" * 10)
    _write_m3u(
        tmp_path / "PSX" / "Game (Europe).m3u",
        ["Game (Europe) (Disc 1).chd", "Game (Europe) (Disc 2).chd"],
    )
    _touch(tmp_path / "PSX" / "Game (Europe) (Disc 1).chd", b"3" * 10)
    _touch(tmp_path / "PSX" / "Game (Europe) (Disc 2).chd", b"4" * 10)

    result = find_duplicates(str(tmp_path))

    assert len(result.version_groups) == 1
    for unit in result.version_groups[0].units:
        assert len(unit.members) == 3  # le .m3u + ses 2 disques, jamais séparés


def test_gdi_and_its_tracks_are_never_separated(tmp_path):
    _write_gdi(tmp_path / "DC" / "Game (USA).gdi", ["track01.bin", "track02.raw"])
    _touch(tmp_path / "DC" / "track01.bin", b"1" * 10)
    _touch(tmp_path / "DC" / "track02.raw", b"2" * 10)
    _write_gdi(tmp_path / "DC" / "Game (Europe).gdi", ["track01e.bin", "track02e.raw"])
    _touch(tmp_path / "DC" / "track01e.bin", b"3" * 10)
    _touch(tmp_path / "DC" / "track02e.raw", b"4" * 10)

    result = find_duplicates(str(tmp_path))

    assert len(result.version_groups) == 1
    for unit in result.version_groups[0].units:
        assert len(unit.members) == 3  # le .gdi + ses 2 pistes, jamais séparés


def test_missing_linked_file_excludes_the_whole_group_and_is_reported(tmp_path):
    _write_cue(tmp_path / "PSX" / "Game.cue", ["Game.bin"])
    # "Game.bin" volontairement absent du disque

    result = find_duplicates(str(tmp_path))

    assert result.version_groups == []
    assert len(result.excluded) == 1
    assert result.excluded[0].manifest.name == "Game.cue"
    assert "Game.bin" in result.excluded[0].missing


def test_a_disc_referenced_by_an_m3u_is_never_also_counted_as_a_standalone_unit(tmp_path):
    """Un .chd listé dans un .m3u ne doit jamais aussi apparaître comme
    unité solo -- sinon un même fichier physique compterait deux fois."""
    _write_m3u(tmp_path / "PSX" / "Game (USA).m3u", ["Disc.chd"])
    _touch(tmp_path / "PSX" / "Disc.chd", b"x" * 10)
    _write_m3u(tmp_path / "PSX" / "Game (Europe).m3u", ["Disc2.chd"])
    _touch(tmp_path / "PSX" / "Disc2.chd", b"y" * 10)

    result = find_duplicates(str(tmp_path))

    assert len(result.version_groups) == 1
    assert len(result.version_groups[0].units) == 2  # jamais 4 (2 manifestes + 2 disques comptés à part)


# --- Dossiers ignorés ----------------------------------------------------


def test_ignored_folder_contents_are_never_scanned(tmp_path):
    _touch(tmp_path / "media" / "Game.zip")
    _touch(tmp_path / "media" / "Game2.zip")

    result = find_duplicates(str(tmp_path), ignored_dirs=["media"])

    assert result.files_scanned == 0
    assert result.version_groups == []


def test_ignored_folder_match_is_case_insensitive(tmp_path):
    _touch(tmp_path / "MEDIA" / "Game.zip")

    result = find_duplicates(str(tmp_path), ignored_dirs=["media"])

    assert result.files_scanned == 0


def test_dot_prefixed_folder_is_always_ignored_even_without_being_listed(tmp_path):
    _touch(tmp_path / ".hidden" / "Game.zip")
    _touch(tmp_path / ".hidden" / "Game2.zip")

    result = find_duplicates(str(tmp_path))

    assert result.files_scanned == 0


def test_doublons_folder_is_never_rescanned(tmp_path):
    _touch(tmp_path / "_doublons" / "SNES" / "Old.zip")

    result = find_duplicates(str(tmp_path))

    assert result.files_scanned == 0


# --- Annulation / seuil des dossiers volumineux --------------------------


def test_cancellation_raises_operation_cancelled(tmp_path):
    _touch(tmp_path / "A.zip")
    _touch(tmp_path / "B.zip")

    with pytest.raises(OperationCancelled):
        find_duplicates(str(tmp_path), should_cancel=lambda: True)


def test_large_folder_threshold_triggers_confirmation_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.doublons.scan.LARGE_FOLDER_FILE_THRESHOLD", 2)
    _touch(tmp_path / "A.zip")
    _touch(tmp_path / "B.zip")
    _touch(tmp_path / "C.zip")

    calls = []

    def confirm():
        calls.append(True)
        return True

    result = find_duplicates(str(tmp_path), confirm_large_folder=confirm)

    assert calls == [True]
    assert result.files_scanned == 3


def test_large_folder_threshold_refused_cancels_the_scan(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.doublons.scan.LARGE_FOLDER_FILE_THRESHOLD", 2)
    _touch(tmp_path / "A.zip")
    _touch(tmp_path / "B.zip")
    _touch(tmp_path / "C.zip")

    with pytest.raises(OperationCancelled):
        find_duplicates(str(tmp_path), confirm_large_folder=lambda: False)


def test_progress_callback_is_called_for_every_file_seen(tmp_path):
    _touch(tmp_path / "A.zip")
    _touch(tmp_path / "B.zip")
    _touch(tmp_path / "Readme.txt")  # compte aussi, même s'il n'est jamais candidat

    counts = []
    find_duplicates(str(tmp_path), on_progress=counts.append)

    assert counts == [1, 2, 3]
