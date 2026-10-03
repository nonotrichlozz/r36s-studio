# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Feuille de style Qt centralisée (§5) : habillage « poste de commande »
sombre et technique, inspiré des interfaces de console de jeu rétro. Toute
la palette vit ici, sous forme de constantes nommées — un seul fichier à
modifier pour l'ajuster, plutôt que des couleurs éparpillées dans chaque
écran. `gui/app.py` applique `STYLESHEET` une fois, globalement
(`QApplication.setStyleSheet`).

Contraintes délibérées (demandées explicitement) : aucune lueur, ombre
portée ni dégradé — Qt les rend mal (aliasing grossier, artefacts sur les
bords arrondis) et ça nuit à la lisibilité sur une palette déjà sombre.
Des surfaces plates, des bordures fines, une seule couleur d'accent (le
cyan) réutilisée pour les bordures actives, les barres de progression et
les icônes.

Les écrans (`screens.py`) ne posent jamais de couleur en dur : ils fixent
un rôle (`role`) ou un statut (`badgeKind`) via `setProperty`, et cette
feuille de style décide de l'apparence à partir de là. `repolish()` est
nécessaire après un `setProperty` sur un widget déjà affiché — Qt
n'applique les sélecteurs `[propriété="valeur"]` qu'au moment où le style
est recalculé, pas à chaque changement de propriété."""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

# --- Palette -----------------------------------------------------------

BG_DARK = "#0A1420"  # fond général
SURFACE = "#12222F"  # surfaces (cadres, lignes d'étape, champs)
SURFACE_RAISED = "#182C3B"  # survol/pression d'une ligne cliquable
BORDER = "#22384A"  # bordures neutres, non actives
BORDER_CYAN = "#2DD4E8"  # bordures actives -- couleur d'accent
TEXT_PRIMARY = "#F2F6F8"  # blanc cassé
TEXT_SECONDARY = "#7C93A6"  # gris-bleu
ACCENT_CYAN = "#2DD4E8"

# Badges de statut (écran d'accueil, §5) : fond et texte assortis, jamais
# de dégradé -- une seule teinte plate par statut.
STATUS_AVAILABLE_BG = "#173226"
STATUS_AVAILABLE_FG = "#4ADE80"  # vert
STATUS_DONE_BG = "#1E2A33"
STATUS_DONE_FG = "#8CA3B4"  # gris-bleu clair
STATUS_PLATFORM_LIMITED_BG = "#332310"
STATUS_PLATFORM_LIMITED_FG = "#F0A94E"  # orange
STATUS_NOT_RELEVANT_BG = "#18212A"
STATUS_NOT_RELEVANT_FG = "#4C5D6B"
# Distinct de PLATFORM_LIMITED (orange, limite de l'OS) : ici la raison est
# la carte elle-même (un système qui ne gère pas cette étape du tout), pas
# la plateforme -- teinte violette pour ne pas laisser croire que changer
# d'OS résoudrait quoi que ce soit.
STATUS_SYSTEM_INCOMPATIBLE_BG = "#241C33"
STATUS_SYSTEM_INCOMPATIBLE_FG = "#B98CF0"  # violet

DANGER_BG = "#2A1214"  # écran de confirmation (§5 point 4)
DANGER_BORDER = "#5A2328"
DANGER_FG = "#F87171"  # texte/pastille rouge sur fond sombre (chip "non commerciale")

# Encadré orange (fiche "Consoles diverses", bloc "À savoir") -- réutilise la
# même teinte que le badge d'étape "PLATFORM_LIMITED" ci-dessus, pas une
# nouvelle couleur pour le même signal de prudence (une seule couleur
# d'accent, §5).
WARNING_BG = STATUS_PLATFORM_LIMITED_BG
WARNING_BORDER = STATUS_PLATFORM_LIMITED_FG

LOG_BG = "#07101A"  # journal de bord (écran Exécution)
LOG_TEXT = "#8CF5B0"  # vert clair

FONT_FAMILY = "-apple-system, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
MONO_FONT_FAMILY = "'SF Mono', Menlo, Consolas, 'Courier New', monospace"


def repolish(widget: QWidget) -> None:
    """À appeler après `setProperty(...)` sur un widget déjà affiché, pour
    que la feuille de style réévalue ses sélecteurs `[propriété="valeur"]`
    -- un `setProperty` seul ne suffit pas une fois le widget déjà rendu
    (ex. badge de statut qui change au rafraîchissement de l'accueil)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


STYLESHEET = f"""
/* Un `QWidget` nu n'honore `background-color` en feuille de style que
   si l'attribut WA_StyledBackground est posé (piège Qt classique) --
   `screens.Screen`, la classe de base commune à tous les écrans, le pose
   une fois pour toutes, pour que chaque écran peigne son propre fond
   quel que soit son contexte d'affichage (fenêtre principale ou rendu
   isolé, ex. tests visuels). */
QMainWindow, QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_PRIMARY};
    font-family: {FONT_FAMILY};
    font-size: 13px;
}}

QLabel {{
    background: transparent;
}}

QLabel[role="title"] {{
    font-size: 19px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

QLabel[role="secondary"] {{
    color: {TEXT_SECONDARY};
}}

QLabel[role="rowTitle"] {{
    font-size: 13px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}

QLabel[role="rowDesc"] {{
    font-size: 12px;
    color: {TEXT_SECONDARY};
}}

QPushButton {{
    background-color: {SURFACE};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 7px 14px;
}}
QPushButton:hover {{
    border-color: {BORDER_CYAN};
}}
QPushButton:pressed {{
    background-color: {SURFACE_RAISED};
}}
QPushButton:disabled {{
    color: {TEXT_SECONDARY};
    border-color: {BORDER};
}}
QPushButton[role="primary"] {{
    border: 1px solid {BORDER_CYAN};
    color: {ACCENT_CYAN};
}}
QPushButton[role="flat"] {{
    border: none;
    padding: 2px 4px;
    color: {TEXT_SECONDARY};
}}
QPushButton[role="flat"]:hover {{
    color: {ACCENT_CYAN};
}}
QPushButton[role="cta"] {{
    background-color: {ACCENT_CYAN};
    color: {BG_DARK};
    border: none;
    border-radius: 10px;
    padding: 14px 32px;
    font-weight: bold;
}}
QPushButton[role="cta"]:hover {{
    background-color: {TEXT_PRIMARY};
}}
QPushButton[role="cta"]:pressed {{
    background-color: {BORDER_CYAN};
}}

/* Lien externe (fiche "Consoles diverses", carte d'option et section
   Sources) : un vrai bouton visible -- bordure, fond légèrement
   contrasté, coins arrondis -- jamais confondu avec du texte simple
   comme le `role="flat"` utilisé ailleurs (signalé : « Ouvrir la page »
   ressemblait à du texte). Trois teintes croissantes au repos/survol/
   pression, même principe que le `QPushButton` générique ci-dessus. */
QPushButton[role="link"] {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 5px 12px;
    color: {ACCENT_CYAN};
    text-align: left;
}}
QPushButton[role="link"]:hover {{
    background-color: {SURFACE_RAISED};
    border-color: {BORDER_CYAN};
}}
QPushButton[role="link"]:pressed {{
    background-color: {BORDER};
    border-color: {BORDER_CYAN};
}}

/* Cadre du bandeau carte (accueil) et des lignes d'étape -- même surface,
   coins arrondis, bordure neutre au repos, cyan pour le bandeau (toujours
   actif) et au survol d'une ligne cliquable. */
QFrame[role="banner"] {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_CYAN};
    border-radius: 10px;
}}
QFrame[role="row"] {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame[role="row"]:hover {{
    border-color: {BORDER_CYAN};
}}
/* Pendant une opération (§5, refonte navigation) : les six étapes (et la
   sauvegarde) sont désactivées plutôt que masquées -- une ligne plus
   sombre que la surface habituelle, pour se distinguer d'une ligne au
   repos normale (dont la bordure ne change qu'au survol, pas assez
   visible seule pour signaler "indisponible"). */
QFrame[role="row"]:disabled {{
    background-color: {BG_DARK};
}}
QLabel:disabled {{
    color: {TEXT_SECONDARY};
}}

/* Tuiles de l'accueil assisté (§5, refonte menu de tuiles) : même
   famille que QFrame[role="row"] ci-dessus (surface/bordure/hover),
   déclinée en trois rôles -- normale, mise en avant (l'action
   principale, tuile 1), destructive (la seule qui efface, tuile 9). */
QFrame[role="tile"] {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame[role="tile"]:hover {{
    border-color: {BORDER_CYAN};
}}
QFrame[role="tile"]:disabled {{
    background-color: {BG_DARK};
}}
QFrame[role="tileEmphasized"] {{
    background-color: {ACCENT_CYAN};
    border: none;
    border-radius: 10px;
}}
QFrame[role="tileEmphasized"]:disabled {{
    background-color: {SURFACE};
}}
QFrame[role="tileDestructive"] {{
    background-color: {DANGER_BG};
    border: 1px solid {DANGER_BORDER};
    border-radius: 10px;
}}
QFrame[role="tileDestructive"]:hover {{
    border-color: {DANGER_FG};
}}
QFrame[role="tileDestructive"]:disabled {{
    background-color: {BG_DARK};
}}
/* Libellé bas-gauche d'une tuile -- couleur par défaut surchargée sur
   fond plein (tuile 1) et sur fond danger (tuile 9), pour rester lisible
   sur ces deux fonds non neutres. */
QLabel[role="tileLabel"] {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
}}
QFrame[role="tileEmphasized"] QLabel[role="tileLabel"] {{
    color: {BG_DARK};
}}
QFrame[role="tileDestructive"] QLabel[role="tileLabel"] {{
    color: {DANGER_FG};
}}
/* Tuile 1 (« Préparer ma carte ») uniquement -- seule tuile qui porte une
   description sous son libellé, l'un comme l'autre plus grands que le
   reste de la grille (§5, correctif visuel : « c'est l'icône qui doit
   porter la tuile », mais la tuile mise en avant reste un cran au-dessus
   du reste). */
QLabel[role="tileLabelLarge"] {{
    font-size: 16px;
    font-weight: 700;
    color: {BG_DARK};
}}
/* Description de la tuile 1 uniquement -- `BG_DARK` comme le libellé
   ci-dessus, jamais `role="rowDesc"` (TEXT_SECONDARY, illisible sur le
   fond cyan plein de cette tuile -- correctif visuel demandé). */
QLabel[role="tileDescLarge"] {{
    font-size: 11px;
    color: {BG_DARK};
}}

/* En-tête de l'accueil assisté (§5, refonte menu de tuiles) : nom de
   l'application, espacement des lettres géré en Python
   (`QFont.setLetterSpacing` -- non supporté par Qt Style Sheets,
   contrairement à CSS). */
QLabel[role="brandTitle"] {{
    font-size: 22px;
    font-weight: 700;
    color: {ACCENT_CYAN};
}}
/* Étiquette de section au-dessus de la grille de tuiles (« POUR
   COMMENCER », maquette de référence) -- lettres espacées (Python,
   `QFont.setLetterSpacing`, même raison que `brandTitle`), petite et
   discrète. */
QLabel[role="sectionLabel"] {{
    font-size: 11px;
    font-weight: 600;
    color: {TEXT_SECONDARY};
}}

QLabel[role="stepIcon"] {{
    border: 1px solid {BORDER_CYAN};
    border-radius: 6px;
    color: {ACCENT_CYAN};
    font-weight: 700;
    font-size: 14px;
    qproperty-alignment: AlignCenter;
}}

/* Pastilles de statut (§5) : forme de capsule (rayon >= moitié de la
   hauteur) plutôt qu'un simple rectangle arrondi. */
QLabel[role="badge"] {{
    border-radius: 9px;
    min-height: 16px;
    padding: 2px 12px;
    font-size: 11px;
    font-weight: 600;
    qproperty-alignment: AlignCenter;
}}
QLabel[badgeKind="available"] {{ background-color: {STATUS_AVAILABLE_BG}; color: {STATUS_AVAILABLE_FG}; }}
QLabel[badgeKind="done"] {{ background-color: {STATUS_DONE_BG}; color: {STATUS_DONE_FG}; }}
QLabel[badgeKind="platform_limited"] {{ background-color: {STATUS_PLATFORM_LIMITED_BG}; color: {STATUS_PLATFORM_LIMITED_FG}; }}
QLabel[badgeKind="not_relevant"] {{ background-color: {STATUS_NOT_RELEVANT_BG}; color: {STATUS_NOT_RELEVANT_FG}; }}
QLabel[badgeKind="system_incompatible"] {{ background-color: {STATUS_SYSTEM_INCOMPATIBLE_BG}; color: {STATUS_SYSTEM_INCOMPATIBLE_FG}; }}
/* Statut des firmwares (§4.6, catalogue) : mêmes tons que les pastilles
   d'étape ci-dessus -- même signal bon/neutre/prudence, pas de nouvelle
   couleur pour la même signification (une seule couleur d'accent, §5). */
QLabel[badgeKind="maintained"] {{ background-color: {STATUS_AVAILABLE_BG}; color: {STATUS_AVAILABLE_FG}; }}
QLabel[badgeKind="archived"] {{ background-color: {STATUS_DONE_BG}; color: {STATUS_DONE_FG}; }}
QLabel[badgeKind="experimental"] {{ background-color: {STATUS_PLATFORM_LIMITED_BG}; color: {STATUS_PLATFORM_LIMITED_FG}; }}
/* Pastilles de carte d'option (fiche "Consoles diverses") : licence (ton
   neutre, même surface que le survol d'une ligne) et restriction "non
   commerciale" (rouge, même paire que `role="danger"` ci-dessous). */
QLabel[badgeKind="neutral"] {{ background-color: {SURFACE_RAISED}; color: {TEXT_SECONDARY}; }}
QLabel[badgeKind="danger"] {{ background-color: {DANGER_BG}; color: {DANGER_FG}; }}

QProgressBar {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
    color: {TEXT_PRIMARY};
    min-height: 18px;
}}
QProgressBar::chunk {{
    background-color: {ACCENT_CYAN};
    border-radius: 3px;
}}

QListWidget, QLineEdit {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 4px;
    color: {TEXT_PRIMARY};
}}
QListWidget::item {{
    padding: 4px;
}}
QListWidget::item:selected {{
    background-color: {SURFACE_RAISED};
    border: 1px solid {BORDER_CYAN};
    color: {TEXT_PRIMARY};
}}

QCheckBox {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}
QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 1px solid {BORDER_CYAN};
    border-radius: 3px;
    background-color: {SURFACE};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT_CYAN};
}}

/* Journal de bord, colonne droite (§5, refonte navigation) : cadre à
   bordure cyan (le panneau) contenant la zone de texte -- celle-ci n'a
   pas sa propre bordure (`border: none`), pour ne pas doubler celle du
   panneau qui l'entoure. Seul endroit en police monospace de toute
   l'interface : une console dans la console. */
QFrame[role="logPanel"] {{
    background-color: {SURFACE};
    border: 1px solid {BORDER_CYAN};
    border-radius: 10px;
}}
QLabel[role="logHeader"] {{
    font-weight: 700;
    font-size: 13px;
    color: {ACCENT_CYAN};
}}
QPlainTextEdit[role="log"] {{
    background-color: {LOG_BG};
    color: {LOG_TEXT};
    border: none;
    border-radius: 6px;
    font-family: {MONO_FONT_FAMILY};
    font-size: 11px;
    padding: 6px;
}}

QFrame[role="danger"], QWidget[role="danger"] {{
    background-color: {DANGER_BG};
    border: 1px solid {DANGER_BORDER};
}}

/* Encadré orange -- même rôle que `role="danger"` mais pour un signal de
   prudence plutôt que de danger (fiche "Consoles diverses", bloc « À
   savoir », §docs/consoles-diverses-design.md). */
QFrame[role="warning"], QWidget[role="warning"] {{
    background-color: {WARNING_BG};
    border: 1px solid {WARNING_BORDER};
}}

QLabel[role="dangerTitle"] {{
    font-size: 22px;
    font-weight: 700;
    color: {TEXT_PRIMARY};
}}
QLabel[role="dangerMessage"] {{
    font-size: 15px;
    color: {TEXT_PRIMARY};
}}

QLabel[role="details"] {{
    color: {TEXT_SECONDARY};
    font-family: {MONO_FONT_FAMILY};
    font-size: 11px;
}}

QScrollBar:vertical {{
    background: {BG_DARK};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""
