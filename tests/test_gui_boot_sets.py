"""Écran « Choisir l'écran de la console » (`gui/boot_sets_ui.py`) et son
branchement dans `MainWindow` -- dossier temporaire, jamais une vraie carte."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.config import AppConfig
from r36s_studio.devices import Device
from r36s_studio.gui.boot_sets_ui import BootSetsDialog, BootSetsRunner, action_argv
from r36s_studio.gui.main_window import MainWindow
from r36s_studio.partitions.locate import PartitionInfo

_DEVICE = Device("/dev/fake-disk-test-8", "Carte SD factice", 32_000_000_000, True, "USB", False, [])


def _boot(tmp_path):
    root = tmp_path / "BOOT"
    for name in ("Panel0", "Panel1"):
        (root / "Panels" / name).mkdir(parents=True)
        (root / "Panels" / name / "a.dtb").write_bytes(name.encode())
    (root / "a.dtb").write_bytes(b"origine")
    return root


def _run(root, action, elevated=None):
    boot = PartitionInfo(device_path="/dev/fake-disk-test-8s1", label="", filesystem="vfat", mountpoint=str(root))
    with patch("r36s_studio.gui.boot_sets_ui.locate_mounted", return_value=boot), patch(
        "r36s_studio.gui.boot_sets_ui.unmount_forced"
    ):
        return BootSetsRunner(_DEVICE.path, action, elevated=elevated)._run()


def test_runner_direct_apply_restore_and_errors(tmp_path):
    root = _boot(tmp_path)
    result, error = _run(root, action_argv(apply="Panels/Panel1"))
    assert error is None and result["applied"] == "Panels/Panel1"
    assert (root / "a.dtb").read_bytes() == b"Panel1"

    assert _run(root, action_argv(apply="Panels/Nope")) == (None, "unknown_set")
    result, error = _run(root, action_argv(restore=True))
    assert error is None and (root / "a.dtb").read_bytes() == b"origine"
    assert _run(root, action_argv(restore=True)) == (None, "originals_missing")


def test_runner_falls_back_to_elevated_worker_on_access_denied(tmp_path):
    root = _boot(tmp_path)
    calls = []

    def elevated(action):
        calls.append(action)
        return {"card_id": "x", "applied": None, "can_restore": False, "sets": []}, None

    with patch("r36s_studio.partitions.boot_sets.os.listdir", side_effect=PermissionError("refusé")):
        assert _run(root, [], elevated)[1] is None
        assert _run(root, [], None) == (None, "access_denied")
        assert _run(root, ["--restore"], lambda a: (None, "ELEVATION_REFUSED")) == (None, "elevation_refused")
    assert calls == [[]]


def _result(applied=None):
    return {
        "card_id": "c1",
        "applied": applied,
        "can_restore": applied is not None,
        "sets": [{"set_id": "Panels/Panel0", "name": "Panel0"}, {"set_id": "Panels/Panel1", "name": "Panel1"}],
    }


def test_dialog_strikes_tried_screens_and_asks_outcome(qapp):
    dialog = BootSetsDialog()
    trials = [
        {"set_id": "Panels/Panel0", "name": "Panel0", "date": "2026-10-11", "outcome": "failed"},
        {"set_id": "Panels/Panel1", "name": "Panel1", "date": "2026-10-12", "outcome": "tried"},
    ]
    dialog.set_result(_result(applied="Panels/Panel1"), trials)
    assert dialog._pages.currentWidget() is dialog._outcome_page  # dernier essai sans réponse
    assert "Panel1" in dialog._outcome_text.text()

    answers = []
    dialog.outcome_answered.connect(lambda s, o: answers.append((s, o)))
    dialog._answer("failed")
    assert answers == [("Panels/Panel1", "failed")]

    trials[0]["outcome"] = "booted"
    dialog.set_result(_result(), trials)
    items = [dialog._list.item(i) for i in range(dialog._list.count())]
    assert [i.font().strikeOut() for i in items] == [False, True]  # « a démarré » jamais barré
    assert "11/10/2026" in items[0].text()


def test_dialog_confirms_before_asking_to_write(qapp):
    dialog = BootSetsDialog()
    dialog.set_result(_result(), [])
    requested = []
    dialog.apply_requested.connect(requested.append)
    assert not dialog.try_button.isEnabled() and not dialog.restore_button.isEnabled()

    dialog._list.setCurrentRow(1)
    dialog.try_button.click()
    assert requested == [] and dialog._pages.currentWidget() is dialog._confirm_page
    dialog._on_confirmed()
    assert requested == ["Panels/Panel1"]


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_main_window_records_trial_then_outcome(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._boot_sets_device = _DEVICE

    window._on_boot_sets_finished(_result(applied="Panels/Panel1"), None, ["--apply", "Panels/Panel1"])
    (trial,) = window._app_config.boot_set_trials["c1"]
    assert (trial["set_id"], trial["name"], trial["outcome"]) == ("Panels/Panel1", "Panel1", "tried")
    assert window._boot_sets_dialog._pages.currentWidget() is window._boot_sets_dialog._done_page

    window._on_boot_set_outcome("Panels/Panel1", "failed")
    assert window._app_config.boot_set_trials["c1"][0]["outcome"] == "failed"
    assert mock_save.call_count == 2

    window._on_boot_sets_finished(None, "io", [])
    assert window._boot_sets_dialog._message.text()  # message d'erreur affiché


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_main_window_import_shows_original_screen_first(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window._boot_sets_device = _DEVICE
    result = _result()
    result["sets"].insert(0, {"set_id": "ecran-d-origine", "name": "ecran-d-origine"})

    window._on_boot_sets_finished(result, None, ["--import", "F:/sd original"])

    dialog = window._boot_sets_dialog
    assert dialog._list.item(0).text().startswith("Écran d'origine de cette console")
    assert "en tête de liste" in dialog._message.text()
    assert "F:/sd original" in window._log_panel._log_view.toPlainText()
    assert window._app_config.boot_set_trials == {}  # un import n'est pas un essai
