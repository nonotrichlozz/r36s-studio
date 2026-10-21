"""Fenêtre « Choisis le fichier image » sur un petit écran (bug du
2026-10-21, portable 1366×768) : neuf firmwares dépassaient la hauteur de
l'écran, boutons hors cadre ; au redimensionnement, la fenêtre disparaissait
et l'application se bloquait (hauteur minimale plus grande que l'écran,
réimposée en boucle). Hauteur bornée à l'écran disponible, liste qui défile,
boutons toujours visibles, description du seul firmware choisi."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QPushButton, QWidget

from r36s_studio.gui import theme
from r36s_studio.gui.screens import Dialog, FileDialog
from r36s_studio.identify.firmware_catalog import FIRMWARE_CATALOG

# Hauteurs utilisables (pixels logiques, barre des tâches et titre déduits) :
# 1366×768 à 150 %, 1280×720 à 125 %, 1366×768 à 100 %, 1920×1080.
HEIGHTS = (445, 504, 688, 1000)


@pytest.fixture
def styled(qapp):
    previous = qapp.styleSheet()
    qapp.setStyleSheet(theme.STYLESHEET)
    yield qapp
    qapp.setStyleSheet(previous)


def _open(available):
    parent = QWidget()
    parent.resize(1000, 700)
    dialog = FileDialog(parent)
    dialog.set_mode("flash", firmware=FIRMWARE_CATALOG[0].id)
    with patch.object(Dialog, "available_height", return_value=available):
        dialog.open()
        for _ in range(5):
            dialog.adjustSize()
    return parent, dialog


@pytest.mark.parametrize("available", HEIGHTS)
def test_the_dialog_and_its_buttons_always_fit_the_screen(styled, available):
    with patch.object(Dialog, "available_height", return_value=available):
        parent, dialog = _open(available)
        assert dialog.maximumHeight() == available
        assert dialog.minimumHeight() <= available and dialog.height() <= available
        for label in ("Parcourir", "Retour", "Suivant", "Voir les versions"):
            button = next(b for b in dialog.findChildren(QPushButton) if b.isVisible() and label in b.text())
            bottom = button.mapTo(dialog, button.rect().bottomLeft()).y()
            assert bottom < dialog.height(), label
        dialog.close()


def test_resizing_below_the_content_never_loops(styled):
    """Chaque redimensionnement ne provoque qu'un nombre borné d'événements,
    même vers une taille plus petite que le contenu."""
    with patch.object(Dialog, "available_height", return_value=445):
        parent, dialog = _open(445)
        seen = []

        class Count(QObject):
            def eventFilter(self, obj, event):
                if event.type() in (QEvent.Resize, QEvent.LayoutRequest):
                    seen.append(event.type())
                return False

        counter = Count()
        dialog.installEventFilter(counter)
        for width, height in ((300, 200), (420, 900), (2000, 100), (480, 445)):
            seen.clear()
            dialog.resize(width, height)
            styled.processEvents()
            assert len(seen) < 10
            assert dialog.height() <= 445
        dialog.close()


def test_only_the_chosen_firmware_shows_its_description(styled):
    parent, dialog = _open(688)
    first, second = FIRMWARE_CATALOG[0].id, FIRMWARE_CATALOG[1].id
    visible = [fid for fid, desc in dialog._firmware_descs.items() if desc.isVisible()]
    assert visible == [first]
    dialog._firmware_radios[second].setChecked(True)
    visible = [fid for fid, desc in dialog._firmware_descs.items() if desc.isVisible()]
    assert visible == [second]
    # Les autres restent lisibles au survol.
    assert all(dialog._firmware_radios[e.id].toolTip() for e in FIRMWARE_CATALOG)
    dialog.close()
