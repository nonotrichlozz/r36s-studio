"""Tests du numéro de version + horodatage de construction affichés sur
l'écran d'accueil (gui/build_info.py, §5) — sans mock d'un vrai binaire
PyInstaller, seulement de `sys.frozen`/`sys._MEIPASS`."""

from __future__ import annotations

import sys

from r36s_studio import __version__
from r36s_studio.gui import build_info


def test_build_timestamp_is_none_in_dev_mode(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    assert build_info.build_timestamp() is None


def test_build_timestamp_is_none_when_frozen_without_meipass(monkeypatch):
    """`sys.frozen` sans `sys._MEIPASS` ne devrait jamais arriver pour un
    vrai binaire PyInstaller, mais mieux vaut un None prudent qu'une
    exception si ça arrive quand même."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert build_info.build_timestamp() is None


def test_build_timestamp_reads_embedded_file_when_frozen(tmp_path, monkeypatch):
    # encoding="utf-8" explicite : sans lui, l'encodage par défaut de
    # write_text() dépend de la locale de l'OS -- l'ANSI de Windows n'est
    # pas UTF-8, ce que build_info.build_timestamp() lit pourtant en UTF-8
    # explicite (même problème que la production, jamais implicite). Sans
    # ça, ce test écrivait "à" en cp1252 sur Windows, faisant échouer la
    # lecture avec UnicodeDecodeError plutôt que de tester le bon comportement.
    (tmp_path / "build_timestamp.txt").write_text("27/08/2026 à 16:28\n", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert build_info.build_timestamp() == "27/08/2026 à 16:28"


def test_build_timestamp_is_none_when_embedded_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert build_info.build_timestamp() is None


def test_version_label_shows_dev_marker_without_build_timestamp(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    label = build_info.version_label()

    assert f"v{__version__}" in label
    assert "développement" in label


def test_version_label_shows_build_timestamp_when_frozen(tmp_path, monkeypatch):
    (tmp_path / "build_timestamp.txt").write_text("27/08/2026 à 16:28", encoding="utf-8")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    label = build_info.version_label()

    assert f"v{__version__}" in label
    assert "build du 27/08/2026 à 16:28" in label
