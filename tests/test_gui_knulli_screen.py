"""Écran « Copier des jeux sur ma console (USB) » (`gui/knulli_screen.py`) et
son entrée depuis l'écran Console Android -- aucun thread réel lancé pour la
copie (runner remplacé), aucune commande adb."""

from __future__ import annotations

from pathlib import Path

from r36s_studio.android.knulli import CopyItem, CopyPlan, CopyResult, SPACE_MARGIN_BYTES
from r36s_studio.android.models import AndroidDeviceInfo, DetectionResult, LinuxConsole
from r36s_studio.gui import knulli_screen
from r36s_studio.gui.knulli_screen import KnulliCopyScreen
from r36s_studio.gui.screens import AndroidScreen
from r36s_studio.gui.strings import tr

CONSOLE = LinuxConsole("knulli", "20260511")


def _item(name, size=1000, existing=None):
    return CopyItem(Path(name), f"/userdata/roms/snes/{name}", "snes", size, existing_size=existing)


def _screen(plan):
    screen = KnulliCopyScreen()
    screen.start("adb", "S", CONSOLE)
    screen._show_summary(plan)
    return screen


def test_android_screen_offers_the_copy_for_a_knulli_console(qapp):
    screen = AndroidScreen()
    unknown = AndroidDeviceInfo("0123456789", *["inconnu"] * 5)
    screen.show_detection_result(DetectionResult(state="ready", device=unknown, linux_console=CONSOLE))
    assert not screen._knulli_frame.isHidden() and screen._device_frame.isHidden()
    assert "20260511" in screen._knulli_body_label.text()
    emitted = []
    screen.knulli_copy_requested.connect(lambda: emitted.append(True))
    screen._knulli_frame.findChildren(type(screen._catalog_search_button))[0].click()
    assert emitted == [True]


def test_summary_refuses_clearly_when_it_does_not_fit(qapp):
    plan = CopyPlan(Path("x"), items=[_item("A.sfc", 2000)], free_bytes=SPACE_MARGIN_BYTES + 1000)
    screen = _screen(plan)
    assert not screen._space_frame.isHidden() and not screen._copy_button.isEnabled()
    assert screen._folders_list.item(0).text().startswith("snes")


def test_conflicts_are_asked_and_skip_all_skips_the_rest(qapp, monkeypatch):
    started = []

    class FakeRunner:
        def __init__(self, adb_path, serial, plan, parent=None):
            started.append(plan)
            self.progress = self.finished_copy = self.not_enough_space = self.error = self.finished = self

        def deleteLater(self):
            pass

        def connect(self, slot):
            pass

        def start(self):
            pass

    monkeypatch.setattr(knulli_screen, "KnulliCopyRunner", FakeRunner)
    plan = CopyPlan(
        Path("x"),
        items=[_item("New.sfc"), _item("A.sfc", existing=5), _item("B.sfc", existing=5), _item("C.sfc", existing=5)],
        free_bytes=10**12,
    )
    screen = _screen(plan)
    answers = iter(["replace", "skip_all"])
    asked = []
    monkeypatch.setattr(screen, "_ask_conflict", lambda item: asked.append(item.local.name) or next(answers))

    screen._on_copy_clicked()

    assert asked == ["A.sfc", "B.sfc"]  # C.sfc ignoré sans question après « Tout ignorer »
    assert [(i.local.name, i.replace) for i in started[0].items] == [("New.sfc", False), ("A.sfc", True)]
    assert sorted(s.local.name for s in plan.skipped) == ["B.sfc", "C.sfc"]


def test_result_says_when_the_list_was_not_refreshed_because_a_game_runs(qapp):
    screen = _screen(CopyPlan(Path("x"), items=[_item("A.sfc")], free_bytes=10**12))
    item = _item("B.sfc")
    screen._show_result(CopyResult(copied=[_item("A.sfc")], failures=[(item, "size_mismatch")]), "game_running")
    assert screen._reload_label.text() == tr("knulli_reload_game_running")
    assert "B.sfc" in screen._failures_list.item(0).text()
