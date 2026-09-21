"""Tests de `gui/screens.py::AndroidScreen` -- outil « Console Android »
(étape 1, docs/android-adb.md). Aucun accès adb/réseau réel : cet écran ne
connaît que des signaux et des setters, pilotés ici directement comme le
ferait `main_window.py`."""

from __future__ import annotations

from PySide6.QtCore import Qt

from r36s_studio.android.emulators import EmulatorCatalog, EmulatorEntry, EmulatorVariant, SENTINEL_A_VERIFIER
from r36s_studio.android.models import AdbDeviceEntry, AndroidDeviceInfo, DetectionResult
from r36s_studio.consoles_diverses.models import fiche_depuis_json
from r36s_studio.gui.screens import AndroidScreen


def _find_category_row(screen: AndroidScreen, category_id) -> int:
    for row in range(screen._category_list.count()):
        if screen._category_list.item(row).data(Qt.UserRole) == category_id:
            return row
    raise AssertionError(f"catégorie {category_id!r} introuvable dans la colonne de gauche")


def _fiche(statut="verifie"):
    return fiche_depuis_json(
        {
            "id": "x",
            "identite": {"nom": "Retroid Pocket Flip 2", "fabricant": "Retroid"},
            "statut": statut,
            "materiel": {"soc": "SD865", "architecture": "arm64"},
            "os": {"type": "Android"},
        }
    )


def _device_info():
    return AndroidDeviceInfo(
        serial="SER1",
        manufacturer="Retroid",
        model="RP Flip 2",
        product_name="flip2",
        android_version="13",
        abi="arm64-v8a",
    )


# --- Zones -----------------------------------------------------------------


def test_show_need_consent_shows_only_the_consent_frame(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_need_consent("https://dl.google.com/x.zip")

    assert screen._consent_frame.isVisible()
    assert not screen._device_frame.isVisible()
    assert not screen._catalog_frame.isVisible()
    assert not screen._emulators_frame.isVisible()
    assert "dl.google.com" in screen._consent_url_label.text()


def test_show_detecting_shows_only_the_status_frame(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detecting()

    assert screen._status_frame.isVisible()
    assert not screen._consent_frame.isVisible()
    assert not screen._device_frame.isVisible()


def test_show_detection_result_ready_shows_device_catalog_and_emulators(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))

    assert screen._device_frame.isVisible()
    assert screen._catalog_frame.isVisible()
    assert screen._emulators_frame.isVisible()
    assert not screen._status_frame.isVisible()
    assert not screen._consent_frame.isVisible()


def test_show_detection_result_no_device_shows_only_status_frame(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detection_result(DetectionResult(state="no_device"))

    assert screen._status_frame.isVisible()
    assert not screen._device_frame.isVisible()
    assert screen._status_title_label.text()
    assert screen._status_help_label.text()


def test_show_detection_result_unauthorized_shows_raw_output(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detection_result(
        DetectionResult(state="unauthorized", devices=[AdbDeviceEntry(serial="SER1", state="unauthorized")])
    )

    assert screen._status_raw_output.isVisible()
    assert "SER1" in screen._status_raw_output.toPlainText()


def test_show_detection_result_multiple_devices(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detection_result(
        DetectionResult(
            state="multiple_devices",
            devices=[AdbDeviceEntry(serial="S1", state="device"), AdbDeviceEntry(serial="S2", state="device")],
        )
    )

    assert screen._status_frame.isVisible()
    assert "S1" in screen._status_raw_output.toPlainText()
    assert "S2" in screen._status_raw_output.toPlainText()


def test_show_detection_result_adb_error_shows_error_detail(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detection_result(DetectionResult(state="adb_error", error_detail="délai dépassé"))

    assert "délai dépassé" in screen._status_raw_output.toPlainText()


# --- Console détectée --------------------------------------------------


def test_populate_device_shows_known_values(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))

    assert screen._device_value_labels["manufacturer"].text() == "Retroid"
    assert screen._device_value_labels["model"].text() == "RP Flip 2"


def test_populate_device_shows_not_found_for_unknown_values(qapp):
    unknown_device = AndroidDeviceInfo(
        serial="SER1", manufacturer="inconnu", model="inconnu", product_name="inconnu", android_version="13", abi="inconnu"
    )
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.show_detection_result(DetectionResult(state="ready", device=unknown_device))

    assert screen._device_value_labels["manufacturer"].text() == "Non trouvé"
    assert screen._device_value_labels["android_version"].text() == "13"


# --- Téléchargement d'adb -------------------------------------------------


def test_show_downloading_hides_download_button_and_shows_progress(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_need_consent("https://dl.google.com/x.zip")

    screen.show_downloading()

    assert not screen._consent_download_button.isVisible()
    assert screen._download_bar.isVisible()
    assert screen._download_cancel_button.isVisible()


def test_set_download_progress_updates_bar_range_and_value(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_downloading()

    screen.set_download_progress(50, 100)

    assert screen._download_bar.minimum() == 0
    assert screen._download_bar.maximum() == 100
    assert screen._download_bar.value() == 50


def test_set_download_progress_with_unknown_total_is_indeterminate(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_downloading()

    screen.set_download_progress(50, 0)

    assert screen._download_bar.minimum() == 0
    assert screen._download_bar.maximum() == 0


def test_show_download_error_shows_message_and_resets_button(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_downloading()

    screen.show_download_error("Le téléchargement a échoué.")

    assert screen._download_error_label.isVisible()
    assert screen._download_error_label.text() == "Le téléchargement a échoué."
    assert screen._consent_download_button.isVisible()


def test_set_platform_tools_size_formats_known_size(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.set_platform_tools_size(1024 * 1024)

    assert "environ" in screen._consent_size_label.text()


def test_set_platform_tools_size_shows_unknown_when_none(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.set_platform_tools_size(None)

    assert "inconnue" in screen._consent_size_label.text()


# --- Catalogue --------------------------------------------------------


def test_search_catalog_button_emits_current_model(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))
    requested = []
    screen.search_catalog_requested.connect(lambda ref: requested.append(ref))

    screen._catalog_search_button.click()

    assert requested == ["RP Flip 2"]


def test_show_catalog_found_verified_displays_badge(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))

    screen.show_catalog_found(_fiche(statut="verifie"))

    assert screen._catalog_result_layout.count() >= 2


def test_show_catalog_found_unverified_does_not_raise(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))

    screen.show_catalog_found(_fiche(statut="non_verifie"))


def test_show_catalog_not_found_displays_message(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))

    screen.show_catalog_not_found()

    assert screen._catalog_status_label.isVisible()


def test_show_catalog_error_displays_message(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))

    screen.show_catalog_error("Le serveur est injoignable.")

    assert screen._catalog_status_label.text() == "Le serveur est injoignable."


def test_new_detection_resets_previous_catalog_result(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))
    screen.show_catalog_found(_fiche())
    assert screen._catalog_result_layout.count() > 0

    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))

    assert screen._catalog_result_layout.count() == 0


# --- Émulateurs recommandés ------------------------------------------


def test_set_emulator_catalog_builds_one_row_per_entry(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    # `_emulators_frame` (parent de `_emulators_warning_label`) n'est visible
    # qu'en zone "ready" (§ `_show_zone`) -- sans appareil détecté, le label
    # resterait invisible quel que soit son propre `setVisible`.
    screen.show_detection_result(DetectionResult(state="ready", device=_device_info()))
    catalog = EmulatorCatalog(
        avertissement="Vérifie toujours la source.",
        emulateurs=[
            EmulatorEntry(
                id="x",
                nom="X",
                systemes_emules=["Y"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="actif",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
            ),
            EmulatorEntry(
                id="z",
                nom="Z",
                systemes_emules=["W"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="abandonne",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
            ),
        ],
    )

    screen.set_emulator_catalog(catalog)

    assert screen._emulators_list_layout.count() == 2
    assert screen._emulators_warning_label.isVisible()
    assert screen._emulators_warning_label.text() == "Vérifie toujours la source."

    # Badge de statut du projet (demandé explicitement) -- un par carte,
    # texte convivial plutôt que le mot-clé brut "actif"/"abandonne".
    from PySide6.QtWidgets import QLabel

    first_row = screen._emulators_list_layout.itemAt(0).widget()
    second_row = screen._emulators_list_layout.itemAt(1).widget()
    first_row_texts = [label.text().lower() for label in first_row.findChildren(QLabel)]
    second_row_texts = [label.text().lower() for label in second_row.findChildren(QLabel)]
    assert any("actif" in text for text in first_row_texts)
    assert any("abandonné" in text for text in second_row_texts)


def test_set_emulator_catalog_hides_warning_when_empty(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.set_emulator_catalog(EmulatorCatalog(avertissement="", emulateurs=[]))

    assert not screen._emulators_warning_label.isVisible()
    assert screen._emulators_list_layout.count() == 0


# --- Filtrage par appareil (signalé : liste identique quelle que soit la
# console détectée) -----------------------------------------------------


def _capability_catalog():
    return EmulatorCatalog(
        avertissement="",
        emulateurs=[
            EmulatorEntry(
                id="leger",
                nom="Léger",
                systemes_emules=["Y"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="actif",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
            ),
            EmulatorEntry(
                id="exigeant",
                nom="Exigeant",
                systemes_emules=["Z"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="actif",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
                architecture_minimale="arm64-v8a",
                android_minimum="12",
            ),
        ],
    )


def _device(abi="arm64-v8a", android_version="13"):
    return AndroidDeviceInfo(
        serial="SER1", manufacturer="Retroid", model="RP Flip 2", product_name="flip2", android_version=android_version, abi=abi
    )


def test_emulator_list_is_filtered_for_a_capable_device(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())

    screen.show_detection_result(DetectionResult(state="ready", device=_device(abi="arm64-v8a", android_version="13")))

    assert screen._emulators_list_layout.count() == 2
    assert not screen._emulators_generic_label.isVisible()


def test_emulator_list_is_filtered_for_a_limited_device(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())

    screen.show_detection_result(
        DetectionResult(state="ready", device=_device(abi="armeabi-v7a", android_version="8.0"))
    )

    assert screen._emulators_list_layout.count() == 1
    assert not screen._emulators_generic_label.isVisible()


def test_emulator_list_shows_generic_notice_when_device_info_is_unknown(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())

    screen.show_detection_result(
        DetectionResult(state="ready", device=_device(abi="inconnu", android_version="inconnu"))
    )

    assert screen._emulators_list_layout.count() == 2
    assert screen._emulators_generic_label.isVisible()


def test_emulator_list_refilters_when_a_new_device_is_detected(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device(abi="arm64-v8a", android_version="13")))
    assert screen._emulators_list_layout.count() == 2

    screen.show_detection_result(
        DetectionResult(state="ready", device=_device(abi="armeabi-v7a", android_version="8.0"))
    )

    assert screen._emulators_list_layout.count() == 1


# --- Classement par console émulée (colonne de gauche) --------------------


def test_category_sidebar_lists_all_and_the_fourteen_categories(qapp):
    from r36s_studio.android.emulators import CATEGORIES

    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))

    assert screen._category_list.count() == 1 + len(CATEGORIES)
    assert screen._category_list.item(0).data(Qt.UserRole) is None  # "Toutes" en tête


def test_category_sidebar_shows_zero_for_categories_with_no_entry(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))

    xbox_row = _find_category_row(screen, "xbox")
    assert "(0)" in screen._category_list.item(xbox_row).text()


def test_selecting_a_category_filters_the_card_list(qapp):
    catalog = EmulatorCatalog(
        avertissement="",
        emulateurs=[
            EmulatorEntry(
                id="ps2_emu",
                nom="PS2 emu",
                systemes_emules=["PlayStation 2"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="actif",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
            ),
            EmulatorEntry(
                id="switch_emu",
                nom="Switch emu",
                systemes_emules=["Nintendo Switch"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="actif",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
            ),
        ],
    )
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(catalog)
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))
    assert screen._emulators_list_layout.count() == 2

    screen._category_list.setCurrentRow(_find_category_row(screen, "ps2"))

    assert screen._emulators_list_layout.count() == 1
    assert screen._selected_category == "ps2"


def test_selecting_toutes_shows_the_full_list_again(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))
    screen._category_list.setCurrentRow(_find_category_row(screen, "retro"))
    assert screen._emulators_list_layout.count() != screen._category_list.count()  # sanity

    screen._category_list.setCurrentRow(0)  # "Toutes"

    assert screen._selected_category is None
    assert screen._emulators_list_layout.count() == len(_capability_catalog().emulateurs)


def test_category_selection_survives_a_re_render(qapp):
    """Une nouvelle détection (même appareil, ou un autre) ne doit pas
    ramener silencieusement l'utilisateur sur "Toutes" s'il avait choisi
    une catégorie précise."""
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))
    screen._category_list.setCurrentRow(_find_category_row(screen, "retro"))
    assert screen._selected_category == "retro"

    screen.show_detection_result(DetectionResult(state="ready", device=_device()))

    assert screen._selected_category == "retro"


# --- Compteur « cochés » et Tout cocher / Tout décocher -------------------


def test_checked_counter_starts_at_zero(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))

    assert screen._checked_counter_label.text() == "0/2 cochés"


def test_checking_a_card_updates_the_counter(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))

    screen._visible_checkboxes["leger"].setChecked(True)

    assert screen._checked_counter_label.text() == "1/2 cochés"


def test_check_all_button_checks_only_the_visible_category(qapp):
    catalog = EmulatorCatalog(
        avertissement="",
        emulateurs=[
            EmulatorEntry(
                id="a",
                nom="A",
                systemes_emules=["PSP"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="actif",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
            ),
            EmulatorEntry(
                id="b",
                nom="B",
                systemes_emules=["Nintendo Switch"],
                licence=SENTINEL_A_VERIFIER,
                prix=SENTINEL_A_VERIFIER,
                statut_projet="actif",
                url_officielle="https://example.invalid/",
                source_url="https://example.invalid/",
            ),
        ],
    )
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(catalog)
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))
    screen._category_list.setCurrentRow(_find_category_row(screen, "psp"))

    screen._check_all_button.click()

    assert screen._checked_emulator_ids == {"a"}
    assert screen._checked_counter_label.text() == "1/2 cochés"


def test_uncheck_all_button_unchecks_only_the_visible_category(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))
    screen._on_check_all_clicked()  # sur "Toutes" -- tout coché
    assert screen._checked_counter_label.text() == "2/2 cochés"

    screen._on_uncheck_all_clicked()

    assert screen._checked_counter_label.text() == "0/2 cochés"


def test_checked_state_survives_switching_category(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))
    screen._visible_checkboxes["leger"].setChecked(True)

    screen._category_list.setCurrentRow(_find_category_row(screen, "retro"))
    screen._category_list.setCurrentRow(0)  # retour à "Toutes"

    assert screen._visible_checkboxes["leger"].isChecked() is True
    assert screen._checked_counter_label.text() == "1/2 cochés"


def test_checked_counter_drops_ids_no_longer_realistic_for_a_new_device(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device(abi="arm64-v8a", android_version="13")))
    screen._visible_checkboxes["exigeant"].setChecked(True)
    assert screen._checked_counter_label.text() == "1/2 cochés"

    screen.show_detection_result(
        DetectionResult(state="ready", device=_device(abi="armeabi-v7a", android_version="8.0"))
    )

    assert "exigeant" not in screen._checked_emulator_ids
    assert screen._checked_counter_label.text() == "0/1 cochés"


# --- Variantes ------------------------------------------------------------


def test_card_without_variants_shows_base_links_only(qapp):
    from PySide6.QtWidgets import QComboBox

    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(_capability_catalog())
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))

    row = screen._emulators_list_layout.itemAt(0).widget()
    assert row.findChildren(QComboBox) == []


def test_card_with_variants_shows_a_dropdown_and_switches_links(qapp):
    from PySide6.QtWidgets import QComboBox

    entry = EmulatorEntry(
        id="x",
        nom="X",
        systemes_emules=["PSP"],
        licence=SENTINEL_A_VERIFIER,
        prix=SENTINEL_A_VERIFIER,
        statut_projet="actif",
        url_officielle="https://example.invalid/standard",
        source_url="https://example.invalid/standard",
        variantes=[
            EmulatorVariant(nom="Standard", url_officielle="https://example.invalid/standard", source_url="https://example.invalid/standard"),
            EmulatorVariant(nom="Edge", url_officielle="https://example.invalid/edge", source_url="https://example.invalid/edge"),
        ],
    )
    catalog = EmulatorCatalog(avertissement="", emulateurs=[entry])
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    screen.set_emulator_catalog(catalog)
    screen.show_detection_result(DetectionResult(state="ready", device=_device()))

    row = screen._emulators_list_layout.itemAt(0).widget()
    combos = row.findChildren(QComboBox)
    assert len(combos) == 1
    combo = combos[0]
    assert [combo.itemText(i) for i in range(combo.count())] == ["Standard", "Edge"]

    def link_targets():
        return [
            row._links_row.itemAt(i).widget().toolTip()
            for i in range(row._links_row.count())
            if row._links_row.itemAt(i).widget() is not None
        ]

    assert link_targets() == ["https://example.invalid/standard", "https://example.invalid/standard"]

    combo.setCurrentIndex(1)

    assert link_targets() == ["https://example.invalid/edge", "https://example.invalid/edge"]


# --- Signaux de base -----------------------------------------------------


def test_back_and_refresh_signals(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    events = []
    screen.back_requested.connect(lambda: events.append("back"))
    screen.refresh_requested.connect(lambda: events.append("refresh"))

    screen._refresh_button.click()

    assert events == ["refresh"]


def test_consent_and_cancel_download_signals(qapp):
    screen = AndroidScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    events = []
    screen.consent_download_requested.connect(lambda: events.append("download"))
    screen.cancel_download_requested.connect(lambda: events.append("cancel"))

    screen._consent_download_button.click()
    screen.show_downloading()
    screen._download_cancel_button.click()

    assert events == ["download", "cancel"]
