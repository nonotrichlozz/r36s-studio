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
charger une réponse de taille arbitraire en mémoire.

Envoie toujours un en-tête `User-Agent` explicite (`USER_AGENT` ci-dessous)
-- bug corrigé, confirmé en isolant la différence entre le serveur local et
le serveur distant (HTTPS, derrière Cloudflare) pour une même recherche :
sans cet en-tête, `urllib.request` retombe sur `"Python-urllib/{version}"`,
une signature que Cloudflare bloque par défaut (403, `error code: 1010`)
avant même que la requête n'atteigne le Worker -- jamais un problème côté
serveur local, qui n'a pas Cloudflare devant lui.

Un échec HTTP dont le corps n'est pas la forme JSON `{"erreur": ...}`
attendue (`_erreur_depuis_corps_http` retombe alors sur `reponse_
invalide`, générique) est consigné dans le même journal que les fiches
rejetées (`models.py::_journaliser_fiche_rejetee`,
`gui/logs.py::consoles_diverses_log_path`) -- exactement le genre
d'incident qui a motivé cet ajout (le blocage Cloudflare ci-dessus s'est
d'abord confondu avec un bug serveur, faute d'un détail exploitable
côté client). Jamais affiché à l'écran (§CLAUDE.md du package) ; un code
`{"erreur": ...}` bien formé du serveur (licence invalide, référence
invalide...) n'est lui jamais un incident, donc jamais journalisé ici."""

from __future__ import annotations

import datetime
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional

from r36s_studio import __version__
from r36s_studio.gui import logs as gui_logs

from .models import FicheConsole, fiche_depuis_json

REQUEST_TIMEOUT_SECONDS = 90
MAX_RESPONSE_BYTES = 1024 * 1024  # 1 Mio (durcissement demandé, point 4)

# Bug corrigé, confirmé en isolant la différence local/distant (curl avec
# différents en-têtes `User-Agent`, même requête sinon identique) : le
# serveur en HTTPS (`*.workers.dev`, derrière Cloudflare) répondait
# `403` + `error code: 1010` -- Cloudflare bloque par défaut certaines
# signatures `User-Agent` connues de bibliothèques HTTP de script,
# *avant même que la requête n'atteigne le Worker*. `urllib.request` ne
# fixe aucun en-tête `User-Agent` explicite par défaut : `OpenerDirector`
# retombe alors sur `"Python-urllib/{version}"`, une des signatures
# bloquées. Le serveur local (`http://localhost:8787`, sans Cloudflare
# devant) n'est jamais concerné -- d'où l'écart observé entre les deux
# adresses pour une requête par ailleurs identique. `python-requests/...`
# n'est PAS bloqué (vérifié directement) : ni la compression (aucun
# `Content-Encoding` sur la réponse, vérifié aussi), ni l'URL, ni le
# corps ne sont en cause -- uniquement cet en-tête, jamais envoyé
# jusqu'ici. Un en-tête `User-Agent` identifiable et fixe (jamais une
# signature de navigateur usurpée) suffit à passer -- même principe déjà
# suivi côté serveur pour ses propres requêtes sortantes vers GitHub/
# Handhelds Wiki (`r36s-studio-cloud/lib/sources/userAgent.ts`, lu en
# lecture seule).
USER_AGENT = f"R36S-Studio/{__version__}"

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


_EXTRAIT_JOURNAL_MAX_OCTETS = 200


def _journaliser_erreur_http_inattendue(status: int, raw: bytes) -> None:
    """Consigne un échec HTTP dont le corps n'est pas la forme JSON
    `{"erreur": ...}` attendue -- même journal que les fiches rejetées
    (`models.py::_journaliser_fiche_rejetee`), même principe best-effort
    (un journal inaccessible ne doit jamais empêcher l'erreur de remonter
    normalement). Cas réel qui a motivé cet ajout : Cloudflare bloquait la
    requête (403, `error code: 1010`, corps texte brut) avant même qu'elle
    n'atteigne le Worker -- sans ce détail, ça se lit comme un bug serveur
    aléatoire plutôt que comme ce que c'est vraiment. L'extrait est tronqué
    (`_EXTRAIT_JOURNAL_MAX_OCTETS`) : jamais besoin du corps entier pour
    identifier la cause, et ce journal ne doit pas grossir sans limite."""
    try:
        chemin = gui_logs.consoles_diverses_log_path()
        horodatage = datetime.datetime.now().isoformat(timespec="seconds")
        extrait = raw[:_EXTRAIT_JOURNAL_MAX_OCTETS].decode("utf-8", errors="replace")
        with open(chemin, "a", encoding="utf-8") as fichier:
            fichier.write(f"{horodatage} erreur HTTP {status} inattendue : {extrait!r}\n")
    except OSError:
        pass


def _erreur_depuis_corps_http(status: int, raw: bytes) -> RechercheErreur:
    try:
        payload = json.loads(raw)
    except ValueError:
        _journaliser_erreur_http_inattendue(status, raw)
        return RechercheErreur("reponse_invalide")
    if not isinstance(payload, dict):
        _journaliser_erreur_http_inattendue(status, raw)
        return RechercheErreur("reponse_invalide")
    code = payload.get("erreur")
    if not isinstance(code, str) or not code:
        _journaliser_erreur_http_inattendue(status, raw)
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
            "User-Agent": USER_AGENT,
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
        raise _erreur_depuis_corps_http(exc.code, raw_error) from exc
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
    "USER_AGENT",
    "Opener",
    "RechercheErreur",
    "ResultatRecherche",
    "rechercher_console",
]
