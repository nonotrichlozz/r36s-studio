# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

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
- Tout texte serveur passe par `_plain_label`, qui verrouille
  `setTextFormat(Qt.PlainText)` -- aucun HTML n'est jamais interprété.
- Un lien n'est cliquable que si `_est_url_externe_sure` le confirme --
  strictement `http://`/`https://`, jamais `file:`/`javascript:`/un chemin
  local/un schéma absent, qui restent du texte simple non cliquable."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

from PySide6.QtCore import QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.gui.screens import Screen

from .client import ResultatRecherche
from .models import FicheConsole, OptionConsole
from .search_runner import ConsoleSearchRunner
from .strings import friendly_error_message, tr

MAX_REFERENCE_LENGTH = 64
SLOW_SEARCH_WARNING_DELAY_MS = 15_000

_CATEGORY_TITLE_KEYS = {
    "frontend": "category_frontend",
    "systeme_cfw": "category_systeme_cfw",
    "firmware_origine": "category_firmware_origine",
    "mises_a_jour": "category_mises_a_jour",
}


def _est_url_externe_sure(url: Optional[str]) -> bool:
    """Un lien n'est jamais cliquable que s'il s'agit explicitement d'une
    URL `http://`/`https://` -- une fiche peut être générée par IA, donc
    traitée comme une donnée non fiable. `file:`, `javascript:`, un chemin
    local ou un schéma absent restent du texte simple, jamais un lien ouvert
    automatiquement."""
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


def _link_widget(url: Optional[str]) -> QWidget:
    """Un petit bouton cliquable (jamais un `QLabel` en `RichText` --
    point 1) si `url` est une adresse http(s) sûre (point 2), un simple
    texte non cliquable sinon -- jamais caché pour autant, l'utilisateur
    voit toujours l'adresse brute."""
    if not url:
        return _plain_label("", role="secondary")
    if _est_url_externe_sure(url):
        button = QPushButton(url)
        button.setProperty("role", "flat")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
        return button
    return _plain_label(url, role="secondary", wrap=True)


def _build_restriction_banner() -> QWidget:
    frame = QFrame()
    frame.setProperty("role", "danger")
    layout = QVBoxLayout(frame)
    layout.addWidget(_plain_label(tr("restriction_commerciale_banner"), role="dangerTitle", wrap=True))
    return frame


def _build_info_banner(text: str) -> QWidget:
    frame = QFrame()
    frame.setProperty("role", "banner")
    layout = QVBoxLayout(frame)
    layout.addWidget(_plain_label(text, role="secondary", wrap=True))
    return frame


def _build_option_widget(option: OptionConsole) -> QWidget:
    container = QFrame()
    container.setProperty("role", "row")
    layout = QVBoxLayout(container)
    layout.addWidget(_plain_label(option.nom, role="rowTitle"))
    layout.addWidget(_plain_label(option.description, role="rowDesc", wrap=True))
    if option.licence:
        layout.addWidget(_plain_label(tr("option_licence", valeur=option.licence), role="secondary"))
    if option.licence_a_verifier:
        layout.addWidget(_plain_label(tr("licence_a_verifier_mention"), role="secondary"))
    if option.restriction_commerciale:
        layout.addWidget(_build_restriction_banner())
    if option.url:
        layout.addWidget(_link_widget(option.url), alignment=Qt.AlignLeft)
    if option.source_url:
        layout.addWidget(_plain_label(tr("option_source_url", valeur=option.source_url), role="secondary", wrap=True))
    return container


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


class ConsolesDiversesScreen(Screen):
    """Écran unique de la section (étape 1, mode recherche). `set_network_
    config` doit être appelé (par `MainWindow`, depuis `AppConfig`/
    `settings_store`) avant toute recherche -- valeurs par défaut sûres
    (`http://localhost:8787`, aucune clé) sinon, pour ne jamais lever si
    l'appelant oublie."""

    back_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._server_url = "http://localhost:8787"
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
        result_content = QWidget()
        self._result_content_layout = QVBoxLayout(result_content)
        self._result_frame.setWidget(result_content)
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
        self._retry_error_button = QPushButton(tr("retry_button"))
        self._retry_error_button.clicked.connect(self._lancer_recherche)
        error_layout.addWidget(self._retry_error_button)
        root.addWidget(self._error_frame)

        self._show_zone("idle")

    # --- Configuration réseau ------------------------------------------

    def set_network_config(self, server_url: str, licence_key: str, opener=None) -> None:
        self._server_url = server_url
        self._licence_key = licence_key
        self._opener = opener

    # --- Zones -----------------------------------------------------------

    def _show_zone(self, zone: str) -> None:
        self._status_label.setVisible(zone == "searching")
        self._result_frame.setVisible(zone == "result")
        self._no_info_frame.setVisible(zone == "no_info")
        self._error_frame.setVisible(zone == "error")

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
        self._show_zone("error")

    # --- Affichage de la fiche ----------------------------------------------

    def _afficher_fiche(self, fiche: FicheConsole) -> None:
        _clear_layout(self._result_content_layout)
        layout = self._result_content_layout

        layout.addWidget(_plain_label(fiche.nom, role="title"))

        badge = QLabel(tr("badge_verified") if fiche.verifiee else tr("badge_unverified"))
        badge.setTextFormat(Qt.PlainText)
        badge.setProperty("role", "badge")
        badge.setProperty("badgeKind", "available" if fiche.verifiee else "platform_limited")
        layout.addWidget(badge)

        if not fiche.verifiee:
            layout.addWidget(_build_info_banner(tr("unverified_banner")))

        if fiche.a_une_restriction_commerciale:
            layout.addWidget(_build_restriction_banner())

        layout.addWidget(_plain_label(tr("identity_fabricant", valeur=fiche.fabricant)))
        layout.addWidget(_plain_label(tr("identity_soc", valeur=fiche.soc)))
        layout.addWidget(_plain_label(tr("identity_architecture", valeur=fiche.architecture)))
        layout.addWidget(_plain_label(tr("identity_os_type", valeur=fiche.os_type)))

        for key, options in fiche.options.toutes_les_categories():
            layout.addWidget(_plain_label(tr(_CATEGORY_TITLE_KEYS[key]), role="title"))
            if not options:
                layout.addWidget(_plain_label(tr("category_empty"), role="secondary"))
            for option in options:
                layout.addWidget(_build_option_widget(option))

        if fiche.incompatibles:
            layout.addWidget(_plain_label(tr("incompatibles_title"), role="title"))
            for incompatible in fiche.incompatibles:
                layout.addWidget(
                    _plain_label(f"{incompatible.nom} — {incompatible.raison}", role="dangerMessage", wrap=True)
                )

        if fiche.sources:
            layout.addWidget(_plain_label(tr("sources_title"), role="title"))
            for source in fiche.sources:
                layout.addWidget(_link_widget(source.url))


__all__ = ["ConsolesDiversesScreen"]
