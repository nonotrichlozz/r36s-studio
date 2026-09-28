"""Tests du choix de langue (`r36s_studio/i18n.py`) : mécanique de
`tr()`, complétude de l'anglais, variables `{…}` identiques d'une langue
à l'autre, mémorisation dans `config.json`, sélecteur des deux accueils,
et mise en page en anglais (libellés plus longs, §5)."""

from __future__ import annotations

import string
from datetime import datetime
from unittest.mock import patch

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QLabel, QPushButton

from r36s_studio import config, i18n
from r36s_studio.config import AppConfig
from r36s_studio.consoles_diverses import strings as cd_strings
from r36s_studio.consoles_diverses.strings_en import STRINGS_EN as CD_STRINGS_EN
from r36s_studio.gui import strings as gui_strings
from r36s_studio.gui.strings_en import STRINGS_EN as GUI_STRINGS_EN

_TABLES = [
    pytest.param(gui_strings.STRINGS, GUI_STRINGS_EN, id="gui"),
    pytest.param(cd_strings.STRINGS, CD_STRINGS_EN, id="consoles_diverses"),
]


def _fields(template: str):
    """Variables d'un modèle, avec leur format (`{size_go:.1f}`) : une
    traduction qui perd, renomme ou change le format d'une variable
    lèverait `KeyError`/`ValueError` à l'affichage, ou montrerait une
    taille fausse."""
    return sorted((name, spec) for _, name, spec, _ in string.Formatter().parse(template) if name is not None)


# --- i18n --------------------------------------------------------------------


def test_default_language_is_french():
    assert i18n.DEFAULT_LANGUAGE == "fr"
    assert i18n.get_language() == "fr"


def test_set_language_falls_back_to_french_for_an_unknown_code():
    i18n.set_language("zh")
    assert i18n.get_language() == "fr"


def test_language_names_are_written_in_their_own_language():
    assert i18n.LANGUAGE_NAMES == {"fr": "Français", "en": "English"}


# --- complétude et variables -------------------------------------------------


@pytest.mark.parametrize("french, english", _TABLES)
def test_english_has_exactly_the_french_keys(french, english):
    assert set(english) - set(french) == set(), "clé anglaise sans équivalent français"
    assert set(french) - set(english) == set(), "chaîne française non traduite"


@pytest.mark.parametrize("french, english", _TABLES)
def test_english_keeps_the_same_variables_and_formats(french, english):
    for key, template in french.items():
        assert _fields(english[key]) == _fields(template), key


@pytest.mark.parametrize("french, english", _TABLES)
def test_no_english_string_is_empty(french, english):
    for key, template in english.items():
        assert template.strip(), key


def test_no_technical_jargon_in_english_strings():
    """Même règle de vocabulaire (§5) qu'en français."""
    forbidden = ["/dev/", "\\\\.\\physicaldrive", "block device", "partition"]
    for key, template in GUI_STRINGS_EN.items():
        lowered = template.lower()
        for term in forbidden:
            assert term not in lowered, f"{key!r} contient un terme technique : {term!r}"


def test_destructive_confirmation_is_translated_with_the_real_size():
    """§2 n°6 : l'avertissement avant une écriture destructive doit dire
    la même chose, avec la même taille, dans les deux langues."""
    i18n.set_language("en")
    message = gui_strings.tr("confirm_erase", display="SanDisk Ultra", size_go=119.24)
    assert message == 'All the data on "SanDisk Ultra" (119.2 GB) will be permanently erased.'
    assert "erased" in gui_strings.tr("confirm_checkbox")


# --- tr() --------------------------------------------------------------------


def test_tr_follows_the_current_language():
    assert gui_strings.tr("home_refresh") == "Rafraîchir"
    i18n.set_language("en")
    assert gui_strings.tr("home_refresh") == "Refresh"
    assert cd_strings.tr("search_button") == "Search"


def test_tr_falls_back_to_french_for_a_key_missing_in_english(monkeypatch):
    monkeypatch.delitem(GUI_STRINGS_EN, "home_refresh")
    i18n.set_language("en")
    assert gui_strings.tr("home_refresh") == "Rafraîchir"


def test_consoles_diverses_tr_falls_back_to_french_for_a_missing_key(monkeypatch):
    monkeypatch.delitem(CD_STRINGS_EN, "search_button")
    i18n.set_language("en")
    assert cd_strings.tr("search_button") == "Rechercher"


def test_tr_unknown_key_still_raises_in_english():
    i18n.set_language("en")
    with pytest.raises(KeyError):
        gui_strings.tr("clef_qui_n_existe_pas")


def test_tr_in_uses_the_given_language_not_the_current_one():
    assert i18n.get_language() == "fr"
    assert gui_strings.tr_in("en", "language_restart_message").startswith("The new language")


def test_friendly_error_message_is_translated():
    i18n.set_language("en")
    assert gui_strings.friendly_error_message("CANCELLED") == "The operation was cancelled before it finished."


# --- formats dépendant de la langue ------------------------------------------


def test_sizes_use_the_units_of_the_current_language():
    from r36s_studio.gui.screens import _format_size

    size = int(1.5 * 1024**3)
    assert _format_size(size) == "1.5 Go"
    i18n.set_language("en")
    assert _format_size(size) == "1.5 GB"
    assert _format_size(512) == "512 B"


def test_dates_follow_the_current_language():
    from r36s_studio.gui.screens import format_datetime_label

    moment = datetime(2026, 7, 6, 0, 21)
    assert format_datetime_label(moment) == "6 juillet 2026 à 00h21"
    i18n.set_language("en")
    assert format_datetime_label(moment) == "July 6, 2026 at 00:21"


@patch("r36s_studio.gui.reveal.platform.system", return_value="Darwin")
def test_reveal_label_is_translated(mock_system):
    from r36s_studio.gui.reveal import reveal_label

    i18n.set_language("en")
    assert reveal_label() == "Show in Finder"


# --- config.json -------------------------------------------------------------


def test_language_defaults_to_french_when_no_file_exists(tmp_path):
    with patch("r36s_studio.config.config_path", return_value=tmp_path / "config.json"):
        assert config.load_config().language == "fr"


def test_save_then_load_roundtrips_language(tmp_path):
    path = tmp_path / "config.json"
    with patch("r36s_studio.config.config_path", return_value=path):
        config.save_config(AppConfig(language="en"))
        assert config.load_config().language == "en"


def test_unknown_language_in_config_falls_back_to_french(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"language": "ja"}', encoding="utf-8")
    with patch("r36s_studio.config.config_path", return_value=path):
        assert config.load_config().language == "fr"


# --- sélecteur ---------------------------------------------------------------


def test_language_selector_lists_native_names_and_shows_the_current_language(qapp):
    from r36s_studio.gui.screens import LanguageSelector

    i18n.set_language("en")
    selector = LanguageSelector()
    assert [selector.itemText(i) for i in range(selector.count())] == ["Français", "English"]
    assert selector.currentData() == "en"
    assert selector.toolTip() == "Langue / Language"


def test_language_selector_emits_only_on_user_choice(qapp):
    from r36s_studio.gui.screens import LanguageSelector

    selector = LanguageSelector()
    emitted = []
    selector.language_selected.connect(emitted.append)

    selector.set_language("en")
    assert emitted == []

    selector.activated.emit(selector.findData("en"))
    assert emitted == ["en"]


def test_both_home_screens_forward_the_selector_signal(qapp):
    from r36s_studio.gui.screens import AssistedLandingScreen, HomeScreen

    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screens = [HomeScreen(), AssistedLandingScreen()]
    for screen in screens:
        emitted = []
        screen.language_selected.connect(emitted.append)
        screen._language_selector.activated.emit(screen._language_selector.findData("en"))
        assert emitted == ["en"]


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_choosing_a_language_saves_it_syncs_both_screens_and_explains_in_that_language(
    mock_list, mock_filter, mock_load, qapp
):
    from r36s_studio.gui.main_window import MainWindow

    with patch("r36s_studio.gui.main_window.app_config.save_config") as mock_save, patch(
        "r36s_studio.gui.main_window.QMessageBox.information"
    ) as mock_info:
        window = MainWindow()
        window._assisted_landing.language_selected.emit("en")

    saved = mock_save.call_args.args[0]
    assert saved.language == "en"
    assert window._home._language_selector.currentData() == "en"
    # Le message parle la langue choisie, pas le français encore affiché.
    assert mock_info.call_args.args[2] == "The new language will apply the next time you start R36S Studio."
    # Appliquée au prochain démarrage seulement.
    assert i18n.get_language() == "fr"


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_choosing_the_current_language_again_does_nothing(mock_list, mock_filter, mock_load, qapp):
    from r36s_studio.gui.main_window import MainWindow

    with patch("r36s_studio.gui.main_window.app_config.save_config") as mock_save, patch(
        "r36s_studio.gui.main_window.QMessageBox.information"
    ) as mock_info:
        window = MainWindow()
        window._home.language_selected.emit("fr")

    mock_save.assert_not_called()
    mock_info.assert_not_called()


def test_app_run_applies_the_saved_language_before_building_any_widget():
    from r36s_studio.gui import app

    seen = []

    class _StopAtFirstWidget(Exception):
        pass

    def _fake_splash():
        seen.append(i18n.get_language())
        raise _StopAtFirstWidget

    # `QApplication` entièrement remplacé : ni feuille de style globale
    # modifiée, ni vraie fenêtre construite -- le test s'arrête au premier
    # widget (l'écran d'attente, qui affiche déjà du texte traduit).
    with patch("r36s_studio.gui.app.app_config.load_config", return_value=AppConfig(language="en")), patch(
        "r36s_studio.gui.app.QApplication"
    ), patch("r36s_studio.gui.app._build_splash", side_effect=_fake_splash):
        with pytest.raises(_StopAtFirstWidget):
            app.run()

    assert seen == ["en"]


# --- mise en page en anglais (§5, chevauchements) ----------------------------


def _text_fits(label: QLabel) -> bool:
    """Le texte entier, retour à la ligne compris, tient dans la hauteur
    réellement attribuée au libellé -- `heightForWidth` ne suffit pas pour
    un libellé à hauteur fixe (renvoie la hauteur fixée)."""
    metrics = QFontMetrics(label.font())
    flags = Qt.TextWordWrap if label.wordWrap() else Qt.TextSingleLine
    needed = metrics.boundingRect(QRect(0, 0, max(label.width(), 1), 100_000), flags, label.text()).height()
    return needed <= label.height()


@pytest.mark.parametrize("language", ["fr", "en"])
def test_assisted_tile_labels_are_never_clipped(qapp, language):
    """Bug corrigé, constaté au rendu en anglais : la tuile 1 réservait
    la hauteur d'une ligne mesurée avec la police par défaut de Qt, pas
    celle du thème -- le bas de « Prepare my card » était coupé
    (« Préparer ma carte » aussi, moins visiblement)."""
    from r36s_studio.gui import theme
    from r36s_studio.gui.screens import AssistedLandingScreen

    i18n.set_language(language)
    qapp.setStyleSheet(theme.STYLESHEET)
    try:
        with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
            screen = AssistedLandingScreen()
        screen.resize(1120, 690)
        screen.show()
        qapp.processEvents()
        for tile in screen._all_tiles:
            assert _text_fits(tile._label), tile._label.text()
    finally:
        qapp.setStyleSheet("")


@pytest.mark.parametrize("language", ["fr", "en"])
def test_header_buttons_never_overlap_and_show_their_whole_text(qapp, language):
    """En-têtes des deux accueils, là où un libellé plus long déborderait
    en premier : aucun bouton tronqué, aucun chevauchement entre voisins.

    Ignoré sans police installée (plateforme Qt « offscreen » nue, ex.
    Windows sans `QT_QPA_FONTDIR`) : chaque caractère y est dessiné comme
    une boîte large, les largeurs ne veulent rien dire -- même en
    français. Vérifié par rendu réel (Segoe UI) lors de l'ajout de
    l'anglais."""
    from PySide6.QtGui import QFontDatabase

    from r36s_studio.gui import theme
    from r36s_studio.gui.screens import AssistedLandingScreen, HomeScreen, LanguageSelector

    if not QFontDatabase.families():
        pytest.skip("aucune police disponible pour Qt : largeurs de texte non significatives")
    i18n.set_language(language)
    qapp.setStyleSheet(theme.STYLESHEET)
    try:
        with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
            home = HomeScreen()
            assisted = AssistedLandingScreen()
        home.setFixedWidth(480)  # colonne gauche réelle (MainView._LEFT_COLUMN_WIDTH)
        assisted.resize(1120, 690)
        for screen in (home, assisted):
            screen.show()
            qapp.processEvents()
            header = [
                widget
                for widget in screen.findChildren(QPushButton) + screen.findChildren(LanguageSelector)
                if widget.isVisible() and widget.property("role") in ("flat", None)
                and widget.mapTo(screen, widget.rect().topLeft()).y() < 120
            ]
            assert header, "aucun widget d'en-tête trouvé"
            for widget in header:
                assert widget.width() >= widget.sizeHint().width(), widget.text() if hasattr(widget, "text") else widget
            rects = [QRect(widget.mapTo(screen, widget.rect().topLeft()), widget.size()) for widget in header]
            for i, first in enumerate(rects):
                for second in rects[i + 1 :]:
                    assert not first.intersects(second)
    finally:
        qapp.setStyleSheet("")
