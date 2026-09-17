"""Tests de `consoles_diverses/strings.py::friendly_error_message` --
correspondance code d'erreur -> message clair pour un débutant."""

from __future__ import annotations

from r36s_studio.consoles_diverses.strings import friendly_error_message


def test_ia_surchargee_has_a_dedicated_friendly_message():
    message = friendly_error_message("ia_surchargee", "")

    assert message == "Le service de recherche est surchargé pour le moment. Réessaie dans quelques minutes."


def test_delai_depasse_message_mentions_the_new_client_timeout():
    message = friendly_error_message("delai_depasse", "")

    assert "90 secondes" in message
