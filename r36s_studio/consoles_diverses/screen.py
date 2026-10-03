# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Écran de recherche de la section « Consoles diverses » (étape 1). Un
seul écran avec des zones montrées/masquées tour à tour (recherche → en
cours → résultat / aucune information / erreur), plutôt qu'un empilement de
plusieurs écrans -- flux linéaire, pas de va-et-vient.

Réutilise `gui/screens.py::Screen` (attribut Qt `WA_StyledBackground`) et
les rôles/`badgeKind` déjà présents dans `gui/theme.py` -- infrastructure
visuelle générique, partagée par toute l'application, sans aucun lien avec
le domaine métier du reste du dépôt (§CLAUDE.md du package, règle
d'isolation : c'est le contenu qui est isolé, pas l'habillage Qt).

**Une fiche vient d'un serveur externe et peut être générée par IA -- elle
est traitée comme une donnée non fiable, jamais comme du contenu de
confiance** (durcissement demandé) :
- Tout texte serveur passe par `_plain_label`/`_badge_label`, qui
  verrouillent `setTextFormat(Qt.PlainText)` -- aucun HTML n'est jamais
  interprété.
- Un lien -- y compris le bouton « Ouvrir la page » d'une carte d'option --
  n'est cliquable que si `_est_url_externe_sure` le confirme -- strictement
  `http://`/`https://`, jamais `file:`/`javascript:`/un chemin local/un
  schéma absent, qui restent du texte simple non cliquable. Aucun bouton
  d'installation ou de téléchargement automatique : uniquement des liens
  ouverts dans le navigateur (§CLAUDE.md du package, hors périmètre).

Présentation (`docs/consoles-diverses-design.md`) : une fiche lisible en 5
secondes -- en-tête (nom + statut vérifié/non vérifié), bloc « À savoir »
conditionnel (licence non commerciale, licence à vérifier, incompatibles,
console Android), carte Matériel, options groupées par catégorie (les
catégories vides sont résumées en une seule ligne plutôt que répétées),
section Sources repliée par défaut. Contenu centré sur une colonne de
largeur de lecture max (`_MAX_CONTENT_WIDTH`)."""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import urlsplit

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.gui.screens import Screen

from . import settings_store
from .client import ResultatRecherche
from .models import FicheConsole, Incompatible, OptionConsole
from .search_runner import ConsoleSearchRunner
from .strings import friendly_error_message, tr

MAX_REFERENCE_LENGTH = 64
SLOW_SEARCH_WARNING_DELAY_MS = 15_000
_MAX_CONTENT_WIDTH = 900

_CATEGORY_TITLE_KEYS = {
    "frontend": "category_frontend",
    "systeme_cfw": "category_systeme_cfw",
    "firmware_origine": "category_firmware_origine",
    "mises_a_jour": "category_mises_a_jour",
}

# Sentinelle renvoyée par `models.py::fiche_depuis_json` pour tout champ
# matériel/identité optionnel absent ou malformé -- affichée « Non trouvé »
# plutôt que le mot brut, un débutant n'a aucune raison de savoir ce que
# "inconnu" signifie ici (§docs/consoles-diverses-design.md).
_VALEUR_INCONNUE = "inconnu"

# Sentinelle du schéma pour une option dont la licence n'a pas pu être
# identifiée (ex. `tests/fixtures_reponse_r36s.json::options.frontend[0].
# licence`) -- affichée en clair plutôt que le code technique brut, même
# principe que `_VALEUR_INCONNUE` ci-dessus.
_LICENCE_NON_DETECTEE = "non_detectee"


def _est_url_externe_sure(url: Optional[str]) -> bool:
    """Un lien n'est jamais cliquable que s'il s'agit explicitement d'une
    URL `http://`/`https://` -- une fiche peut être générée par IA, donc
    traitée comme une donnée non fiable. `file:`, `javascript:`, un chemin
    local ou un schéma absent restent du texte simple, jamais un lien ouvert
    automatiquement. S'applique à tout lien de la fiche, y compris le
    bouton « Ouvrir la page » d'une carte d'option -- même garantie, pas
    d'exception pour ce libellé plus convivial."""
    if not url:
        return False
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return False
    return scheme in ("http", "https")


def _plain_label(text: str, role: Optional[str] = None, wrap: bool = False) -> QLabel:
    """`QLabel` dont le format de texte est verrouillé sur `PlainText` --
    une donnée serveur n'est jamais interprétée comme du HTML, quel que
    soit son contenu (durcissement demandé, point 1)."""
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    if role:
        label.setProperty("role", role)
    if wrap:
        label.setWordWrap(True)
    return label


def _badge_label(text: str, badge_kind: str) -> QLabel:
    """Pastille capsule (`role="badge"`/`badgeKind`, `gui/theme.py`) --
    même verrouillage `PlainText` que `_plain_label` (point 1), factorisé
    ici puisque plusieurs pastilles distinctes (statut vérifié, licence,
    restriction commerciale) partagent exactement ce contrat."""
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setProperty("role", "badge")
    label.setProperty("badgeKind", badge_kind)
    return label


def _valeur_ou_non_trouve(valeur: str) -> QLabel:
    """`_VALEUR_INCONNUE` (le repli par défaut de `models.py` pour un champ
    matériel/identité absent ou malformé) s'affiche en gris « Non trouvé »
    plutôt que le mot technique brut."""
    if valeur.strip().lower() == _VALEUR_INCONNUE:
        return _plain_label(tr("value_not_found"), role="secondary")
    return _plain_label(valeur)


def _licence_affichee(licence: str) -> str:
    """`_LICENCE_NON_DETECTEE` (sentinelle du schéma pour une option dont la
    licence n'a pas pu être identifiée) s'affiche en clair plutôt que le
    code technique brut sur la pastille de la carte d'option."""
    if licence.strip().lower() == _LICENCE_NON_DETECTEE:
        return tr("licence_non_detectee")
    return licence


# Nom d'icône tenté auprès du thème d'icônes du système (`QIcon.
# fromTheme`) -- best-effort, comme les illustrations optionnelles de
# `gui/asset_paths.py` : aucun thème d'icônes freedesktop n'existe sous
# Windows par défaut (plateforme la plus testée dans ce projet), donc ce
# nom ne résout quasiment jamais en pratique ici -- `_GLYPH_EXTERNAL_LINK`
# est le repli explicitement demandé, pas un cas d'exception rare.
_ICON_NAME_EXTERNAL_LINK = "external-link"
_GLYPH_EXTERNAL_LINK = "↗"


def _est_url_github(url: str) -> bool:
    """Détecte un lien GitHub par simple recherche de sous-chaîne (retouche
    visuelle demandée : « Ouvrir sur GitHub » quand l'URL contient
    `github.com`) -- ne change jamais rien à la sécurité du lien
    (`_est_url_externe_sure`, seule autorité sur ce qui est cliquable),
    uniquement le libellé affiché."""
    return "github.com" in url.lower()


def _default_link_label(url: str) -> str:
    """Libellé par défaut d'un bouton de lien externe -- plus parlant que
    l'URL brute (retouche visuelle demandée), commun à la carte d'option
    et à la section Sources (même traitement, point 5)."""
    return tr("open_github_button") if _est_url_github(url) else tr("open_page_button")


def _apply_external_link_appearance(button: QPushButton, label: str) -> None:
    """Icône de lien externe devant le texte quand le thème du système en
    fournit une (`QIcon.fromTheme`, jamais garanti) ; à défaut, le
    caractère ↗ en préfixe du texte -- repli explicitement demandé plutôt
    qu'un bouton sans aucun indice qu'il ouvre une page à l'extérieur de
    l'application."""
    icon = QIcon.fromTheme(_ICON_NAME_EXTERNAL_LINK)
    if icon.isNull():
        button.setText(f"{_GLYPH_EXTERNAL_LINK} {label}")
    else:
        button.setIcon(icon)
        button.setText(label)


def _link_widget(url: Optional[str], label: Optional[str] = None) -> QWidget:
    """Un vrai bouton cliquable, jamais un `role="flat"` qui se confond
    avec du texte simple (signalé : « Ouvrir la page » ressemblait à du
    texte) -- si `url` est une adresse http(s) sûre (point 2 du
    durcissement) ; un simple texte non cliquable sinon, jamais caché pour
    autant, l'utilisateur voit toujours l'adresse brute. Le texte affiché
    n'est jamais l'URL elle-même : `label`, quand fourni, ou sinon un
    libellé calculé (`_default_link_label`, « Ouvrir sur GitHub »/« Ouvrir
    la page ») -- l'URL complète reste toujours consultable en infobulle.
    Ne change en rien la règle de sécurité : une URL non sûre reste le
    texte brut de l'URL, jamais un libellé convivial, jamais un bouton."""
    if not url:
        return _plain_label("", role="secondary")
    if _est_url_externe_sure(url):
        button = QPushButton()
        button.setProperty("role", "link")
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(url)
        _apply_external_link_appearance(button, label or _default_link_label(url))
        button.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        return button
    return _plain_label(url, role="secondary", wrap=True)


def _build_restriction_banner() -> QWidget:
    frame = QFrame()
    frame.setProperty("role", "danger")
    layout = QVBoxLayout(frame)
    layout.addWidget(_plain_label(tr("restriction_commerciale_banner"), role="dangerTitle", wrap=True))
    return frame


def _build_warning_banner(text: str) -> QWidget:
    """Symétrique de `_build_restriction_banner`, teinte orange (`role=
    "warning"`, `gui/theme.py`) -- signal de prudence plutôt que de danger
    (ex. licence à vérifier)."""
    frame = QFrame()
    frame.setProperty("role", "warning")
    layout = QVBoxLayout(frame)
    layout.addWidget(_plain_label(text, role="dangerTitle", wrap=True))
    return frame


def _build_card(*, title: Optional[str] = None) -> tuple[QWidget, QVBoxLayout]:
    """Cadre `role="row"` générique (surface, bordure, coins arrondis) --
    l'unité visuelle répétée pour l'en-tête, le bloc « À savoir » et la
    carte Matériel (§docs/consoles-diverses-design.md)."""
    frame = QFrame()
    frame.setProperty("role", "row")
    layout = QVBoxLayout(frame)
    if title:
        layout.addWidget(_plain_label(title, role="title"))
    return frame, layout


def _build_option_widget(option: OptionConsole) -> QWidget:
    container = QFrame()
    container.setProperty("role", "row")
    layout = QVBoxLayout(container)
    layout.addWidget(_plain_label(option.nom, role="rowTitle"))
    layout.addWidget(_plain_label(option.description, role="rowDesc", wrap=True))

    chips_row = QHBoxLayout()
    has_chip = False
    if option.licence:
        chips_row.addWidget(_badge_label(_licence_affichee(option.licence), "neutral"))
        has_chip = True
    if option.restriction_commerciale:
        chips_row.addWidget(_badge_label(tr("restriction_commerciale_chip"), "danger"))
        has_chip = True
    if has_chip:
        chips_row.addStretch()
        layout.addLayout(chips_row)

    if option.url:
        # Pas de libellé fixe ici : `_link_widget` calcule « Ouvrir sur
        # GitHub »/« Ouvrir la page » selon l'URL (retouche visuelle).
        layout.addWidget(_link_widget(option.url), alignment=Qt.AlignLeft)

    return container


def _build_hardware_card(fiche: FicheConsole) -> QWidget:
    frame, layout = _build_card(title=tr("hardware_title"))
    grid = QGridLayout()
    grid.setColumnStretch(1, 1)
    champs = [
        (tr("hardware_label_soc"), fiche.soc),
        (tr("hardware_label_architecture"), fiche.architecture),
        (tr("hardware_label_os_type"), fiche.os_type),
    ]
    for row, (label_text, valeur) in enumerate(champs):
        grid.addWidget(_plain_label(label_text, role="secondary"), row, 0)
        grid.addWidget(_valeur_ou_non_trouve(valeur), row, 1)
    layout.addLayout(grid)
    return frame


def _licence_a_verifier_quelque_part(fiche: FicheConsole) -> bool:
    """Agrégat purement présentationnel (calculé ici, pas dans
    `models.py` -- aucun changement de parsing demandé) : vrai si au moins
    une option de la fiche porte `licence_a_verifier`, pour une seule ligne
    de synthèse dans le bloc « À savoir » plutôt qu'une mention répétée sur
    chaque carte d'option."""
    return any(
        option.licence_a_verifier
        for _, options in fiche.options.toutes_les_categories()
        for option in options
    )


def _build_incompatibles_widget(incompatibles: List[Incompatible]) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    liste = ", ".join(incompatible.nom for incompatible in incompatibles)
    layout.addWidget(_plain_label(tr("incompatibles_title", liste=liste), wrap=True))
    for incompatible in incompatibles:
        layout.addWidget(_plain_label(incompatible.raison, role="secondary", wrap=True))
    return container


def _build_info_block(fiche: FicheConsole) -> Optional[QWidget]:
    """Bloc « À savoir » -- absent entièrement si aucune des quatre
    conditions ne s'applique (§docs/consoles-diverses-design.md, point 2).
    Licence non commerciale et licence à vérifier sont des signaux courts,
    colorés (rouge/orange) ; incompatibles et mention Android restent en
    texte simple, la spec ne leur donnant pas de couleur."""
    est_android = "android" in fiche.os_type.lower()
    licence_a_verifier = _licence_a_verifier_quelque_part(fiche)
    a_quelque_chose = (
        fiche.a_une_restriction_commerciale or licence_a_verifier or bool(fiche.incompatibles) or est_android
    )
    if not a_quelque_chose:
        return None

    frame, layout = _build_card(title=tr("info_title"))
    if fiche.a_une_restriction_commerciale:
        layout.addWidget(_build_restriction_banner())
    if licence_a_verifier:
        layout.addWidget(_build_warning_banner(tr("licence_a_verifier_mention")))
    if fiche.incompatibles:
        layout.addWidget(_build_incompatibles_widget(fiche.incompatibles))
    if est_android:
        layout.addWidget(_plain_label(tr("android_notice"), role="secondary", wrap=True))
    return frame


def _build_options_section(fiche: FicheConsole) -> List[QWidget]:
    """Une carte par option présente, plus -- pour les catégories qui n'en
    ont aucune -- une seule ligne grise groupée plutôt qu'un titre de
    catégorie répété pour ne rien dire (point 4). Si la fiche n'a
    strictement aucune option nulle part, un message unique remplace tout
    (point 6) -- pas de liste de catégories vides à côté d'un message déjà
    équivalent."""
    widgets: List[QWidget] = []
    categories = fiche.options.toutes_les_categories()
    total_options = sum(len(options) for _, options in categories)

    if total_options == 0:
        widgets.append(_plain_label(tr("no_options_at_all_message"), role="secondary"))
        return widgets

    categories_vides: List[str] = []
    for key, options in categories:
        if not options:
            categories_vides.append(tr(_CATEGORY_TITLE_KEYS[key]))
            continue
        widgets.append(_plain_label(tr(_CATEGORY_TITLE_KEYS[key]), role="title"))
        for option in options:
            widgets.append(_build_option_widget(option))

    if categories_vides:
        widgets.append(
            _plain_label(tr("categories_without_options", liste=", ".join(categories_vides)), role="secondary")
        )
    return widgets


def _clear_layout(layout: QLayout) -> None:
    """Vide `layout` avant de le repeupler (nouvelle recherche) --
    `deleteLater()` plutôt qu'une suppression immédiate, comme le reste de
    ce projet fait pour tout widget Qt retiré d'un layout affiché."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
            continue
        sub_layout = item.layout()
        if sub_layout is not None:
            _clear_layout(sub_layout)


# Refus de licence pour lesquels saisir (ou ressaisir) une clé est la
# solution -- jamais le quota du jour, qu'une autre clé ne réglerait pas.
_CODES_SAISIE_LICENCE = {"licence_requise", "licence_invalide", "licence_expiree", "licence_revoquee"}


class ConsolesDiversesScreen(Screen):
    """Écran unique de la section (étape 1, mode recherche). `set_network_
    config` doit être appelé (par `MainWindow`, depuis `settings_store`)
    avant toute recherche -- valeurs par défaut sûres (serveur de
    production, aucune clé) sinon, pour ne jamais lever si l'appelant
    oublie."""

    back_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server_url = settings_store.adresse_serveur()
        self._licence_key = ""
        self._opener = None
        self._runner: Optional[ConsoleSearchRunner] = None
        self._slow_search_timer = QTimer(self)
        self._slow_search_timer.setSingleShot(True)
        self._slow_search_timer.setInterval(SLOW_SEARCH_WARNING_DELAY_MS)
        self._slow_search_timer.timeout.connect(self._on_slow_search_warning)

        root = QVBoxLayout(self)

        top_row = QHBoxLayout()
        self._back_button = QPushButton(tr("back_button"))
        self._back_button.setProperty("role", "flat")
        self._back_button.clicked.connect(self.back_requested.emit)
        top_row.addWidget(self._back_button)
        top_row.addStretch()
        top_row.addWidget(_plain_label(tr("screen_title"), role="title"))
        top_row.addStretch()
        self._settings_button = QPushButton(tr("settings_button"))
        self._settings_button.setProperty("role", "flat")
        self._settings_button.clicked.connect(self.settings_requested.emit)
        top_row.addWidget(self._settings_button)
        root.addLayout(top_row)

        search_row = QHBoxLayout()
        self._reference_edit = QLineEdit()
        self._reference_edit.setMaxLength(MAX_REFERENCE_LENGTH)
        self._reference_edit.setPlaceholderText(tr("reference_placeholder"))
        self._reference_edit.returnPressed.connect(self._lancer_recherche)
        search_row.addWidget(self._reference_edit, 1)
        self._search_button = QPushButton(tr("search_button"))
        self._search_button.setProperty("role", "primary")
        self._search_button.clicked.connect(self._lancer_recherche)
        search_row.addWidget(self._search_button)
        root.addLayout(search_row)

        self._status_label = _plain_label(tr("searching_status"), role="secondary")
        root.addWidget(self._status_label)

        self._result_frame = QScrollArea()
        self._result_frame.setWidgetResizable(True)

        # Colonne centrée, largeur de lecture max (§docs/consoles-diverses-
        # design.md) -- un widget extérieur avec deux ressorts horizontaux
        # encadrant une colonne dont la largeur est plafonnée, plutôt que le
        # contenu du `QScrollArea` directement : `findChildren` (tests
        # existants) traverse cette imbrication sans rien y changer.
        result_outer = QWidget()
        result_outer_layout = QHBoxLayout(result_outer)
        result_outer_layout.setContentsMargins(0, 0, 0, 0)
        result_outer_layout.addStretch()
        result_content = QWidget()
        result_content.setMaximumWidth(_MAX_CONTENT_WIDTH)
        self._result_content_layout = QVBoxLayout(result_content)
        result_outer_layout.addWidget(result_content, 1)
        result_outer_layout.addStretch()
        self._result_frame.setWidget(result_outer)
        root.addWidget(self._result_frame, 1)

        self._no_info_frame = QWidget()
        no_info_layout = QVBoxLayout(self._no_info_frame)
        no_info_layout.addWidget(_plain_label(tr("no_info_title"), role="title"))
        no_info_layout.addWidget(_plain_label(tr("no_info_message"), role="secondary", wrap=True))
        self._retry_no_info_button = QPushButton(tr("retry_button"))
        self._retry_no_info_button.clicked.connect(self._lancer_recherche)
        no_info_layout.addWidget(self._retry_no_info_button)
        root.addWidget(self._no_info_frame)

        self._error_frame = QWidget()
        error_layout = QVBoxLayout(self._error_frame)
        self._error_label = _plain_label("", role="secondary", wrap=True)
        error_layout.addWidget(self._error_label)
        error_buttons = QHBoxLayout()
        self._retry_error_button = QPushButton(tr("retry_button"))
        self._retry_error_button.clicked.connect(self._lancer_recherche)
        error_buttons.addWidget(self._retry_error_button)
        # Seulement pour un refus de licence : mène directement à la saisie
        # de la clé plutôt que de laisser chercher le bon réglage.
        self._error_licence_button = QPushButton(tr("enter_licence_button"))
        self._error_licence_button.setProperty("role", "primary")
        self._error_licence_button.clicked.connect(self.settings_requested.emit)
        error_buttons.addWidget(self._error_licence_button)
        error_buttons.addStretch()
        error_layout.addLayout(error_buttons)
        root.addWidget(self._error_frame)

        # Aucune clé saisie : explication et accès direct à la saisie, à la
        # place de la zone vide sous le champ de recherche.
        self._no_licence_frame = QWidget()
        no_licence_layout = QVBoxLayout(self._no_licence_frame)
        no_licence_layout.addWidget(_plain_label(tr("no_licence_title"), role="title"))
        no_licence_layout.addWidget(_plain_label(tr("no_licence_message"), role="secondary", wrap=True))
        self._no_licence_button = QPushButton(tr("enter_licence_button"))
        self._no_licence_button.setProperty("role", "primary")
        self._no_licence_button.clicked.connect(self.settings_requested.emit)
        no_licence_layout.addWidget(self._no_licence_button, alignment=Qt.AlignLeft)
        root.addWidget(self._no_licence_frame)

        # Zones de message à leur hauteur naturelle, en haut : sans ça, tant
        # que la zone de résultat (seule extensible) est masquée, Qt étirait
        # chacune sur toute la hauteur -- titre, texte et boutons éparpillés
        # avec de grands vides entre eux (constaté au rendu). L'espace restant
        # va au ressort final, qui ne prend rien quand un résultat s'affiche
        # (facteur 0 contre 1 pour `_result_frame`).
        for frame in (self._no_info_frame, self._error_frame, self._no_licence_frame):
            frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addStretch(0)

        self._zone = "idle"
        self._show_zone("idle")

    # --- Configuration réseau ------------------------------------------

    def set_network_config(self, server_url: str, licence_key: str, opener=None) -> None:
        self._server_url = server_url
        self._licence_key = licence_key
        self._opener = opener
        # La clé vient peut-être d'être saisie ou effacée : l'explication
        # « aucune clé » suit sans attendre une nouvelle recherche.
        self._show_zone(self._zone)

    # --- Zones -----------------------------------------------------------

    def _show_zone(self, zone: str) -> None:
        self._zone = zone
        self._status_label.setVisible(zone == "searching")
        self._result_frame.setVisible(zone == "result")
        self._no_info_frame.setVisible(zone == "no_info")
        self._error_frame.setVisible(zone == "error")
        self._no_licence_frame.setVisible(zone == "idle" and not (self._licence_key or "").strip())

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._reference_edit.setEnabled(enabled)
        self._search_button.setEnabled(enabled)

    # --- Recherche ---------------------------------------------------------

    def _lancer_recherche(self) -> None:
        reference = self._reference_edit.text().strip()
        if not reference:
            return
        self._status_label.setText(tr("searching_status"))
        self._set_controls_enabled(False)
        self._show_zone("searching")
        self._slow_search_timer.start()

        runner = ConsoleSearchRunner(reference, self._server_url, self._licence_key, opener=self._opener)
        runner.finished_ok.connect(self._on_search_finished)
        runner.error.connect(self._on_search_error)
        runner.finished.connect(runner.deleteLater)
        self._runner = runner
        runner.start()

    def _on_slow_search_warning(self) -> None:
        self._status_label.setText(tr("searching_status_lente"))

    def _on_search_finished(self, resultat: ResultatRecherche) -> None:
        self._slow_search_timer.stop()
        self._set_controls_enabled(True)
        if resultat.statut == "aucune_information_trouvee":
            self._show_zone("no_info")
            return
        if resultat.console is None:
            self._on_search_error("reponse_invalide", "")
            return
        self._afficher_fiche(resultat.console)
        self._show_zone("result")

    def _on_search_error(self, code: str, message_serveur: str) -> None:
        self._slow_search_timer.stop()
        self._set_controls_enabled(True)
        self._error_label.setText(friendly_error_message(code, message_serveur))
        self._error_licence_button.setVisible(code in _CODES_SAISIE_LICENCE)
        self._show_zone("error")

    # --- Affichage de la fiche ----------------------------------------------

    def _build_header(self, fiche: FicheConsole) -> QWidget:
        frame, layout = _build_card()
        name_row = QHBoxLayout()
        name_row.addWidget(_plain_label(fiche.nom, role="title"))
        name_row.addStretch()
        badge_kind = "available" if fiche.verifiee else "platform_limited"
        badge_text = tr("badge_verified") if fiche.verifiee else tr("badge_unverified")
        name_row.addWidget(_badge_label(badge_text, badge_kind))
        layout.addLayout(name_row)
        if fiche.fabricant.strip().lower() != _VALEUR_INCONNUE:
            layout.addWidget(_plain_label(fiche.fabricant))
        if not fiche.verifiee:
            layout.addWidget(_plain_label(tr("unverified_note"), role="secondary"))
        return frame

    def _build_sources_section(self, sources) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        toggle = QPushButton(f"▸ {tr('sources_title', total=len(sources))}")
        toggle.setProperty("role", "flat")
        toggle.setCheckable(True)
        toggle.setChecked(False)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        for source in sources:
            content_layout.addWidget(_link_widget(source.url), alignment=Qt.AlignLeft)
        content.setVisible(False)

        def _on_toggled(checked: bool) -> None:
            content.setVisible(checked)
            fleche = "▾" if checked else "▸"
            toggle.setText(f"{fleche} {tr('sources_title', total=len(sources))}")

        toggle.toggled.connect(_on_toggled)

        layout.addWidget(toggle, alignment=Qt.AlignLeft)
        layout.addWidget(content)
        return container

    def _afficher_fiche(self, fiche: FicheConsole) -> None:
        _clear_layout(self._result_content_layout)
        layout = self._result_content_layout

        layout.addWidget(self._build_header(fiche))

        info_block = _build_info_block(fiche)
        if info_block is not None:
            layout.addWidget(info_block)

        layout.addWidget(_build_hardware_card(fiche))

        for widget in _build_options_section(fiche):
            layout.addWidget(widget)

        if fiche.sources:
            layout.addWidget(self._build_sources_section(fiche.sources))


__all__ = ["ConsolesDiversesScreen"]
