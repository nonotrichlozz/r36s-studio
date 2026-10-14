"""Parcours « Ma console ne démarre plus » / « carte neuve » : profil de
console (`identify/console_profile.py`), fenêtre (`gui/journey_ui.py`) et
branchement dans `MainWindow`."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.config import AppConfig
from r36s_studio.gui.journey_ui import ConsoleJourneyDialog
from r36s_studio.gui.main_window import MainWindow
from r36s_studio.identify import IdentifyFailureReason, IdentifyResult
from r36s_studio.identify import console_profile as cp
from r36s_studio.identify.releases import ARKOS_K36_RELEASES_URL, DARKOSEN_R36S_RELEASES_URL


def test_profiles_and_recommendation():
    assert cp.profile_from_identify(IdentifyResult(is_clone=True)) == cp.CLONE
    assert cp.profile_from_identify(IdentifyResult(failure_reason=IdentifyFailureReason.NO_DTB_FOUND)) is None
    assert cp.profile_from_reference("g80ca-mb v1.2-20250422") == cp.CLONE
    assert cp.profile_from_reference("R36S-V21 2023") == cp.UNKNOWN  # saisie libre, jamais refusée
    assert cp.recommended_releases_url(cp.ORIGIN) == DARKOSEN_R36S_RELEASES_URL
    assert cp.recommended_releases_url(cp.UNKNOWN) == ARKOS_K36_RELEASES_URL  # « je ne sais pas » -> image clone


def test_dialog_reference_then_file(qapp):
    dialog = ConsoleJourneyDialog()
    dialog.start(not_booting=False)
    assert dialog._pages.currentWidget() is dialog._console_page
    assert not dialog.reference_button.isEnabled()

    dialog.reference_edit.setText("G80CA-MB V1.2-20250422")
    dialog.reference_button.click()
    assert dialog._pages.currentWidget() is dialog._system_page
    assert dialog.recommended_url() == ARKOS_K36_RELEASES_URL

    chosen = []
    dialog.image_chosen.connect(lambda *args: chosen.append(args))
    with patch.object(dialog, "_ask_file", return_value="C:/fake/k36.img.xz"):
        dialog._choose_file()
    assert chosen == [("C:/fake/k36.img.xz", cp.CLONE, "G80CA-MB V1.2-20250422")]


def test_dialog_unreadable_card_stays_on_console_page(qapp):
    dialog = ConsoleJourneyDialog()
    dialog.start(not_booting=True)
    assert dialog._pages.currentWidget() is dialog._start_page
    dialog._show_console_page()
    dialog.set_identify_result(IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED))
    assert dialog._pages.currentWidget() is dialog._console_page
    assert dialog._status.text()


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_main_window_routes_journey(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()

    with patch.object(window, "_start_boot_sets") as boot_sets:
        window._assisted_landing.not_booting_requested.emit()
        window._journey_dialog.screens_requested.emit()
    boot_sets.assert_called_once()

    # Identification : le résultat va au parcours, pas à IdentifyResultDialog.
    with patch.object(window, "_start_assisted_identify"):
        window._on_journey_identify_requested()
    with patch.object(window._identify_result_dialog, "open") as result_dialog:
        window._on_identify_finished(IdentifyResult(is_clone=True))
    result_dialog.assert_not_called()
    assert window._journey_dialog._profile == cp.CLONE

    with patch.object(window, "_on_prepare_card_requested") as prepare:
        window._on_journey_image_chosen("C:/fake/k36.img.xz", cp.CLONE, "")
    prepare.assert_called_once()
    assert window._file_path == "C:/fake/k36.img.xz" and window._journey_flash and window._assisted_ad_hoc_active


def test_dialog_pages_never_squash_at_any_window_size(qapp):
    """Signalé le 2026-10-14 : « Quelle console as-tu ? » gardait la hauteur
    minimale de la première page affichée -- boutons superposés, « Lire la
    carte » coupé. `Dialog.event` recalcule le minimum, textes à retour à
    la ligne compris."""
    from PySide6.QtWidgets import QLabel, QPushButton

    from r36s_studio.gui import theme

    qapp.setStyleSheet(theme.STYLESHEET)
    try:
        dialog = ConsoleJourneyDialog()
        dialog.start(not_booting=True)
        dialog.show()
        for show_page in (lambda: dialog.start(not_booting=False), lambda: dialog._show_system_page(cp.AMBIGUOUS)):
            show_page()
            for size in ((200, 150), (420, 300), (900, 700)):
                dialog.resize(*size)
                for _ in range(3):
                    qapp.processEvents()
                for widget in dialog.findChildren(QPushButton) + dialog.findChildren(QLabel):
                    if not widget.isVisible():
                        continue
                    needed = widget.heightForWidth(widget.width()) if widget.hasHeightForWidth() else widget.minimumSizeHint().height()
                    assert widget.height() >= needed, (size, widget.text())
        dialog.close()
    finally:
        qapp.setStyleSheet("")


def test_ambiguous_reference_offers_darkosen_then_k36(qapp):
    """2026-10-14 : dArkOSen a fait redémarrer une R36S `R36S-V12
    2023-08-18` ; K36 reste à un clic pour un clone de même référence."""
    dialog = ConsoleJourneyDialog()
    opened = []
    dialog.open_url_requested.connect(opened.append)
    dialog.start(not_booting=False)
    dialog.reference_edit.setText("R36S-V12 2023-08-18")
    dialog.reference_button.click()
    dialog.show()

    assert dialog.recommended_url() == DARKOSEN_R36S_RELEASES_URL
    assert dialog.clone_page_button.isVisible()
    dialog.clone_page_button.click()
    assert opened == [ARKOS_K36_RELEASES_URL]

    dialog._show_system_page(cp.CLONE)
    assert not dialog.clone_page_button.isVisible()
    assert dialog.recommended_url() == ARKOS_K36_RELEASES_URL
    dialog.close()
