"""Tests des écrans de l'assistant (gui/screens.py) — construction et
logique des signaux, en mode Qt "offscreen" (fixture `qapp`)."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.gui.screens import (
    ConfirmScreen,
    DeviceScreen,
    ExecuteScreen,
    FileScreen,
    HomeScreen,
    ResultScreen,
    _format_duration,
    format_archive_label,
)


def _make_device(path="/dev/fake-disk-test-3", size_bytes=32_000_000_000, display="Carte SD factice") -> Device:
    return Device(
        path=path,
        display=display,
        size_bytes=size_bytes,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


# --- HomeScreen --------------------------------------------------------


def test_home_screen_backup_tile_emits_signal(qapp):
    screen = HomeScreen()
    received = []
    screen.backup_selected.connect(lambda: received.append(True))

    screen.backup_selected.emit()

    assert received == [True]


def test_home_screen_all_six_steps_emit_their_signal(qapp):
    screen = HomeScreen()
    signals = {
        "extract_boot": screen.extract_boot_selected,
        "extract_easyroms": screen.extract_easyroms_selected,
        "flash": screen.flash_selected,
        "inject_boot": screen.inject_boot_selected,
        "copy_games": screen.copy_games_selected,
        "eject": screen.eject_selected,
    }
    received = []
    for key, signal in signals.items():
        signal.connect(lambda key=key: received.append(key))

    for signal in signals.values():
        signal.emit()

    assert received == list(signals)


def test_home_screen_all_six_tiles_always_visible_and_enabled_regardless_of_status(qapp):
    """Coeur de la correction de conception : plus de tuile unique mise en
    avant, plus de section « Autres opérations » -- les six étapes restent
    toujours visibles et cliquables, quel que soit leur statut (§4.5)."""
    screen = HomeScreen()
    screen.show()

    status = {
        "extract_boot": StepStatus.NOT_RELEVANT,
        "extract_easyroms": StepStatus.NOT_RELEVANT,
        "flash": StepStatus.AVAILABLE,
        "inject_boot": StepStatus.NOT_RELEVANT,
        "copy_games": StepStatus.NOT_RELEVANT,
        "eject": StepStatus.NOT_RELEVANT,
    }
    screen.set_status(status)

    for tile in screen._tiles.values():
        assert tile.isVisible() is True
        assert tile.isEnabled() is True


def test_home_screen_empty_status_keeps_base_text_without_badge(qapp):
    screen = HomeScreen()

    screen.set_status({})

    for key, tile in screen._tiles.items():
        assert tile.text() == screen._base_texts[key]


def test_home_screen_status_appends_badge_text_to_each_tile(qapp):
    screen = HomeScreen()

    screen.set_status(
        {
            "extract_boot": StepStatus.AVAILABLE,
            "extract_easyroms": StepStatus.DONE,
            "flash": StepStatus.DONE,
            "inject_boot": StepStatus.AVAILABLE,
            "copy_games": StepStatus.AVAILABLE,
            "eject": StepStatus.NOT_RELEVANT,
        }
    )

    assert "Faisable" in screen._tiles["extract_boot"].text()
    assert "Déjà faite" in screen._tiles["extract_easyroms"].text()
    assert "Déjà faite" in screen._tiles["flash"].text()
    assert "Non pertinente" in screen._tiles["eject"].text()


def test_home_screen_steps_appear_in_fixed_chronological_order(qapp):
    screen = HomeScreen()

    assert list(screen._tiles) == [
        "extract_boot",
        "extract_easyroms",
        "flash",
        "inject_boot",
        "copy_games",
        "eject",
    ]


def test_home_screen_refresh_button_emits_signal(qapp):
    screen = HomeScreen()
    received = []
    screen.refresh_requested.connect(lambda: received.append(True))

    screen._refresh_button.click()

    assert received == [True]


# --- DeviceScreen --------------------------------------------------------


def test_device_screen_no_default_selection(qapp):
    screen = DeviceScreen()
    screen.set_devices([_make_device()])

    assert screen._list.selectedItems() == []
    assert screen._next_button.isEnabled() is False


def test_device_screen_selecting_enables_next_and_emits_correct_device(qapp):
    screen = DeviceScreen()
    device_a = _make_device(path="/dev/fake-disk-test-3", display="A")
    device_b = _make_device(path="/dev/fake-disk-test-4", display="B")
    screen.set_devices([device_a, device_b])

    screen._list.setCurrentRow(1)
    assert screen._next_button.isEnabled() is True

    chosen = []
    screen.device_chosen.connect(lambda d: chosen.append(d))
    screen._emit_chosen()

    assert chosen == [device_b]


def test_device_screen_empty_list_shows_empty_message(qapp):
    screen = DeviceScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois le parent affiché
    screen.set_devices([])

    assert screen._empty_label.isVisible() is True
    assert screen._list.isVisible() is False


# --- FileScreen ----------------------------------------------------------


def test_file_screen_set_mode_resets_state(qapp):
    screen = FileScreen()
    screen.set_mode("flash")
    assert screen._next_button.isEnabled() is False
    assert screen._path_label.text() == ""


@patch("r36s_studio.gui.screens.QFileDialog.getSaveFileName", return_value=("/tmp/out.img", ""))
def test_file_screen_backup_browse_enables_next(mock_dialog, qapp):
    screen = FileScreen()
    screen.set_mode("backup")

    screen._browse()

    assert screen._path_label.text() == "/tmp/out.img"
    assert screen._next_button.isEnabled() is True


@patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("", ""))
def test_file_screen_cancelled_dialog_does_not_enable_next(mock_dialog, qapp):
    screen = FileScreen()
    screen.set_mode("flash")

    screen._browse()

    assert screen._next_button.isEnabled() is False


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/boot_backup")
def test_file_screen_inject_boot_browse_picks_a_folder(mock_dialog, qapp):
    """inject-boot/copy-games consomment un dossier (§4.4), pas un fichier
    unique -- le sélecteur doit être un choix de dossier."""
    screen = FileScreen()
    screen.set_mode("inject_boot")

    screen._browse()

    mock_dialog.assert_called_once()
    assert screen._path_label.text() == "/tmp/boot_backup"
    assert screen._next_button.isEnabled() is True


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/games")
def test_file_screen_copy_games_browse_picks_a_folder(mock_dialog, qapp):
    screen = FileScreen()
    screen.set_mode("copy_games")

    screen._browse()

    assert screen._path_label.text() == "/tmp/games"


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="")
def test_file_screen_cancelled_folder_dialog_does_not_enable_next(mock_dialog, qapp):
    screen = FileScreen()
    screen.set_mode("copy_games")

    screen._browse()

    assert screen._next_button.isEnabled() is False


# --- FileScreen : liste des archives existantes (étapes D/E, §4.4) --------


def test_file_screen_archive_mode_lists_existing_archives(qapp):
    screen = FileScreen()
    screen.show()
    screen.set_mode("inject_boot", archive_choices=["/tmp/R36S Studio/BOOT_2026-07-06_00-21"])

    assert screen._archive_list.isVisible() is True
    assert screen._archive_list.count() == 1
    assert screen._archive_empty_label.isVisible() is False


def test_file_screen_archive_mode_with_no_archives_shows_empty_message(qapp):
    screen = FileScreen()
    screen.show()
    screen.set_mode("copy_games", archive_choices=[])

    assert screen._archive_list.count() == 0
    assert screen._archive_empty_label.isVisible() is True


def test_file_screen_non_archive_mode_hides_archive_list(qapp):
    screen = FileScreen()
    screen.set_mode("flash")

    assert screen._archive_list.isVisible() is False
    assert screen._archive_empty_label.isVisible() is False


def test_file_screen_selecting_an_archive_enables_next_and_sets_path(qapp):
    screen = FileScreen()
    screen.set_mode("inject_boot", archive_choices=["/tmp/R36S Studio/BOOT_2026-07-06_00-21"])

    screen._archive_list.setCurrentRow(0)

    assert screen._path_label.text() == "/tmp/R36S Studio/BOOT_2026-07-06_00-21"
    assert screen._next_button.isEnabled() is True


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/manual_folder")
def test_file_screen_browse_still_works_as_fallback_in_archive_mode(mock_dialog, qapp):
    """Repli manuel : même quand des archives existent, Parcourir… reste
    disponible pour désigner un dossier différent."""
    screen = FileScreen()
    screen.set_mode("inject_boot", archive_choices=["/tmp/R36S Studio/BOOT_2026-07-06_00-21"])

    screen._browse()

    assert screen._path_label.text() == "/tmp/manual_folder"
    assert screen._next_button.isEnabled() is True


def test_format_archive_label_formats_known_timestamp_in_french():
    label = format_archive_label("/tmp/R36S Studio/BOOT_2026-07-06_00-21")

    assert label == "6 juillet 2026 à 00h21"


def test_format_archive_label_falls_back_to_folder_name_for_manual_folder():
    label = format_archive_label("/tmp/mon_dossier_perso")

    assert label == "mon_dossier_perso"


# --- FileScreen : dossier de destination avec défaut (étapes A/B, §4.4) ----


def test_file_screen_destination_mode_preselects_default_path(qapp):
    screen = FileScreen()

    screen.set_mode("extract_boot", default_path="/home/x/Documents/R36S Studio")

    assert screen._path_label.text() == "/home/x/Documents/R36S Studio"
    assert screen._next_button.isEnabled() is True


def test_file_screen_destination_mode_shows_hint_and_hides_archive_widgets(qapp):
    screen = FileScreen()
    screen.show()

    screen.set_mode("extract_easyroms", default_path="/home/x/Documents/R36S Studio")

    assert screen._destination_hint_label.isVisible() is True
    assert screen._archive_list.isVisible() is False
    assert screen._archive_empty_label.isVisible() is False


def test_file_screen_other_modes_hide_destination_hint(qapp):
    screen = FileScreen()
    screen.show()

    screen.set_mode("flash")

    assert screen._destination_hint_label.isVisible() is False


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/Volumes/DisqueExterne")
def test_file_screen_destination_mode_can_replace_default_via_browse(mock_dialog, qapp):
    screen = FileScreen()
    screen.set_mode("extract_boot", default_path="/home/x/Documents/R36S Studio")

    screen._browse()

    mock_dialog.assert_called_once()
    assert mock_dialog.call_args.args[-1] == "/home/x/Documents/R36S Studio"  # démarre sur le défaut affiché
    assert screen._path_label.text() == "/Volumes/DisqueExterne"
    assert screen._next_button.isEnabled() is True


def test_file_screen_without_default_path_disables_next_until_chosen(qapp):
    """Un mode destination sans défaut fourni (ne devrait pas arriver en
    pratique, mais ne doit pas planter) laisse Suivant désactivé."""
    screen = FileScreen()

    screen.set_mode("extract_boot")

    assert screen._path_label.text() == ""
    assert screen._next_button.isEnabled() is False


# --- ConfirmScreen ---------------------------------------------------------


def test_confirm_screen_go_disabled_until_checkbox_checked(qapp):
    screen = ConfirmScreen()
    screen.set_device(_make_device())
    assert screen._go_button.isEnabled() is False

    screen._checkbox.setChecked(True)
    assert screen._go_button.isEnabled() is True

    screen._checkbox.setChecked(False)
    assert screen._go_button.isEnabled() is False


def test_confirm_screen_shows_device_display_and_size(qapp):
    screen = ConfirmScreen()
    screen.set_device(_make_device(display="SanDisk Ultra", size_bytes=31_914_983_424))

    text = screen._message.text()
    assert "SanDisk Ultra" in text
    assert "31.9" in text


def test_confirm_screen_cancel_resets_checkbox_and_emits(qapp):
    screen = ConfirmScreen()
    screen.set_device(_make_device())
    screen._checkbox.setChecked(True)

    cancelled = []
    screen.cancelled.connect(lambda: cancelled.append(True))
    screen._cancel()

    assert cancelled == [True]
    assert screen._checkbox.isChecked() is False


# --- ExecuteScreen ---------------------------------------------------------


def test_execute_screen_update_progress_sets_percentage(qapp):
    screen = ExecuteScreen()
    screen.reset("flash")

    screen.update_progress(done=50, total=200, speed=1_000_000)

    assert screen._bar.value() == 25
    assert screen._bar.minimum() == 0 and screen._bar.maximum() == 100


def test_execute_screen_unknown_total_shows_indeterminate_bar(qapp):
    screen = ExecuteScreen()
    screen.reset("flash")

    screen.update_progress(done=50, total=0, speed=1_000_000)

    assert screen._bar.minimum() == 0 and screen._bar.maximum() == 0


def test_format_duration():
    assert _format_duration(45) == "45 s"
    assert _format_duration(125) == "2 min 05 s"
    assert _format_duration(3725) == "1 h 02 min"


# --- ResultScreen ---------------------------------------------------------


def test_result_screen_success_shows_eject_only_for_flash(qapp):
    screen = ResultScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois le parent affiché
    screen.show_success("ok", allow_eject=True)
    assert screen._eject_button.isVisible() is True

    screen.show_success("ok", allow_eject=False)
    assert screen._eject_button.isVisible() is False


def test_result_screen_error_hides_eject(qapp):
    screen = ResultScreen()
    screen.show()
    screen.show_error("boom")
    assert screen._eject_button.isVisible() is False


def test_result_screen_error_without_details_hides_details_toggle(qapp):
    screen = ResultScreen()
    screen.show()
    screen.show_error("Un message déjà clair")
    assert screen._details_toggle.isVisible() is False


def test_result_screen_error_with_details_shows_toggle_collapsed_by_default(qapp):
    """Vocabulaire §5 : le message technique brut (qui peut contenir un
    chemin comme /dev/disk4) reste replié tant qu'on n'a pas cliqué sur
    Détails."""
    screen = ResultScreen()
    screen.show()
    screen.show_error("Impossible de trouver les fichiers de la console.", details="Partition « BOOT » introuvable sur /dev/disk4")

    assert screen._details_toggle.isVisible() is True
    assert screen._details_label.isVisible() is False
    assert "/dev/disk4" not in screen._message.text()


def test_result_screen_details_toggle_reveals_technical_message(qapp):
    screen = ResultScreen()
    screen.show()
    screen.show_error("Un problème est survenu.", details="[Errno 2] /dev/disk4")

    screen._details_toggle.click()

    assert screen._details_label.isVisible() is True
    assert screen._details_label.text() == "[Errno 2] /dev/disk4"


def test_result_screen_identical_message_and_details_hides_toggle(qapp):
    """Si le détail est identique au message principal, pas la peine de le
    répéter sous un panneau Détails."""
    screen = ResultScreen()
    screen.show()
    screen.show_error("Opération annulée.", details="Opération annulée.")

    assert screen._details_toggle.isVisible() is False


def test_result_screen_success_clears_previous_error_details(qapp):
    screen = ResultScreen()
    screen.show()
    screen.show_error("boom", details="détail technique")
    assert screen._details_toggle.isVisible() is True

    screen.show_success("ok", allow_eject=False)

    assert screen._details_toggle.isVisible() is False


# --- ResultScreen : chemin d'archive + bouton révéler (§4.4, écran Résultat)


def test_result_screen_success_without_archive_info_hides_it(qapp):
    screen = ResultScreen()
    screen.show()

    screen.show_success("ok", allow_eject=False)

    assert screen._archive_info_label.isVisible() is False
    assert screen._reveal_button.isVisible() is False


def test_result_screen_success_with_archive_info_shows_it_and_reveal_button(qapp):
    screen = ResultScreen()
    screen.show()

    screen.show_success(
        "ok", allow_eject=True, archive_info="Enregistrée dans : /tmp/BOOT_x", reveal_path="/tmp/BOOT_x"
    )

    assert screen._archive_info_label.isVisible() is True
    assert "/tmp/BOOT_x" in screen._archive_info_label.text()
    assert screen._reveal_button.isVisible() is True


def test_result_screen_reveal_button_emits_stored_path(qapp):
    screen = ResultScreen()
    screen.show()
    screen.show_success("ok", allow_eject=False, archive_info="x", reveal_path="/tmp/BOOT_x")
    received = []
    screen.reveal_requested.connect(lambda path: received.append(path))

    screen._reveal_button.click()

    assert received == ["/tmp/BOOT_x"]


def test_result_screen_error_hides_archive_info_and_reveal_button(qapp):
    screen = ResultScreen()
    screen.show()
    screen.show_success("ok", allow_eject=False, archive_info="x", reveal_path="/tmp/BOOT_x")

    screen.show_error("boom")

    assert screen._archive_info_label.isVisible() is False
    assert screen._reveal_button.isVisible() is False


def test_format_size_formats_megabytes_and_gigabytes():
    from r36s_studio.gui.screens import _format_size

    assert _format_size(500) == "500 o"
    assert _format_size(12_582_912) == "12.0 Mo"
    assert _format_size(2 * 1024**3) == "2.0 Go"
