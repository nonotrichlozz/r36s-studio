from __future__ import annotations

from r36s_studio.doublons.linked_files import resolve_manifest


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_resolve_cue_finds_its_bin(tmp_path):
    cue = tmp_path / "Game.cue"
    cue.write_text('FILE "Game.bin" BINARY\n', encoding="utf-8")
    _touch(tmp_path / "Game.bin")

    resolution = resolve_manifest(cue)

    assert resolution.missing == []
    assert [m.name for m in resolution.members] == ["Game.bin"]


def test_resolve_cue_is_case_insensitive_on_disk(tmp_path):
    cue = tmp_path / "Game.cue"
    cue.write_text('FILE "GAME.BIN" BINARY\n', encoding="utf-8")
    _touch(tmp_path / "game.bin")

    resolution = resolve_manifest(cue)

    assert resolution.missing == []
    assert len(resolution.members) == 1


def test_resolve_cue_multi_track_finds_all_tracks(tmp_path):
    cue = tmp_path / "Game.cue"
    cue.write_text(
        'FILE "Game (Track 1).bin" BINARY\nFILE "Game (Track 2).bin" BINARY\n',
        encoding="utf-8",
    )
    _touch(tmp_path / "Game (Track 1).bin")
    _touch(tmp_path / "Game (Track 2).bin")

    resolution = resolve_manifest(cue)

    assert resolution.missing == []
    assert len(resolution.members) == 2


def test_resolve_cue_reports_missing_file(tmp_path):
    cue = tmp_path / "Game.cue"
    cue.write_text('FILE "Missing.bin" BINARY\n', encoding="utf-8")

    resolution = resolve_manifest(cue)

    assert resolution.members == []
    assert resolution.missing == ["Missing.bin"]


def test_resolve_m3u_lists_each_line_as_a_disc(tmp_path):
    m3u = tmp_path / "Game.m3u"
    m3u.write_text("Disc1.chd\nDisc2.chd\n", encoding="utf-8")
    _touch(tmp_path / "Disc1.chd")
    _touch(tmp_path / "Disc2.chd")

    resolution = resolve_manifest(m3u)

    assert resolution.missing == []
    assert {m.name for m in resolution.members} == {"Disc1.chd", "Disc2.chd"}


def test_resolve_m3u_ignores_blank_and_comment_lines(tmp_path):
    m3u = tmp_path / "Game.m3u"
    m3u.write_text("# comment\n\nDisc1.chd\n", encoding="utf-8")
    _touch(tmp_path / "Disc1.chd")

    resolution = resolve_manifest(m3u)

    assert [m.name for m in resolution.members] == ["Disc1.chd"]


def test_resolve_gdi_skips_track_count_line_and_reads_filenames(tmp_path):
    gdi = tmp_path / "Game.gdi"
    gdi.write_text("2\n1 0 4 2352 track01.bin 0\n2 600 4 2352 track02.raw 0\n", encoding="utf-8")
    _touch(tmp_path / "track01.bin")
    _touch(tmp_path / "track02.raw")

    resolution = resolve_manifest(gdi)

    assert resolution.missing == []
    assert {m.name for m in resolution.members} == {"track01.bin", "track02.raw"}


def test_resolve_gdi_handles_quoted_filenames_with_spaces(tmp_path):
    gdi = tmp_path / "Game.gdi"
    gdi.write_text('1\n1 0 4 2352 "track 01.bin" 0\n', encoding="utf-8")
    _touch(tmp_path / "track 01.bin")

    resolution = resolve_manifest(gdi)

    assert resolution.missing == []
    assert [m.name for m in resolution.members] == ["track 01.bin"]
