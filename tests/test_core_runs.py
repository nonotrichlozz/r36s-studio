"""Modules sans Qt extraits des threads de la GUI (`doublons/run.py`,
`tri/run.py`, `identify/firmware_download.py`) : mêmes codes d'erreur et
même politique qu'avant, appelés tels quels par la GUI et le bot."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from r36s_studio.doublons.move import DestinationNotWritable, MoveFileFailed
from r36s_studio.doublons.run import (
    AUTO_SKIP_AFTER,
    default_units_to_move,
    preferred_destination,
    prune_moved,
    run_move,
    run_scan,
)
from r36s_studio.doublons.scan import ExactDuplicateGroup, ScanResult, Unit, VersionGroup
from r36s_studio.identify import firmware_download
from r36s_studio.identify.rocknix import ChecksumMismatchError, RocknixAsset
from r36s_studio.tri.plan import SortRootRefused, TooManyFiles
from r36s_studio.tri.run import run_apply, run_plan


def _unit(name, size=10):
    return Unit(Path(name), [Path(name)], size, False)


def _result():
    a, b, c = _unit("a.sfc"), _unit("a copie.sfc"), _unit("a bis.sfc")
    v1, v2 = _unit("Zelda (Europe).sfc"), _unit("Zelda (USA).sfc")
    return ScanResult(
        exact_duplicate_groups=[ExactDuplicateGroup([a, b, c], "f" * 64)],
        version_groups=[VersionGroup("snes", "zelda", [v1, v2], suggested_keep=v2)],
        files_scanned=5,
    ), (a, b, c, v1, v2)


def test_default_selection_keeps_one_copy_and_the_suggested_version():
    result, (a, b, c, v1, v2) = _result()
    assert default_units_to_move(result) == [b, c, v1]


def test_prune_drops_groups_left_with_a_single_copy():
    result, (a, b, c, v1, v2) = _result()
    pruned = prune_moved(result, [b, v1])
    assert [g.units for g in pruned.exact_duplicate_groups] == [[a, c]]
    assert pruned.version_groups == [] and pruned.files_scanned == 5


def test_preferred_destination_falls_back_when_remembered_is_inside_root(tmp_path):
    root = tmp_path / "jeux"
    root.mkdir()
    assert preferred_destination(str(root), str(root / "dedans")) == str(root.resolve() / "_doublons")
    elsewhere = tmp_path / "ailleurs"
    elsewhere.mkdir()
    assert preferred_destination(str(root), str(elsewhere)) == str(elsewhere)


def test_scan_errors_become_codes(tmp_path):
    with patch("r36s_studio.doublons.run.find_duplicates", side_effect=OSError("illisible")):
        outcome = run_scan(str(tmp_path), [], {})
    assert outcome.error_code == "DOUBLONS_IO_ERROR" and outcome.error_detail == "illisible"


def test_move_asks_then_stops_asking_after_identical_skipped_failures():
    asked = []

    def fake_move(root, units, dry_run, on_progress, should_cancel, destination, on_file_error):
        results = [on_file_error(MoveFileFailed(f"f{i}", "move", "source_missing", "absent")) for i in range(6)]
        assert all(results)

    with patch("r36s_studio.doublons.run.move_duplicates", fake_move):
        outcome = run_move("/racine", [], False, ask_file_error=lambda exc: (asked.append(exc) or (True, False)))
    assert outcome.ok and len(asked) == AUTO_SKIP_AFTER


def test_move_refusal_maps_to_the_same_code_as_before():
    with patch("r36s_studio.doublons.run.move_duplicates", side_effect=DestinationNotWritable("lecture seule")):
        outcome = run_move("/racine", [], False)
    assert (outcome.ok, outcome.error_code, outcome.moved_units) == (False, "DESTINATION_NOT_WRITABLE", [])


def test_tri_plan_and_apply_errors_become_codes():
    def refused(**_kwargs):
        raise SortRootRefused("/", "filesystem_root")

    def too_many(**_kwargs):
        raise TooManyFiles("trop")

    assert run_plan(refused).error_code == "ROOT_FILESYSTEM_ROOT"
    assert run_plan(too_many).error_code == "TOO_MANY_FILES"

    def no_space(plan, **_kwargs):
        from r36s_studio.doublons.move import InsufficientDiskSpace

        raise InsufficientDiskSpace("/carte", 100, 10)

    assert run_apply(object(), apply=no_space).error_code == "NO_SPACE"


def test_download_firmware_outcomes_and_final_progress(tmp_path):
    asset = RocknixAsset("img.gz", "https://github.com/x/img.gz", 8)
    events = []

    def fake_download(asset, destination, expected_sha256, on_progress, should_cancel, transform):
        on_progress(4, 8)
        on_progress(8, 8)

    with patch("r36s_studio.identify.rocknix.download_asset", fake_download):
        outcome = firmware_download.download_firmware(asset, on_progress=lambda *v: events.append(v), destination_dir=tmp_path)
    assert outcome.path == tmp_path / "img.gz"
    assert events[-1][:2] == (8, 8)  # le compte final exact toujours émis

    with patch("r36s_studio.identify.rocknix.download_asset", side_effect=ChecksumMismatchError("faux")):
        outcome = firmware_download.download_firmware(asset, destination_dir=tmp_path)
    assert not outcome.ok and outcome.error_code == "ROCKNIX_CHECKSUM_MISMATCH"
