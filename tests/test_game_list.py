"""Liste de jeux composable (`tri/selection.py`, `gui/game_list_widget.py`)
et son aperçu de copie KNULLI (`android/knulli.py::build_copy_plan_from`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from r36s_studio import config
from r36s_studio.android import knulli
from r36s_studio.gui.game_list_widget import GameListWidget
from r36s_studio.tri.selection import GameSelection

SYSTEMS = knulli.parse_es_systems(
    """<systemList>
<system><path>/userdata/roms/psx</path><extension>.cue .chd .m3u</extension></system>
<system><path>/userdata/roms/snes</path><extension>.sfc .zip</extension></system>
<system><path>/userdata/roms/gba</path><extension>.gba .zip</extension></system>
</systemList>"""
)


def _write(path: Path, size=100, text=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        path.write_bytes(b"\x00" * size)
    else:
        path.write_text(text)
    return path


def _disc(folder: Path, name="Game", with_bin=True) -> Path:
    cue = _write(folder / f"{name}.cue", text=f'FILE "{name}.bin" BINARY\n')
    if with_bin:
        _write(folder / f"{name}.bin", 5000)
    return cue


def test_multiple_files_and_duplicates_are_merged(tmp_path):
    a = _write(tmp_path / "Downloads" / "A.sfc")
    b = _write(tmp_path / "Downloads" / "B.sfc")
    selection = GameSelection()

    assert selection.add_files([str(a), str(b)]) == 2
    assert selection.add_files([str(a)]) == 0  # même fichier : fusionné
    assert selection.add_folder(str(tmp_path / "Downloads")) == 0  # déjà là par le dossier aussi
    assert [p.name for p in selection.files()] == ["A.sfc", "B.sfc"]


def test_a_folder_brings_its_subfolders_and_several_folders_mix(tmp_path):
    _write(tmp_path / "Jeux1" / "snes" / "sub" / "A.sfc")
    _write(tmp_path / "Jeux2" / "gba" / "B.gba", 300)
    selection = GameSelection()
    selection.add_folder(str(tmp_path / "Jeux1"))
    selection.add_paths([str(tmp_path / "Jeux2")])

    plan = knulli.build_copy_plan_from(selection.entries(), SYSTEMS)

    assert sorted(i.remote for i in plan.items) == ["/userdata/roms/gba/B.gba", "/userdata/roms/snes/sub/A.sfc"]
    assert plan.by_folder() == {"gba": (1, 300), "snes": (1, 100)}  # résumé sur toute la liste


def test_choosing_a_cue_or_its_bin_brings_the_whole_game(tmp_path):
    cue = _disc(tmp_path / "psx")
    selection = GameSelection()
    selection.add_files([str(tmp_path / "psx" / "Game.bin")])  # le .bin seul : son .cue vient avec
    assert sorted(p.name for p in selection.files()) == ["Game.bin", "Game.cue"]
    assert [[p.name for p in g] for g in selection.groups()] == [["Game.cue", "Game.bin"]]

    selection.clear()
    m3u = _write(tmp_path / "psx" / "Game.m3u", text="Game.cue\n")
    selection.add_files([str(m3u)])  # en chaîne : .m3u -> .cue -> .bin
    assert sorted(p.name for p in selection.files()) == ["Game.bin", "Game.cue", "Game.m3u"]

    selection.remove(cue.resolve())  # une ligne retirée : tout le jeu part
    assert len(selection) == 0


def test_a_cue_without_its_bin_is_reported_never_copied(tmp_path):
    cue = _disc(tmp_path / "psx", "Lost", with_bin=False)
    selection = GameSelection()
    selection.add_files([str(cue)])

    plan = knulli.build_copy_plan_from(selection.entries(), SYSTEMS)

    assert plan.items == [] and [(s.reason, s.detail) for s in plan.skipped] == [("disc_missing_files", "Lost.bin")]


def test_widget_drop_remove_and_last_folder(qapp, tmp_path):
    a = _write(tmp_path / "snes" / "A.sfc")
    _write(tmp_path / "gba" / "B.gba")
    widget = GameListWidget()
    widget.set_describer(lambda selection: {path: "snes" for path in selection.files()})
    folders = []
    widget.folder_used.connect(folders.append)

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(a)), QUrl.fromLocalFile(str(tmp_path / "gba"))])
    event = QDropEvent(QPointF(5, 5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    widget.dropEvent(event)

    tree = widget._tree
    assert tree.topLevelItemCount() == 2 and tree.topLevelItem(0).text(2) == "snes"
    assert folders == [str(a.parent)]  # dossier de départ du prochain sélecteur
    tree.topLevelItem(0).setSelected(True)
    widget.remove_selected()
    assert [p.name for p in widget.selection().files()] == ["B.gba"]
    widget.clear()
    assert len(widget.selection()) == 0 and not widget._clear_button.isEnabled()


def test_add_files_dialog_takes_several_files_from_the_last_folder(qapp, tmp_path):
    a, b = _write(tmp_path / "A.sfc"), _write(tmp_path / "B.sfc")
    widget = GameListWidget()
    widget.set_start_folder(str(tmp_path))
    with patch(
        "r36s_studio.gui.game_list_widget.QFileDialog.getOpenFileNames", return_value=([str(a), str(b)], "")
    ) as dialog:
        widget._on_add_files_clicked()
    assert dialog.call_args.args[2] == str(tmp_path)
    assert widget._tree.topLevelItemCount() == 2


def test_last_games_folder_is_kept_in_config(tmp_path):
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(config.AppConfig(last_games_folder="D:/Jeux"))
        assert config.load_config().last_games_folder == "D:/Jeux"
        path.write_text(json.dumps({"last_games_folder": 3}), encoding="utf-8")
        assert config.load_config().last_games_folder == ""
