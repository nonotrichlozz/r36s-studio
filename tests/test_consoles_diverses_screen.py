"""Tests de `consoles_diverses/screen.py` -- bascule des zones, bandeaux
conditionnels, restriction http(s)/PlainText (durcissement demandé), et
comportement du bouton Réessayer. `ConsoleSearchRunner` est mocké au
niveau module pour ne jamais démarrer un vrai thread Qt pendant les tests
(même principe que `tests/test_gui_partition_runner.py`)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from r36s_studio.consoles_diverses.client import ResultatRecherche
from r36s_studio.consoles_diverses.models import fiche_depuis_json
from r36s_studio.consoles_diverses.screen import ConsolesDiversesScreen, _est_url_externe_sure


def _fiche(**overrides) -> dict:
    data = {
        "id": "console-x",
        "identite": {"nom": "Console X", "fabricant": "Fabricant Y", "alias": []},
        "materiel": {"soc": "soc-x", "architecture": "ARM64"},
        "os": {"type": "linux-cfw"},
        "options": {"frontend": [], "systeme_cfw": [], "firmware_origine": [], "mises_a_jour": []},
        "statut": "verifie",
        "signalements": 0,
    }
    data.update(overrides)
    return data


# --- _est_url_externe_sure ---------------------------------------------------


@pytest.mark.parametrize(
    "url,attendu",
    [
        ("https://example.invalid/a", True),
        ("http://example.invalid/a", True),
        ("file:///etc/passwd", False),
        ("javascript:alert(1)", False),
        ("/chemin/local/sans/schema", False),
        ("", False),
        (None, False),
    ],
)
def test_est_url_externe_sure(url, attendu):
    assert _est_url_externe_sure(url) is attendu


# --- Zones et bandeaux -------------------------------------------------------


def test_screen_starts_with_all_result_zones_hidden(qapp):
    screen = ConsolesDiversesScreen()

    assert screen._status_label.isVisible() is False
    assert screen._result_frame.isVisible() is False
    assert screen._no_info_frame.isVisible() is False
    assert screen._error_frame.isVisible() is False


def test_verified_fiche_shows_verified_badge_no_unverified_or_restriction_banner(qapp):
    screen = ConsolesDiversesScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    fiche = fiche_depuis_json(_fiche(statut="verifie"))

    screen._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    assert screen._result_frame.isVisible() is True
    assert screen._no_info_frame.isVisible() is False
    assert screen._error_frame.isVisible() is False


def test_unverified_ia_fiche_with_restriction_commerciale_shows_both_banners(qapp):
    screen = ConsolesDiversesScreen()
    data = _fiche(statut="non_verifie", restriction_commerciale=True)
    data["options"]["frontend"] = [
        {
            "nom": "TreeFrog UI",
            "description": "desc",
            "source_url": "https://example.invalid/a",
            "licence": "CC-BY-NC-SA-4.0",
            "licence_a_verifier": True,
            "restriction_commerciale": True,
        }
    ]
    fiche = fiche_depuis_json(data)

    screen._on_search_finished(ResultatRecherche(statut="trouve_par_ia", console=fiche, pr_creee=False))

    content = screen._result_frame.widget()
    labels_text = [label.text() for label in content.findChildren(QLabel)]
    assert any("non commerciale" in text for text in labels_text)
    assert any("non vérifiées" in text for text in labels_text)
    assert any("à vérifier" in text for text in labels_text)


def test_aucune_information_trouvee_shows_no_info_zone_only(qapp):
    screen = ConsolesDiversesScreen()
    screen.show()

    screen._on_search_finished(ResultatRecherche(statut="aucune_information_trouvee", console=None))

    assert screen._no_info_frame.isVisible() is True
    assert screen._result_frame.isVisible() is False
    assert screen._error_frame.isVisible() is False


def test_search_error_shows_error_zone_with_friendly_message(qapp):
    screen = ConsolesDiversesScreen()
    screen.show()

    screen._on_search_error("serveur_injoignable", "")

    assert screen._error_frame.isVisible() is True
    assert "serveur" in screen._error_label.text().lower()


def test_search_finished_reenables_controls(qapp):
    screen = ConsolesDiversesScreen()
    screen._set_controls_enabled(False)

    screen._on_search_finished(ResultatRecherche(statut="aucune_information_trouvee", console=None))

    assert screen._reference_edit.isEnabled() is True
    assert screen._search_button.isEnabled() is True


# --- Texte brut, jamais interprété (point 1) --------------------------------


def test_all_labels_in_result_zone_use_plain_text_format(qapp):
    screen = ConsolesDiversesScreen()
    data = _fiche()
    data["options"]["frontend"] = [
        {
            "nom": "<b>Nom avec balise</b>",
            "description": "<script>alert(1)</script>",
            "source_url": "https://example.invalid/a",
        }
    ]
    fiche = fiche_depuis_json(data)

    screen._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    content = screen._result_frame.widget()
    for label in content.findChildren(QLabel):
        assert label.textFormat() == Qt.PlainText

    labels_text = [label.text() for label in content.findChildren(QLabel)]
    assert "<b>Nom avec balise</b>" in labels_text  # jamais interprété, affiché tel quel


# --- Liens restreints à http(s) (point 2) -----------------------------------


def test_option_with_unsafe_url_is_not_clickable(qapp):
    screen = ConsolesDiversesScreen()
    data = _fiche()
    data["options"]["frontend"] = [
        {
            "nom": "Option dangereuse",
            "description": "desc",
            "source_url": "https://example.invalid/a",
            "url": "javascript:alert(1)",
        }
    ]
    fiche = fiche_depuis_json(data)

    screen._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    content = screen._result_frame.widget()
    button_texts = [button.text() for button in content.findChildren(QPushButton)]
    assert "javascript:alert(1)" not in button_texts


def test_option_with_safe_https_url_is_clickable():
    from r36s_studio.consoles_diverses.screen import _link_widget

    widget = _link_widget("https://example.invalid/a")

    assert isinstance(widget, QPushButton)
    assert widget.text() == "https://example.invalid/a"


def test_fiche_source_with_unsafe_scheme_shown_as_plain_text(qapp):
    screen = ConsolesDiversesScreen()
    data = _fiche(sources=[{"url": "file:///etc/passwd", "type": "web"}])
    fiche = fiche_depuis_json(data)

    screen._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    content = screen._result_frame.widget()
    button_texts = [button.text() for button in content.findChildren(QPushButton)]
    label_texts = [label.text() for label in content.findChildren(QLabel)]
    assert "file:///etc/passwd" not in button_texts
    assert "file:///etc/passwd" in label_texts


# --- Recherche / Réessayer ---------------------------------------------------


@patch("r36s_studio.consoles_diverses.screen.ConsoleSearchRunner")
def test_search_button_disables_controls_shows_searching_and_creates_runner(mock_runner_cls, qapp):
    screen = ConsolesDiversesScreen()
    screen.show()
    screen.set_network_config("http://localhost:8787", "cle")
    screen._reference_edit.setText("RG35XX")

    screen._search_button.click()

    assert screen._reference_edit.isEnabled() is False
    assert screen._search_button.isEnabled() is False
    assert screen._status_label.isVisible() is True
    mock_runner_cls.assert_called_once()
    args, kwargs = mock_runner_cls.call_args
    assert args[0] == "RG35XX"
    assert args[1] == "http://localhost:8787"
    assert args[2] == "cle"


def test_search_button_with_empty_reference_does_nothing(qapp):
    screen = ConsolesDiversesScreen()
    screen._reference_edit.setText("   ")

    with patch("r36s_studio.consoles_diverses.screen.ConsoleSearchRunner") as mock_runner_cls:
        screen._search_button.click()
        mock_runner_cls.assert_not_called()


@patch("r36s_studio.consoles_diverses.screen.ConsoleSearchRunner")
def test_retry_button_relaunches_search_with_same_reference(mock_runner_cls, qapp):
    screen = ConsolesDiversesScreen()
    screen._reference_edit.setText("Ma Référence")
    screen._on_search_error("serveur_injoignable", "")

    screen._retry_error_button.click()

    mock_runner_cls.assert_called_once()
    args, _kwargs = mock_runner_cls.call_args
    assert args[0] == "Ma Référence"


@patch("r36s_studio.consoles_diverses.screen.ConsoleSearchRunner")
def test_retry_no_info_button_relaunches_search(mock_runner_cls, qapp):
    screen = ConsolesDiversesScreen()
    screen._reference_edit.setText("Référence")
    screen._on_search_finished(ResultatRecherche(statut="aucune_information_trouvee", console=None))

    screen._retry_no_info_button.click()

    mock_runner_cls.assert_called_once()


def test_back_button_emits_signal(qapp):
    screen = ConsolesDiversesScreen()
    received = []
    screen.back_requested.connect(lambda: received.append(True))

    screen._back_button.click()

    assert received == [True]


def test_settings_button_emits_signal(qapp):
    screen = ConsolesDiversesScreen()
    received = []
    screen.settings_requested.connect(lambda: received.append(True))

    screen._settings_button.click()

    assert received == [True]
