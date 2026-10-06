"""Tests de l'écran « Ranger mes jeux » (`gui/tri_screen.py`,
docs/tri-roms.md) : aperçu avant action, confirmation jamais sautée,
annulation du rangement."""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import QCoreApplication

from r36s_studio.gui.main_window import MainWindow
from r36s_studio.gui.tri_screen import TriScreen
from r36s_studio.tri.apply import ApplyResult, apply_plan
from r36s_studio.tri.plan import build_plan

from . import tri_fixtures as fx


def _wait(runner) -> None:
    runner.wait(10_000)
    for _ in range(5):
        QCoreApplication.processEvents()


def _top_level_texts(screen: TriScreen):
    tree = screen._preview_tree
    return [tree.topLevelItem(index).text(0) for index in range(tree.topLevelItemCount())]


def test_default_firmware_follows_the_flash_choice_when_it_has_a_table(qapp):
    screen = TriScreen()
    screen.set_default_firmware("emuelec")
    assert screen.selected_firmware() == "emuelec"


def test_default_firmware_falls_back_to_rocknix_without_a_table(qapp):
    screen = TriScreen()
    screen.set_default_firmware("minui")
    assert screen.selected_firmware() == "rocknix"


def test_verification_status_is_shown_for_the_selected_firmware(qapp):
    screen = TriScreen()
    screen.set_default_firmware("rocknix")
    assert "pas encore vérifiés" in screen._verification_label.text()
    screen.set_default_firmware("treefrogui")
    assert "vérifiés sur une vraie carte" in screen._verification_label.text()


def test_preview_lists_each_destination_folder_and_set_aside_files(qapp, tmp_path):
    fx.write(tmp_path / "Mario.sfc", fx.raw())
    fx.write(tmp_path / "Zelda.gba", fx.gba())
    fx.write(tmp_path / "mystere.bin", fx.raw())
    screen = TriScreen()

    screen.show_preview(build_plan(str(tmp_path), "rocknix"))

    texts = _top_level_texts(screen)
    assert texts[0].startswith("gba — 1 jeu(x)")
    assert texts[1].startswith("snes — 1 jeu(x)")
    assert texts[2].startswith("_non_identifies — 1")
    assert screen.current_page() == TriScreen.PAGE_PREVIEW
    assert screen._sort_button.isEnabled()
    assert screen._case_warning_frame.isHidden()


def test_preview_warns_about_a_differently_cased_folder(qapp, tmp_path):
    fx.write(tmp_path / "SNES/Deja.sfc", fx.raw())
    fx.write(tmp_path / "Nouveau.sfc", fx.raw())
    screen = TriScreen()

    screen.show_preview(build_plan(str(tmp_path), "rocknix"))

    assert not screen._case_warning_frame.isHidden()
    assert "« SNES »" in screen._case_warning_label.text()
    assert any(text.startswith("Laissés à leur place") for text in _top_level_texts(screen))


def test_nothing_to_sort_disables_the_sort_button(qapp, tmp_path):
    fx.write(tmp_path / "snes/Deja.sfc", fx.raw())
    screen = TriScreen()

    screen.show_preview(build_plan(str(tmp_path), "rocknix"))

    assert not screen._sort_button.isEnabled()


def test_sort_button_goes_through_the_confirmation_page(qapp, tmp_path):
    fx.write(tmp_path / "Mario.sfc", fx.raw())
    screen = TriScreen()
    screen.show_preview(build_plan(str(tmp_path), "rocknix"))

    screen._sort_button.click()

    assert screen.current_page() == TriScreen.PAGE_CONFIRM
    # Rien n'a bougé tant que la confirmation n'est pas donnée.
    assert (tmp_path / "Mario.sfc").exists()


def test_full_flow_scan_confirm_move_then_undo(qapp, tmp_path):
    fx.write(tmp_path / "Mario.sfc", fx.raw())
    fx.write(tmp_path / "Zelda.gba", fx.gba())
    screen = TriScreen()
    screen.set_default_firmware("rocknix")

    screen.start_scan(str(tmp_path))
    _wait(screen._plan_runner)
    assert screen.current_page() == TriScreen.PAGE_PREVIEW

    screen._sort_button.click()
    screen._confirm_button.click()
    _wait(screen._apply_runner)

    assert screen.current_page() == TriScreen.PAGE_RESULT
    assert (tmp_path / "snes/Mario.sfc").exists()
    assert (tmp_path / "gba/Zelda.gba").exists()
    assert "2 fichier(s) déplacé(s)" in screen._result_label.text()
    assert not screen._undo_button.isHidden()

    screen._undo_button.click()
    _wait(screen._undo_runner)

    assert (tmp_path / "Mario.sfc").exists()
    assert (tmp_path / "Zelda.gba").exists()
    assert "2 fichier(s) remis à leur place" in screen._result_label.text()


def test_previous_sort_can_be_undone_from_the_preview(qapp, tmp_path):
    fx.write(tmp_path / "Mario.sfc", fx.raw())
    apply_plan(build_plan(str(tmp_path), "rocknix"))
    fx.write(tmp_path / "Autre.sfc", fx.raw())
    screen = TriScreen()

    screen.show_preview(build_plan(str(tmp_path), "rocknix"))

    assert not screen._undo_previous_button.isHidden()


def test_refused_folder_shows_a_message_on_the_choose_page(qapp, tmp_path):
    root = tmp_path / "snes"
    fx.write(root / "Jeu.sfc", fx.raw())
    screen = TriScreen()
    screen.set_default_firmware("rocknix")

    screen.start_scan(str(root))
    _wait(screen._plan_runner)

    assert screen.current_page() == TriScreen.PAGE_CHOOSE
    assert not screen._choose_error_frame.isHidden()
    assert "nom d'une console" in screen._choose_error_label.text()


def test_interrupted_result_is_titled_as_such(qapp, tmp_path):
    screen = TriScreen()
    screen._root = str(tmp_path)
    screen.show_apply_result(ApplyResult(moved_files=3, aborted=True))
    assert screen._result_title.text() == "Rangement interrompu"


@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_sort_row_of_expert_home_opens_the_tri_screen_and_back_returns_home(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._app_config.firmware = "emuelec"

    window._home.sort_games_requested.emit()

    assert window._root_stack.currentWidget() is window._tri_screen
    assert window._tri_screen.selected_firmware() == "emuelec"

    window._tri_screen.back_requested.emit()
    assert window._root_stack.currentWidget() is not window._tri_screen


def test_destination_and_filter_choices_reach_the_scan_and_the_preview(qapp, tmp_path):
    """Destination libre + filtre région/langue, de bout en bout : aperçu
    avec le nombre par catégorie, confirmation qui nomme la destination,
    puis rangement réel."""
    source, destination = tmp_path / "telechargements", tmp_path / "bibliotheque"
    fx.write(source / "Sonic (Europe).md", fx.megadrive())
    fx.write(source / "Streets (Japan).md", fx.megadrive())
    fx.write(source / "Pong homebrew.gba", fx.gba())
    screen = TriScreen()
    screen.set_default_firmware("rocknix")
    screen.set_destination(str(destination))
    screen._region_checks["Europe"].setChecked(True)

    screen.start_scan(str(source))
    _wait(screen._plan_runner)

    summary = screen._preview_summary_label.text()
    assert "1 jeu(x) mis de côté par le filtre" in summary
    assert "1 jeu(x) sans région dans leur nom" in summary
    assert str(destination.resolve()) in summary
    groups = _top_level_texts(screen)
    assert "_hors_filtre — 1 jeu(x) mis de côté (région ou langue)" in groups
    assert "Sans région dans le nom, gardés — 1 jeu(x)" in groups

    screen._sort_button.click()
    assert str(destination.resolve()) in screen._confirm_message_label.text()
    screen._confirm_button.click()
    _wait(screen._apply_runner)

    assert (destination / "megadrive/Sonic (Europe).md").exists()
    assert (destination / "gba/Pong homebrew.gba").exists()
    assert (source / "_hors_filtre/Streets (Japan).md").exists()


def test_sort_in_place_resets_the_destination(qapp):
    screen = TriScreen()
    screen.set_destination("/somewhere")
    assert not screen._destination_reset_button.isHidden()

    screen._destination_reset_button.click()

    assert screen._destination is None
    assert screen._destination_reset_button.isHidden()
