"""Tests de gui/strings.py — fichier de traduction isolé (§5)."""

from __future__ import annotations

import pytest

from r36s_studio.gui.strings import STRINGS, tr


def test_tr_returns_plain_string_without_placeholders():
    assert tr("app_title") == "R36S Studio"


def test_tr_interpolates_kwargs():
    result = tr("confirm_erase", display="Carte X", size_go=12.345)
    assert "Carte X" in result
    assert "12.3" in result


def test_tr_unknown_key_raises():
    with pytest.raises(KeyError):
        tr("clef_qui_n_existe_pas")


def test_no_technical_jargon_in_visible_strings():
    """Vocabulaire (§5) : pas de terme technique dans les chaînes
    visibles."""
    forbidden = ["/dev/", "\\\\.\\physicaldrive", "périphérique bloc", "partition"]
    for key, template in STRINGS.items():
        lowered = template.lower()
        for term in forbidden:
            assert term not in lowered, f"{key!r} contient un terme technique : {term!r}"
