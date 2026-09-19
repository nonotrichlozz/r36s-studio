from __future__ import annotations

from r36s_studio.doublons.report import build_report
from r36s_studio.doublons.scan import find_duplicates


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_build_report_mentions_file_and_group_counts(tmp_path):
    _touch(tmp_path / "SNES" / "Game (USA).sfc", b"same")
    _touch(tmp_path / "SNES" / "Game (Europe).sfc", b"same")

    result = find_duplicates(str(tmp_path))
    report = build_report(result, str(tmp_path))

    assert "Fichiers analysés : 2" in report
    assert "Groupes de copies identiques : 1" in report
    assert "Game (USA).sfc" in report
    assert "Game (Europe).sfc" in report


def test_build_report_marks_the_suggested_version_to_keep(tmp_path):
    _touch(tmp_path / "SNES" / "Game (USA).sfc", b"a" * 5)
    _touch(tmp_path / "SNES" / "Game (France).sfc", b"b" * 5)

    result = find_duplicates(str(tmp_path))
    report = build_report(result, str(tmp_path))

    suggested_line = next(line for line in report.splitlines() if "Game (France).sfc" in line)
    assert "(suggérée)" in suggested_line
    other_line = next(line for line in report.splitlines() if "Game (USA).sfc" in line)
    assert "(suggérée)" not in other_line


def test_build_report_lists_excluded_groups(tmp_path):
    cue = tmp_path / "Game.cue"
    cue.write_text('FILE "Missing.bin" BINARY\n', encoding="utf-8")

    result = find_duplicates(str(tmp_path))
    report = build_report(result, str(tmp_path))

    assert "Groupes exclus" in report
    assert "Missing.bin" in report
