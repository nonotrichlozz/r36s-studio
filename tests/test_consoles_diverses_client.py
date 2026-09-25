"""Tests de `consoles_diverses/client.py` -- contrat HTTP de
`POST /recherche` (r36s-studio-cloud/README.md, lu en lecture seule). Toute
communication réseau est mockée via le paramètre `opener` injectable --
jamais un accès réseau réel dans les tests (même principe que
`identify/rocknix.py`/`tests/test_identify_rocknix.py`)."""

from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from r36s_studio.consoles_diverses.client import (
    MAX_RESPONSE_BYTES,
    REQUEST_TIMEOUT_SECONDS,
    RechercheErreur,
    rechercher_console,
)


class _FakeResponse:
    """Contexte minimal imitant `urllib.request.urlopen` (même forme que
    `tests/test_identify_rocknix.py::_FakeResponse`)."""

    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size=None):
        if size is None:
            return self._data
        return self._data[:size]


def _opener_returning(payload: dict):
    body = json.dumps(payload).encode("utf-8")

    def _opener(request: urllib.request.Request):
        assert request.get_method() == "POST"
        assert request.get_header("X-licence-key") is not None
        return _FakeResponse(body)

    return _opener


def _opener_returning_raw(data: bytes):
    def _opener(request: urllib.request.Request):
        return _FakeResponse(data)

    return _opener


def _opener_raising_http_error(status: int, payload: dict):
    body = json.dumps(payload).encode("utf-8")

    def _opener(request: urllib.request.Request):
        raise urllib.error.HTTPError(request.full_url, status, "erreur", None, io.BytesIO(body))

    return _opener


def _opener_raising_http_error_with_non_json_body(status: int, body: bytes):
    def _opener(request: urllib.request.Request):
        raise urllib.error.HTTPError(request.full_url, status, "erreur", None, io.BytesIO(body))

    return _opener


def _opener_raising_http_error_after_redirect(status: int, payload: dict, url_atteinte: str):
    """Simule une redirection HTTP suivie par `urllib` avant d'obtenir cette
    erreur -- `HTTPError.url` reflète alors l'URL *après* redirection,
    différente de celle demandée par `rechercher_console` (même mécanisme
    que `HTTPRedirectHandler.redirect_request`, lu en lecture seule)."""
    body = json.dumps(payload).encode("utf-8")

    def _opener(request: urllib.request.Request):
        raise urllib.error.HTTPError(url_atteinte, status, "erreur", None, io.BytesIO(body))

    return _opener


def _opener_raising(exc: Exception):
    def _opener(request: urllib.request.Request):
        raise exc

    return _opener


def _fiche_minimale() -> dict:
    return {
        "id": "console-x",
        "identite": {"nom": "Console X", "fabricant": "Fabricant", "alias": []},
        "materiel": {"soc": "soc-x", "architecture": "inconnu"},
        "os": {"type": "inconnu"},
        "options": {"frontend": [], "systeme_cfw": [], "firmware_origine": [], "mises_a_jour": []},
        "statut": "non_verifie",
        "signalements": 0,
    }


def test_request_timeout_allows_for_server_retries_and_fallback_models():
    # Le serveur peut désormais tenter plusieurs modèles de secours avant de
    # répondre (jusqu'à ~60 s) -- le client doit laisser une marge confortable
    # au-delà, pas couper juste à la limite observée côté serveur.
    assert REQUEST_TIMEOUT_SECONDS == 90


# --- Statuts 200 -----------------------------------------------------------


def test_rechercher_console_trouve_dans_catalogue():
    fiche = _fiche_minimale()
    fiche["statut"] = "verifie"
    opener = _opener_returning({"statut": "trouve_dans_catalogue", "console": fiche})

    resultat = rechercher_console("RG35XX", "http://localhost:8787", "cle", opener=opener)

    assert resultat.statut == "trouve_dans_catalogue"
    assert resultat.console is not None
    assert resultat.console.verifiee is True


def test_rechercher_console_trouve_par_ia_avec_restriction_commerciale_et_licence_a_verifier():
    fiche = _fiche_minimale()
    fiche["options"]["frontend"] = [
        {
            "nom": "TreeFrog UI",
            "description": "desc",
            "source_url": "https://example.invalid/a",
            "licence": "CC-BY-NC-SA-4.0",
            "licence_a_verifier": True,
            "restriction_commerciale": True,
        }
    ]
    opener = _opener_returning(
        {"statut": "trouve_par_ia", "console": fiche, "pr_creee": False, "connecteurs": {}}
    )

    resultat = rechercher_console("Console inconnue", "http://localhost:8787", "cle", opener=opener)

    assert resultat.statut == "trouve_par_ia"
    assert resultat.pr_creee is False
    assert resultat.console.verifiee is False
    option = resultat.console.options.frontend[0]
    assert option.licence_a_verifier is True
    assert option.restriction_commerciale is True
    assert resultat.console.a_une_restriction_commerciale is True


def test_rechercher_console_aucune_information_trouvee():
    opener = _opener_returning({"statut": "aucune_information_trouvee", "connecteurs": {}})

    resultat = rechercher_console("XYZ", "http://localhost:8787", "cle", opener=opener)

    assert resultat.statut == "aucune_information_trouvee"
    assert resultat.console is None


# --- Erreurs HTTP exactes ---------------------------------------------------


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "reference_invalide"),
        (403, "licence_requise"),
        (403, "licence_invalide"),
        (500, "configuration_manquante"),
        (502, "erreur_api_ia"),
        (502, "reponse_ia_non_json"),
        (503, "ia_surchargee"),
    ],
)
def test_rechercher_console_raises_recherche_erreur_for_known_http_error_codes(status, code):
    opener = _opener_raising_http_error(status, {"erreur": code})

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == code


def test_rechercher_console_recherche_ia_indisponible_conserve_le_message_serveur():
    opener = _opener_raising_http_error(
        503, {"erreur": "recherche_ia_indisponible", "message": "Réessaie demain."}
    )

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "recherche_ia_indisponible"
    assert exc_info.value.message_serveur == "Réessaie demain."


def test_rechercher_console_http_error_with_non_json_body_is_reponse_invalide():
    opener = _opener_raising_http_error_with_non_json_body(500, b"<html>erreur</html>")

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "reponse_invalide"


def test_rechercher_console_http_error_without_erreur_field_is_reponse_invalide():
    opener = _opener_raising_http_error(500, {"quelque_chose": "d_autre"})

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "reponse_invalide"


def test_rechercher_console_logs_an_unexpected_http_error_with_status_and_body(tmp_path):
    """Cas réel qui a motivé cet ajout : Cloudflare bloquait la requête
    HTTPS distante (403, `error code: 1010`, corps texte brut) avant même
    qu'elle n'atteigne le Worker -- confondu un temps avec un bug serveur
    faute de ce détail exploitable côté client. Même journal que les
    fiches rejetées (`gui/logs.py::consoles_diverses_log_path`)."""
    from r36s_studio.consoles_diverses import client as client_module

    log_path = tmp_path / "consoles_diverses.log"
    opener = _opener_raising_http_error_with_non_json_body(403, b"error code: 1010")

    with patch.object(client_module.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        with pytest.raises(RechercheErreur):
            rechercher_console("ref", "https://r36s-studio-cloud.example.workers.dev", "cle", opener=opener)

    contenu = log_path.read_text(encoding="utf-8")
    assert "403" in contenu
    assert "error code: 1010" in contenu


def test_rechercher_console_does_not_log_a_well_formed_server_error(tmp_path):
    """Un code `{"erreur": ...}` bien formé qui n'est pas lié à la licence
    (référence invalide...) n'est jamais un incident -- rien à consigner."""
    from r36s_studio.consoles_diverses import client as client_module

    log_path = tmp_path / "consoles_diverses.log"
    opener = _opener_raising_http_error(400, {"erreur": "reference_invalide"})

    with patch.object(client_module.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        with pytest.raises(RechercheErreur):
            rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert not log_path.exists()


@pytest.mark.parametrize("code", ["licence_invalide", "licence_requise"])
def test_rechercher_console_logs_licence_diagnostic_without_the_key_itself(tmp_path, code):
    """Diagnostic demandé (clé confirmée valide via `Invoke-RestMethod`,
    refusée par la GUI) : longueur, présence d'un espace parasite et code
    serveur consignés -- jamais la clé elle-même."""
    from r36s_studio.consoles_diverses import client as client_module

    log_path = tmp_path / "consoles_diverses.log"
    opener = _opener_raising_http_error(403, {"erreur": code})

    with patch.object(client_module.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        with pytest.raises(RechercheErreur):
            rechercher_console("ref", "http://localhost:8787", " cle-secrete \n", opener=opener)

    contenu = log_path.read_text(encoding="utf-8")
    # Clé extraite dans une variable : un antislash dans l'expression d'une
    # f-string n'est accepté qu'à partir de Python 3.12 (la CI tourne en 3.11).
    cle = " cle-secrete \n"
    assert "cle-secrete" not in contenu
    assert f"longueur={len(cle)}" in contenu
    assert "espace_parasite=True" in contenu
    assert f"sha256_envoyee={client_module._hash_prefix(cle)}" in contenu
    assert code in contenu


def test_rechercher_console_logs_licence_diagnostic_without_stray_whitespace(tmp_path):
    from r36s_studio.consoles_diverses import client as client_module

    log_path = tmp_path / "consoles_diverses.log"
    opener = _opener_raising_http_error(403, {"erreur": "licence_invalide"})

    with patch.object(client_module.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        with pytest.raises(RechercheErreur):
            rechercher_console("ref", "http://localhost:8787", "cle-secrete", opener=opener)

    contenu = log_path.read_text(encoding="utf-8")
    assert "espace_parasite=False" in contenu
    assert f"sha256_envoyee={client_module._hash_prefix('cle-secrete')}" in contenu


def test_rechercher_console_logs_url_and_http_status_without_redirect(tmp_path):
    """Demandé (point 1/4 de l'enquête) : l'URL réellement construite et le
    statut HTTP numérique reçu, en plus du code d'erreur JSON déjà
    consigné -- sans redirection, les deux URLs journalisées sont
    identiques."""
    from r36s_studio.consoles_diverses import client as client_module

    log_path = tmp_path / "consoles_diverses.log"
    opener = _opener_raising_http_error(403, {"erreur": "licence_invalide"})

    with patch.object(client_module.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        with pytest.raises(RechercheErreur):
            rechercher_console("ref", "https://exemple.invalid", "cle-secrete", opener=opener)

    contenu = log_path.read_text(encoding="utf-8")
    assert "statut_http=403" in contenu
    assert "url_demandee='https://exemple.invalid/recherche'" in contenu
    assert "url_atteinte='https://exemple.invalid/recherche'" in contenu
    assert "redirection_suivie=False" in contenu


def test_rechercher_console_logs_a_followed_redirect(tmp_path):
    """Demandé (point 2 de l'enquête) : détecte et journalise une
    redirection HTTP suivie silencieusement par `urllib` avant d'obtenir
    la réponse d'erreur -- `HTTPError.url` diffère alors de l'URL
    initialement construite."""
    from r36s_studio.consoles_diverses import client as client_module

    log_path = tmp_path / "consoles_diverses.log"
    url_atteinte = "https://exemple.invalid/recherche/"
    opener = _opener_raising_http_error_after_redirect(403, {"erreur": "licence_invalide"}, url_atteinte)

    with patch.object(client_module.gui_logs, "consoles_diverses_log_path", return_value=log_path):
        with pytest.raises(RechercheErreur):
            rechercher_console("ref", "https://exemple.invalid", "cle-secrete", opener=opener)

    contenu = log_path.read_text(encoding="utf-8")
    assert "url_demandee='https://exemple.invalid/recherche'" in contenu
    assert f"url_atteinte={url_atteinte!r}" in contenu
    assert "redirection_suivie=True" in contenu


def test_licence_diagnostic_hash_prefix_distinguishes_different_keys():
    """Sanity check du mécanisme de comparaison demandé : deux clés
    différentes ne doivent jamais produire le même préfixe -- sinon le
    diagnostic ne permettrait pas de conclure quoi que ce soit en
    comparant les journaux d'enregistrement et d'envoi."""
    from r36s_studio.consoles_diverses import client as client_module

    assert client_module._hash_prefix("cle-envoyee") != client_module._hash_prefix("cle-enregistree")
    assert client_module._hash_prefix("cle-envoyee") == client_module._hash_prefix("cle-envoyee")


# --- Serveur injoignable / délai dépassé -----------------------------------


def test_rechercher_console_connection_refused_is_serveur_injoignable():
    opener = _opener_raising(urllib.error.URLError(ConnectionRefusedError()))

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "serveur_injoignable"


def test_rechercher_console_timeout_via_urlerror_is_delai_depasse():
    opener = _opener_raising(urllib.error.URLError(socket.timeout("délai dépassé")))

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "delai_depasse"


def test_rechercher_console_direct_timeout_is_delai_depasse():
    opener = _opener_raising(socket.timeout("délai dépassé"))

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "delai_depasse"


def test_rechercher_console_generic_os_error_is_serveur_injoignable():
    opener = _opener_raising(OSError("panne réseau"))

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "serveur_injoignable"


# --- Réponses 200 invalides / trop grandes ----------------------------------


def test_rechercher_console_non_json_success_body_is_reponse_invalide():
    opener = _opener_returning_raw(b"pas du json")

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "reponse_invalide"


def test_rechercher_console_unknown_statut_is_reponse_invalide():
    opener = _opener_returning({"statut": "statut_inconnu"})

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "reponse_invalide"


def test_rechercher_console_console_field_missing_required_field_is_reponse_invalide():
    fiche = _fiche_minimale()
    del fiche["id"]
    opener = _opener_returning({"statut": "trouve_dans_catalogue", "console": fiche})

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "reponse_invalide"


def test_rechercher_console_response_over_size_limit_is_reponse_invalide():
    # Un objet JSON valide mais dont le corps dépasse la limite (point 4 du
    # durcissement) -- rembourré pour dépasser strictement MAX_RESPONSE_BYTES.
    padding = "x" * (MAX_RESPONSE_BYTES + 10)
    opener = _opener_returning({"statut": "aucune_information_trouvee", "remplissage": padding})

    with pytest.raises(RechercheErreur) as exc_info:
        rechercher_console("ref", "http://localhost:8787", "cle", opener=opener)

    assert exc_info.value.code == "reponse_invalide"


def test_rechercher_console_sends_licence_key_header_and_json_body():
    captured = {}

    def _opener(request: urllib.request.Request):
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data)
        captured["url"] = request.full_url
        return _FakeResponse(json.dumps({"statut": "aucune_information_trouvee"}).encode("utf-8"))

    rechercher_console("Ma référence", "http://localhost:8787", "ma-cle", opener=_opener)

    assert captured["url"] == "http://localhost:8787/recherche"
    assert captured["body"] == {"reference": "Ma référence"}
    assert captured["headers"]["X-licence-key"] == "ma-cle"


def test_rechercher_console_sends_an_explicit_user_agent_header():
    """Bug corrigé, confirmé en isolant la différence entre le serveur
    local (fonctionnait) et le serveur distant HTTPS derrière Cloudflare
    (« réponse inattendue ») : sans en-tête `User-Agent` explicite,
    `urllib.request` retombe sur `"Python-urllib/{version}"`, une
    signature bloquée par défaut par Cloudflare (403, `error code:
    1010`) avant même que la requête n'atteigne le Worker -- jamais un
    problème avec le serveur local, qui n'a pas Cloudflare devant lui."""
    from r36s_studio.consoles_diverses.client import USER_AGENT

    captured = {}

    def _opener(request: urllib.request.Request):
        captured["headers"] = dict(request.header_items())
        return _FakeResponse(json.dumps({"statut": "aucune_information_trouvee"}).encode("utf-8"))

    rechercher_console("Ma référence", "https://r36s-studio-cloud.example.workers.dev", "", opener=_opener)

    assert captured["headers"]["User-agent"] == USER_AGENT
    assert "python-urllib" not in captured["headers"]["User-agent"].lower()
