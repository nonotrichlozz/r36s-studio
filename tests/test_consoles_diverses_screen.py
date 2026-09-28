"""Tests de `consoles_diverses/screen.py` -- bascule des zones, bandeaux
conditionnels, restriction http(s)/PlainText (durcissement demandé), et
comportement du bouton Réessayer. `ConsoleSearchRunner` est mocké au
niveau module pour ne jamais démarrer un vrai thread Qt pendant les tests
(même principe que `tests/test_gui_partition_runner.py`).

La section « Captures de régression » (bas de fichier) couvre la nouvelle
présentation de la fiche (`docs/consoles-diverses-design.md`) sur trois cas
réels : SF3000HD (vérifiée, restriction commerciale, incompatibles), R36S
(fixture IA, `tests/fixtures_reponse_r36s.json`), et une fiche Android sans
aucune option."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QPushButton

from r36s_studio.consoles_diverses.client import ResultatRecherche
from r36s_studio.consoles_diverses.models import fiche_depuis_json
from r36s_studio.consoles_diverses.screen import (
    SLOW_SEARCH_WARNING_DELAY_MS,
    ConsolesDiversesScreen,
    _est_url_externe_sure,
)

FIXTURE_REPONSE_R36S = Path(__file__).parent / "fixtures_reponse_r36s.json"


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


def _fiche_sf3000hd() -> dict:
    return {
        "id": "sf3000hd",
        "identite": {"nom": "SF3000HD", "fabricant": "Data Frog", "alias": []},
        "materiel": {"soc": "HiChip C3100", "architecture": "MIPS"},
        "os": {"type": "proprietaire (H.OS / iCube / cubegm)"},
        "options": {
            "frontend": [
                {
                    "nom": "TreeFrog UI",
                    "description": "Interface/frontend personnalisé pour SF3000HD et consoles apparentées.",
                    "url": "https://github.com/tzubertowski/TreeFrogUI",
                    "licence": "CC-BY-NC-SA-4.0",
                    "restriction_commerciale": True,
                    "source_url": "https://github.com/tzubertowski/TreeFrogUI",
                }
            ],
            "systeme_cfw": [],
            "firmware_origine": [
                {
                    "nom": "Sauvegarde du firmware d'origine",
                    "description": "Procédure de sauvegarde variable selon le modèle exact de console.",
                    "url": "https://github.com/tzubertowski/TreeFrogUI/blob/main/install.md",
                    "source_url": "https://github.com/tzubertowski/TreeFrogUI/blob/main/install.md",
                }
            ],
            "mises_a_jour": [
                {
                    "nom": "update.zip officiel TreeFrog UI",
                    "description": "Copier update.zip à la racine de la carte SD pour mettre à jour TreeFrog UI.",
                    "source_url": "https://github.com/tzubertowski/TreeFrogUI",
                    "licence": "CC-BY-NC-SA-4.0",
                    "restriction_commerciale": True,
                }
            ],
        },
        "incompatibles": [
            {"nom": "ArkOS", "raison": "ARM uniquement, flasher une image ARM corrompt la carte"},
            {"nom": "EmuELEC", "raison": "ARM uniquement, flasher une image ARM corrompt la carte"},
        ],
        "liens_officiels": [],
        "licences": ["CC-BY-NC-SA-4.0"],
        "restriction_commerciale": True,
        "sources": [
            {"url": "https://github.com/tzubertowski/TreeFrogUI", "type": "github"},
        ],
        "statut": "verifie",
        "date_verification": "2026-09-17",
        "signalements": 0,
    }


def _fiche_android_vide() -> dict:
    return {
        "id": "android-clone",
        "identite": {"nom": "Console Android générique", "fabricant": "inconnu", "alias": []},
        "materiel": {"soc": "inconnu", "architecture": "inconnu"},
        "os": {"type": "Android (LineageOS)"},
        "options": {"frontend": [], "systeme_cfw": [], "firmware_origine": [], "mises_a_jour": []},
        "statut": "non_verifie",
        "signalements": 0,
    }


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


def test_unverified_ia_fiche_with_restriction_commerciale_shows_both_signals(qapp):
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
    assert any("non vérifié" in text for text in labels_text)
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


# --- Licence : jamais un écran vide, un message précis par cas -----------------


def test_without_a_key_the_idle_screen_explains_and_offers_to_enter_one(qapp):
    """Signalé : écran vide sous le champ de recherche tant qu'aucune clé
    n'est saisie. L'explication ne bloque rien -- le catalogue vérifié se
    consulte sans clé."""
    screen = ConsolesDiversesScreen()
    screen.show()
    emitted = []
    screen.settings_requested.connect(lambda: emitted.append(True))

    assert screen._no_licence_frame.isVisible() is True
    assert screen._search_button.isEnabled() is True
    screen._no_licence_button.click()
    assert emitted == [True]


def test_the_no_key_explanation_disappears_once_a_key_is_saved(qapp):
    screen = ConsolesDiversesScreen()
    screen.show()

    screen.set_network_config("https://exemple.invalid", "r36s-" + "a" * 32)

    assert screen._no_licence_frame.isVisible() is False


def test_the_no_key_explanation_never_hides_a_result_or_an_error(qapp):
    screen = ConsolesDiversesScreen()
    screen.show()

    screen._on_search_error("serveur_injoignable", "")

    assert screen._error_frame.isVisible() is True
    assert screen._no_licence_frame.isVisible() is False


@pytest.mark.parametrize(
    "code, attendu",
    [
        ("licence_requise", "clé de licence est nécessaire"),
        ("licence_invalide", "n'est pas reconnue"),
        ("licence_expiree", "a expiré"),
        ("licence_revoquee", "a été désactivée"),
    ],
)
def test_licence_refusals_show_a_precise_message_and_a_way_to_enter_the_key(qapp, code, attendu):
    screen = ConsolesDiversesScreen()
    screen.show()

    screen._on_search_error(code, "")

    assert screen._error_frame.isVisible() is True
    assert attendu in screen._error_label.text()
    assert screen._error_licence_button.isVisible() is True


@pytest.mark.parametrize(
    "code, attendu",
    [
        ("quota_licence_depasse", "pour aujourd'hui"),
        ("trop_de_requetes", "Attends une minute"),
        ("erreur_interne", "problème"),
    ],
)
def test_quota_and_server_refusals_are_explained_without_asking_for_another_key(qapp, code, attendu):
    """Une autre clé ne réglerait ni le quota du jour ni une panne : pas
    de bouton « Saisir ma clé » ici."""
    screen = ConsolesDiversesScreen()
    screen.show()

    screen._on_search_error(code, "")

    assert attendu in screen._error_label.text()
    assert screen._error_label.text() != "Une erreur est survenue."
    assert screen._error_licence_button.isVisible() is False


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
    # Un vrai bouton de lien (retouche visuelle), jamais l'URL brute comme
    # texte -- celle-ci reste consultable en infobulle (point 4).
    assert widget.property("role") == "link"
    assert widget.text() == "↗ Ouvrir la page"
    assert widget.toolTip() == "https://example.invalid/a"
    assert widget.cursor().shape() == Qt.PointingHandCursor


def test_link_widget_uses_github_label_for_a_github_url():
    """Retouche visuelle demandée : libellé plus parlant quand l'URL
    contient github.com."""
    from r36s_studio.consoles_diverses.screen import _link_widget

    widget = _link_widget("https://github.com/tzubertowski/TreeFrogUI")

    assert widget.text() == "↗ Ouvrir sur GitHub"
    assert widget.toolTip() == "https://github.com/tzubertowski/TreeFrogUI"


def test_link_widget_uses_generic_label_for_a_non_github_url():
    from r36s_studio.consoles_diverses.screen import _link_widget

    widget = _link_widget("https://example.invalid/a")

    assert widget.text() == "↗ Ouvrir la page"


def test_link_widget_uses_theme_icon_instead_of_glyph_when_available():
    """Le caractère ↗ est un repli explicite -- quand le thème du système
    fournit une icône de lien externe, elle est utilisée à la place
    (`QIcon.setIcon`), pas les deux en même temps."""
    from PySide6.QtGui import QIcon, QPixmap

    from r36s_studio.consoles_diverses.screen import _link_widget

    fake_icon = QIcon(QPixmap(1, 1))
    with patch("r36s_studio.consoles_diverses.screen.QIcon.fromTheme", return_value=fake_icon):
        widget = _link_widget("https://example.invalid/a")

    assert widget.text() == "Ouvrir la page"
    assert "↗" not in widget.text()
    assert widget.icon().isNull() is False


def test_link_widget_explicit_label_still_gets_the_glyph_and_tooltip():
    """Un `label` explicite (compatibilité) suit la même règle d'apparence
    que le libellé calculé -- seul le texte affiché change."""
    from r36s_studio.consoles_diverses.screen import _link_widget

    widget = _link_widget("https://example.invalid/a", label="Mon libellé")

    assert widget.text() == "↗ Mon libellé"
    assert widget.toolTip() == "https://example.invalid/a"


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


# --- Aucun bouton d'installation/téléchargement automatique -----------------


def test_no_install_or_download_button_appears_in_a_rendered_fiche(qapp):
    screen = ConsolesDiversesScreen()
    fiche = fiche_depuis_json(_fiche_sf3000hd())

    screen._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    content = screen._result_frame.widget()
    button_texts = [button.text().lower() for button in content.findChildren(QPushButton)]
    interdits = ("install", "télécharg", "download")
    assert not any(mot in texte for texte in button_texts for mot in interdits)


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


# --- Recherche lente (délai serveur allongé, nouvelles tentatives/modèles) --


@patch("r36s_studio.consoles_diverses.screen.ConsoleSearchRunner")
def test_search_starts_slow_search_timer_with_expected_delay(mock_runner_cls, qapp):
    screen = ConsolesDiversesScreen()
    screen._reference_edit.setText("RG35XX")

    screen._search_button.click()

    assert screen._slow_search_timer.isActive() is True
    assert screen._slow_search_timer.interval() == SLOW_SEARCH_WARNING_DELAY_MS == 15_000
    assert screen._status_label.text() == "Recherche en cours…"


def test_slow_search_warning_updates_status_label_text(qapp):
    screen = ConsolesDiversesScreen()

    screen._on_slow_search_warning()

    assert screen._status_label.text() == "La recherche prend plus de temps que prévu…"


@patch("r36s_studio.consoles_diverses.screen.ConsoleSearchRunner")
def test_relaunching_search_resets_status_label_after_previous_slow_warning(mock_runner_cls, qapp):
    screen = ConsolesDiversesScreen()
    screen._reference_edit.setText("RG35XX")
    screen._on_slow_search_warning()

    screen._search_button.click()

    assert screen._status_label.text() == "Recherche en cours…"


def test_search_finished_stops_the_slow_search_timer(qapp):
    screen = ConsolesDiversesScreen()
    screen._slow_search_timer.start()

    screen._on_search_finished(ResultatRecherche(statut="aucune_information_trouvee", console=None))

    assert screen._slow_search_timer.isActive() is False


def test_search_error_stops_the_slow_search_timer(qapp):
    screen = ConsolesDiversesScreen()
    screen._slow_search_timer.start()

    screen._on_search_error("serveur_injoignable", "")

    assert screen._slow_search_timer.isActive() is False


def test_ia_surchargee_error_shows_error_zone_with_friendly_message(qapp):
    screen = ConsolesDiversesScreen()
    screen.show()

    screen._on_search_error("ia_surchargee", "")

    assert screen._error_frame.isVisible() is True
    assert "surchargé" in screen._error_label.text()
    assert screen._retry_error_button.isVisible() is True


# --- Alignement du lien des cartes d'option ---------------------------------


def test_option_link_is_left_aligned_within_its_card(qapp):
    from r36s_studio.consoles_diverses.models import OptionConsole
    from r36s_studio.consoles_diverses.screen import _build_option_widget

    option = OptionConsole(
        nom="Option", description="desc", source_url="https://example.invalid/source", url="https://example.invalid/a"
    )

    container = _build_option_widget(option)

    layout = container.layout()
    link_widget = next(
        item.widget()
        for i in range(layout.count())
        if (item := layout.itemAt(i)).widget() is not None
        and isinstance(item.widget(), QPushButton)
        and item.widget().property("role") == "link"
    )
    assert link_widget.text() == "↗ Ouvrir la page"
    assert link_widget.toolTip() == "https://example.invalid/a"
    index = layout.indexOf(link_widget)
    assert layout.itemAt(index).alignment() == Qt.AlignLeft


def test_sources_links_are_left_aligned_buttons_not_raw_urls(qapp):
    """Même traitement que la carte d'option (point 5, retouche
    visuelle) : un vrai bouton aligné à gauche, jamais l'URL brute comme
    texte affiché."""
    from r36s_studio.consoles_diverses.models import Source
    from r36s_studio.consoles_diverses.screen import ConsolesDiversesScreen as _Screen

    screen = _Screen()
    sources = [Source(url="https://example.invalid/doc", type="web")]

    container = screen._build_sources_section(sources)

    content = next(w for w in container.findChildren(QPushButton) if w.property("role") == "link")
    assert content.text() != "https://example.invalid/doc"
    assert content.text() == "↗ Ouvrir la page"
    assert content.toolTip() == "https://example.invalid/doc"
    content_layout = content.parentWidget().layout()
    index = content_layout.indexOf(content)
    assert content_layout.itemAt(index).alignment() == Qt.AlignLeft


# --- Captures de régression (docs/consoles-diverses-design.md) --------------


def _texts(container, widget_cls) -> list:
    return [widget.text() for widget in container.findChildren(widget_cls)]


def test_sf3000hd_fiche_shows_verified_badge_restriction_and_incompatibles(qapp):
    screen = ConsolesDiversesScreen()
    fiche = fiche_depuis_json(_fiche_sf3000hd())

    screen._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    content = screen._result_frame.widget()
    labels = _texts(content, QLabel)

    assert "Vérifié" in labels
    assert "Data Frog" in labels  # fabricant connu, jamais "Non trouvé"
    assert any("non commerciale" in t for t in labels)
    assert any(t.startswith("Ne pas installer : ") and "ArkOS" in t and "EmuELEC" in t for t in labels)
    assert "HiChip C3100" in labels
    assert "MIPS" in labels
    assert "proprietaire (H.OS / iCube / cubegm)" in labels
    # Une seule catégorie vide (systeme_cfw) -- frontend/firmware_origine/
    # mises_a_jour ont chacune une option, donc pas regroupées.
    assert any(t == "Rien trouvé pour : Système / CFW" for t in labels)
    assert "TreeFrog UI" in labels


def test_sf3000hd_sources_section_starts_collapsed_and_toggle_reveals_it(qapp):
    screen = ConsolesDiversesScreen()
    fiche = fiche_depuis_json(_fiche_sf3000hd())

    screen._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche))

    content = screen._result_frame.widget()
    toggle = next(b for b in content.findChildren(QPushButton) if "Sources" in b.text())
    assert toggle.text() == "▸ Sources (1)"
    assert toggle.isChecked() is False

    toggle.click()

    assert toggle.isChecked() is True
    assert toggle.text() == "▾ Sources (1)"
    # Bouton de lien, pas l'URL brute (retouche visuelle, même traitement
    # que la carte d'option) -- github.com donne le libellé dédié, l'URL
    # complète reste consultable en infobulle. Cherché uniquement dans la
    # section Sources (le conteneur du bouton Sources lui-même) : les
    # cartes d'option de cette même fiche ont elles aussi des boutons
    # `role="link"`, sans rapport avec ce test.
    sources_container = toggle.parentWidget()
    liens = [b for b in sources_container.findChildren(QPushButton) if b.property("role") == "link"]
    assert len(liens) == 1
    assert liens[0].text() == "↗ Ouvrir sur GitHub"
    assert liens[0].toolTip() == "https://github.com/tzubertowski/TreeFrogUI"


def test_r36s_ia_fixture_shows_unverified_badge_and_grouped_empty_categories(qapp):
    screen = ConsolesDiversesScreen()
    payload = json.loads(FIXTURE_REPONSE_R36S.read_text(encoding="utf-8-sig"))
    fiche = fiche_depuis_json(payload["console"])

    screen._on_search_finished(ResultatRecherche(statut="trouve_par_ia", console=fiche, pr_creee=False))

    content = screen._result_frame.widget()
    labels = _texts(content, QLabel)

    assert "Non vérifié" in labels
    assert "Trouvé automatiquement, non vérifié." in labels
    # Fabricant absent de la fixture -> "inconnu" -> ligne masquée sous le nom,
    # jamais "Non trouvé" ni le mot brut "inconnu".
    assert "Non trouvé" not in labels
    assert "inconnu" not in labels
    assert any("Rockchip RK3326" in t for t in labels)
    assert "Linux" in labels
    assert any("non commerciale" in t for t in labels)  # restriction_commerciale=true dans la fixture
    assert any("à vérifier" in t for t in labels)  # l'option EmulationStation a licence_a_verifier=true
    assert "Licence non détectée" in labels  # option.licence="non_detectee" dans la fixture
    assert "non_detectee" not in labels
    assert any(
        t == "Rien trouvé pour : Système / CFW, Firmware d'origine, Mises à jour" for t in labels
    )
    assert "EmulationStation" in labels


def test_android_fiche_without_any_option_shows_single_message_and_android_notice(qapp):
    screen = ConsolesDiversesScreen()
    fiche = fiche_depuis_json(_fiche_android_vide())

    screen._on_search_finished(ResultatRecherche(statut="trouve_par_ia", console=fiche, pr_creee=False))

    content = screen._result_frame.widget()
    labels = _texts(content, QLabel)

    assert "Peu d'informations trouvées pour cette console." in labels
    assert not any(t.startswith("Rien trouvé pour : ") for t in labels)
    assert any("ADB" in t for t in labels)
    # Aucune des deux autres conditions du bloc « À savoir » ne s'applique ici.
    assert not any("non commerciale" in t for t in labels)
    assert not any("à vérifier" in t for t in labels)
    # Fabricant "inconnu" -> ligne masquée sous le nom (contrairement à SoC/
    # Architecture, qui affichent "Non trouvé" -- voir les tests dédiés
    # `test_header_hides_fabricant_line_when_unknown` ci-dessous), jamais le
    # mot brut "inconnu" en clair.
    assert "inconnu" not in labels


# --- Retouches : licence "non_detectee" et fabricant absent -----------------


def test_licence_non_detectee_shows_friendly_chip_label(qapp):
    from r36s_studio.consoles_diverses.models import OptionConsole
    from r36s_studio.consoles_diverses.screen import _build_option_widget

    option = OptionConsole(
        nom="Option", description="desc", source_url="https://example.invalid/source", licence="non_detectee"
    )

    container = _build_option_widget(option)

    chip_texts = [label.text() for label in container.findChildren(QLabel)]
    assert "Licence non détectée" in chip_texts
    assert "non_detectee" not in chip_texts


def test_licence_with_real_value_is_shown_unchanged(qapp):
    from r36s_studio.consoles_diverses.models import OptionConsole
    from r36s_studio.consoles_diverses.screen import _build_option_widget

    option = OptionConsole(
        nom="Option",
        description="desc",
        source_url="https://example.invalid/source",
        licence="CC-BY-NC-SA-4.0",
    )

    container = _build_option_widget(option)

    chip_texts = [label.text() for label in container.findChildren(QLabel)]
    assert "CC-BY-NC-SA-4.0" in chip_texts


def test_header_hides_fabricant_line_when_unknown(qapp):
    screen = ConsolesDiversesScreen()
    data = _fiche()
    data["identite"]["fabricant"] = "inconnu"
    fiche = fiche_depuis_json(data)

    header = screen._build_header(fiche)

    labels = [label.text() for label in header.findChildren(QLabel)]
    assert "inconnu" not in labels
    assert "Non trouvé" not in labels


def test_header_shows_fabricant_line_when_known(qapp):
    screen = ConsolesDiversesScreen()
    fiche = fiche_depuis_json(_fiche())  # fabricant = "Fabricant Y"

    header = screen._build_header(fiche)

    labels = [label.text() for label in header.findChildren(QLabel)]
    assert "Fabricant Y" in labels
