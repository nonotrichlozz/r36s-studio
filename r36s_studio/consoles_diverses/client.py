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

"""Client HTTP pour `POST /recherche` du serveur `r36s-studio-cloud` (lu en
lecture seule : `r36s-studio-cloud/README.md`, jamais `.dev.vars`). Comme
`identify/rocknix.py` (seul autre module réseau du dépôt), toute
communication passe par un paramètre `opener` injectable plutôt que
`urllib.request.urlopen` appelé en dur -- les tests ne dépendent ainsi
jamais d'un accès réseau réel. Contrairement à `rocknix.py` (simples GET),
l'opener ici reçoit directement un `urllib.request.Request` déjà construit
(méthode, en-têtes, corps) plutôt qu'une simple URL, puisque l'appel est un
POST avec en-tête d'authentification et corps JSON.

La fiche renvoyée par le serveur est une donnée externe non fiable (elle
peut être générée par IA, §CLAUDE.md du package) : la réponse est plafonnée
à `MAX_RESPONSE_BYTES` avant tout `json.loads`, pour ne jamais tenter de
charger une réponse de taille arbitraire en mémoire."""

from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .models import FicheConsole, fiche_depuis_json

REQUEST_TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 Mio (durcissement demandé, point 4)

_STATUTS_CONNUS = {"trouve_dans_catalogue", "trouve_par_ia", "aucune_information_trouvee"}

Opener = Callable[[urllib.request.Request], Any]


class RechercheErreur(Exception):
    """Erreur remontée par `rechercher_console` -- `code` est soit le code
    brut renvoyé par le serveur (`reference_invalide`, `licence_requise`...,
    voir r36s-studio-cloud/README.md), soit un code synthétisé côté client
    pour un cas que le serveur ne peut pas produire lui-même
    (`serveur_injoignable`, `delai_depasse`, `reponse_invalide`).
    `message_serveur` porte le champ `message` optionnel du corps d'erreur
    (ex. `recherche_ia_indisponible`), jamais un détail technique brut."""

    def __init__(self, code: str, message_serveur: Optional[str] = None):
        super().__init__(code)
        self.code = code
        self.message_serveur = message_serveur


@dataclass
class ResultatRecherche:
    statut: str
    console: Optional[FicheConsole]
    pr_creee: Optional[bool] = None


def _default_opener(request: urllib.request.Request):
    return urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS)


def _read_limited(response: Any) -> bytes:
    """Lit au plus `MAX_RESPONSE_BYTES` + 1 octets -- une réponse qui
    atteint ou dépasse cette limite est traitée comme invalide avant toute
    tentative de parsing JSON (durcissement demandé, point 4)."""
    data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise RechercheErreur("reponse_invalide")
    return data


def _est_timeout(reason: Any) -> bool:
    return isinstance(reason, (socket.timeout, TimeoutError))


def _erreur_depuis_corps_http(raw: bytes) -> RechercheErreur:
    try:
        payload = json.loads(raw)
    except ValueError:
        return RechercheErreur("reponse_invalide")
    if not isinstance(payload, dict):
        return RechercheErreur("reponse_invalide")
    code = payload.get("erreur")
    if not isinstance(code, str) or not code:
        return RechercheErreur("reponse_invalide")
    message = payload.get("message")
    return RechercheErreur(code, message if isinstance(message, str) else None)


def rechercher_console(
    reference: str,
    server_url: str,
    licence_key: str,
    *,
    opener: Opener = _default_opener,
) -> ResultatRecherche:
    """Appelle `POST {server_url}/recherche` avec `{"reference": reference}`
    et l'en-tête `X-Licence-Key` (toujours envoyé, même vide -- le serveur
    décide lui-même s'il en a besoin pour ce statut précis). Lève
    `RechercheErreur` pour tout cas d'échec listé dans
    `r36s-studio-cloud/README.md`, plus les cas propres au client (serveur
    injoignable, délai dépassé, réponse invalide/trop grande)."""
    url = server_url.rstrip("/") + "/recherche"
    body = json.dumps({"reference": reference}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Licence-Key": licence_key or "",
        },
        method="POST",
    )

    try:
        with opener(request) as response:
            raw = _read_limited(response)
    except urllib.error.HTTPError as exc:
        try:
            raw_error = _read_limited(exc)
        except RechercheErreur:
            raise
        raise _erreur_depuis_corps_http(raw_error) from exc
    except urllib.error.URLError as exc:
        if _est_timeout(exc.reason):
            raise RechercheErreur("delai_depasse") from exc
        raise RechercheErreur("serveur_injoignable") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise RechercheErreur("delai_depasse") from exc
    except OSError as exc:
        raise RechercheErreur("serveur_injoignable") from exc

    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise RechercheErreur("reponse_invalide") from exc
    if not isinstance(payload, dict):
        raise RechercheErreur("reponse_invalide")

    statut = payload.get("statut")
    if statut not in _STATUTS_CONNUS:
        raise RechercheErreur("reponse_invalide")

    console: Optional[FicheConsole] = None
    if statut in ("trouve_dans_catalogue", "trouve_par_ia"):
        try:
            console = fiche_depuis_json(payload.get("console"))
        except ValueError as exc:
            raise RechercheErreur("reponse_invalide") from exc

    pr_creee = payload.get("pr_creee")
    if not isinstance(pr_creee, bool):
        pr_creee = None

    return ResultatRecherche(statut=statut, console=console, pr_creee=pr_creee)


__all__ = [
    "REQUEST_TIMEOUT_SECONDS",
    "MAX_RESPONSE_BYTES",
    "Opener",
    "RechercheErreur",
    "ResultatRecherche",
    "rechercher_console",
]
