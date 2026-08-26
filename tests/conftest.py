"""Fixtures partagées. `qapp` fournit une QApplication unique pour toute la
session (Qt n'en autorise qu'une par processus), en mode "offscreen" pour
ne pas dépendre d'un vrai écran (CI, machines sans affichage)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
