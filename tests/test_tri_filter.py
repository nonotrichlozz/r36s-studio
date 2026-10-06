"""Tests de `tri/filter.py` -- « Filtrer par région et par langue », fonction
distincte du tri (docs/tri-roms.md) : n'importe quel dossier, rien n'est
réorganisé, seuls les jeux hors critères partent dans `_hors_filtre`."""

from __future__ import annotations

import pytest

from r36s_studio.tri.apply import apply_plan, has_journal, undo_sort
from r36s_studio.tri.filter import build_filter_plan
from r36s_studio.tri.plan import FILTER_JOURNAL_FILENAME, SORT_JOURNAL_FILENAME, SortRootRefused, build_plan
from r36s_studio.tri.regions import RegionFilter

from . import tri_fixtures as fx

EUROPE = RegionFilter(regions=frozenset({"Europe"}))
EUROPE_FRENCH = RegionFilter(regions=frozenset({"Europe"}), languages=frozenset({"Fr"}))


def _names(moves):
    return sorted(member.name for move in moves for member in move.members)


def _all_files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def test_a_single_console_folder_named_like_a_system_is_accepted(tmp_path):
    """Cas constaté : un dossier « SNES » refusé par le tri parce qu'il porte
    un nom de console -- le filtre, lui, ne crée aucun dossier de système."""
    snes = tmp_path / "SNES"
    fx.write(snes / "Mario (Europe).sfc", fx.raw())
    fx.write(snes / "Mario (Japan).sfc", fx.raw())

    plan = build_filter_plan(str(snes), EUROPE)

    assert _names(plan.filtered_out) == ["Mario (Japan).sfc"]
    assert plan.kept_count == 1
    assert plan.moves == [] and plan.unidentified == []


def test_whole_collection_walks_every_console_subfolder(tmp_path):
    fx.write(tmp_path / "snes/Mario (Japan).sfc", fx.raw())
    fx.write(tmp_path / "megadrive/Sonic (USA, Europe).md", fx.megadrive())
    fx.write(tmp_path / "gba/Zelda (USA) (En,Fr).gba", fx.gba())

    plan = build_filter_plan(str(tmp_path), EUROPE_FRENCH)

    assert [(m.members[0].name, m.detail, m.reason) for m in plan.filtered_out] == [
        ("Mario (Japan).sfc", "snes", "region_excluded")
    ]
    assert plan.kept_count == 2


def test_names_without_region_are_kept_and_listed_and_non_game_files_ignored(tmp_path):
    fx.write(tmp_path / "gba/Pong homebrew.gba", fx.gba())
    fx.write(tmp_path / "gba/images/Pong homebrew.png", b"png")
    fx.write(tmp_path / "gba/filelist.csv", b"csv")

    plan = build_filter_plan(str(tmp_path), EUROPE)

    assert _names(plan.no_region) == ["Pong homebrew.gba"]
    assert plan.filtered_out == [] and plan.kept_count == 1


def test_disc_image_group_moves_together_judged_on_its_cue(tmp_path):
    fx.write(tmp_path / "psx/Jeu (Japan).cue", b'FILE "Jeu (Japan) (Track 1).bin" BINARY\n')
    fx.write(tmp_path / "psx/Jeu (Japan) (Track 1).bin", fx.cd_bin())

    plan = build_filter_plan(str(tmp_path), EUROPE)

    assert [_names([move]) for move in plan.filtered_out] == [["Jeu (Japan) (Track 1).bin", "Jeu (Japan).cue"]]


def test_filesystem_root_without_any_card_is_refused(monkeypatch):
    import os

    monkeypatch.setattr("r36s_studio.tri.filter.list_devices", lambda: [])

    with pytest.raises(SortRootRefused):
        build_filter_plan(os.path.abspath(os.sep), EUROPE)


def test_apply_and_undo_use_their_own_journal_independent_from_sorting(tmp_path):
    fx.write(tmp_path / "Mario (Europe).sfc", fx.raw())
    apply_plan(build_plan(str(tmp_path), "rocknix"))  # rangement d'abord
    fx.write(tmp_path / "snes/Mario (Japan).sfc", fx.raw())
    sorted_state = _all_files(tmp_path)

    plan = build_filter_plan(str(tmp_path), EUROPE)
    result = apply_plan(plan, journal_name=FILTER_JOURNAL_FILENAME)

    assert result.moved_files == 1
    assert "_hors_filtre/snes/Mario (Japan).sfc" in _all_files(tmp_path)
    assert has_journal(str(tmp_path), FILTER_JOURNAL_FILENAME)

    undo = undo_sort(str(tmp_path), FILTER_JOURNAL_FILENAME)

    # Annuler le filtrage ne défait pas le rangement d'avant.
    assert undo.restored == 1
    assert _all_files(tmp_path) == sorted_state
    assert has_journal(str(tmp_path), SORT_JOURNAL_FILENAME)


# --- racine d'un lecteur : seulement une carte retenue par safety (§4.2) ------


def _device(mountpoint, **overrides):
    from r36s_studio.devices import Device

    values = dict(
        path="/dev/fake-disk-test-9", display="Lecteur SD factice", size_bytes=64 * 1024**3,
        removable=True, bus="USB", is_system=False, mountpoints=[mountpoint],
    )
    values.update(overrides)
    return Device(**values)


def _as_drive_root(monkeypatch, devices, partitions=()):
    """`tmp_path` joue la racine d'un lecteur : la vraie détection est
    remplacée, le vrai filtre `safety` décide."""
    monkeypatch.setattr("r36s_studio.tri.filter.os.path.ismount", lambda path: True)
    monkeypatch.setattr("r36s_studio.tri.filter.is_filesystem_root", lambda path: True)
    monkeypatch.setattr("r36s_studio.tri.filter.list_devices", lambda: devices)
    monkeypatch.setattr("r36s_studio.tri.filter.list_partitions", lambda path: list(partitions))


def test_root_of_a_card_kept_by_safety_is_accepted_and_named(tmp_path, monkeypatch):
    from r36s_studio.partitions.locate import PartitionInfo

    fx.write(tmp_path / "snes/Mario (Japan).sfc", fx.raw())
    fx.write(tmp_path / "snes/Mario (Europe).sfc", fx.raw())
    _as_drive_root(monkeypatch, [_device(str(tmp_path))], [PartitionInfo("x", "EASYROMS", "exfat", str(tmp_path))])

    plan = build_filter_plan(str(tmp_path), EUROPE)

    assert plan.card_volume == f"EASYROMS ({str(tmp_path).rstrip(chr(92) + '/')})"
    assert plan.card_volume_bytes and plan.card_volume_bytes > 0  # taille du volume, affichée à côté du nom
    assert _names(plan.filtered_out) == ["Mario (Japan).sfc"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_system": True},  # disque système
        {"size_bytes": 4 * 1024**4},  # gros disque externe, au-dessus du seuil de 1 To
        {"removable": False, "bus": "NVMe"},  # disque interne
    ],
)
def test_root_of_a_drive_refused_by_safety_stays_refused(tmp_path, monkeypatch, overrides):
    fx.write(tmp_path / "snes/Mario (Japan).sfc", fx.raw())
    _as_drive_root(monkeypatch, [_device(str(tmp_path), **overrides)])

    with pytest.raises(SortRootRefused) as excinfo:
        build_filter_plan(str(tmp_path), EUROPE)
    assert excinfo.value.reason == "filesystem_root"


def test_drive_root_refused_when_device_detection_fails(tmp_path, monkeypatch):
    _as_drive_root(monkeypatch, [])

    def broken():
        raise OSError("PowerShell indisponible")

    monkeypatch.setattr("r36s_studio.tri.filter.list_devices", broken)

    with pytest.raises(SortRootRefused):
        build_filter_plan(str(tmp_path), EUROPE)
