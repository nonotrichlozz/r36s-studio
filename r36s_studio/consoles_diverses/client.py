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
import hashlib
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


_CODES_LICENCE = {"licence_requise", "licence_invalide", "licence_expiree", "licence_revoquee"}


def _hash_prefix(valeur: str) -> str:
    """8 premiers caractères hexadécimaux du SHA-256 -- jamais la clé
    elle-même, juste assez pour comparer deux valeurs entre elles dans le
    journal (diagnostic demandé). Même fonction que `settings_store.py::
    _hash_prefix` -- non partagée entre les deux modules pour ne pas créer
    de dépendance croisée entre `client.py` et `settings_store.py`, tous
    deux déjà indépendants l'un de l'autre."""
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:8]


def _journaliser_diagnostic_licence(
    licence_key: str,
    code: str,
    *,
    statut_http: int,
    url_demandee: str,
    url_atteinte: str,
) -> None:
    """Diagnostic demandé pour l'enquête « clé confirmée identique à
    l'enregistrement/la relecture/l'envoi (SHA-256), et fonctionnelle via
    `Invoke-RestMethod`, mais refusée par la GUI » -- jamais la clé
    elle-même dans le journal. En plus de la longueur/l'espace parasite/le
    hash déjà en place : l'URL réellement construite pour cette requête
    (`url_demandee`) et celle où l'erreur a finalement été levée
    (`url_atteinte`, `HTTPError.url` -- reflète l'URL *après* une
    éventuelle redirection HTTP suivie silencieusement par `urllib`,
    contrairement à `url_demandee`) et le statut HTTP numérique reçu
    (distinct du code d'erreur `{"erreur": ...}` du corps JSON, déjà
    journalisé). `redirection_suivie` compare les deux URLs -- si elles
    diffèrent, `urllib` a suivi une redirection avant d'atteindre cette
    réponse, ce qui convertit une requête POST en GET et supprime son
    corps (`Content-Type`/`Content-Length`, mais PAS les en-têtes
    personnalisés comme `X-Licence-Key` -- vérifié directement dans le
    code source d'`urllib.request.HTTPRedirectHandler.redirect_request`,
    lu en lecture seule) -- une piste plausible si l'URL configurée
    diffère, même légèrement, de celle validée manuellement.

    À corréler avec le diagnostic *serveur* déjà en place pour cette même
    enquête, `r36s-studio-cloud/worker/src/routes/recherche.ts::
    logLicenceDiagnostic` (lu en lecture seule, jamais modifié depuis ce
    dépôt) -- visible via `wrangler tail`, il journalise côté Worker la
    liste des en-têtes réellement reçus, la présence/longueur/hash de
    `X-Licence-Key` tel que *le serveur* le voit, le hash de la clé
    attendue, et l'URL/`User-Agent` de la requête reçue. Comparer les deux
    journaux (client ici, serveur via `wrangler tail`) pour la même
    requête tranche entre un problème d'émission (ce module) et un
    problème de réception/configuration côté Worker.

    Même journal best-effort que `_journaliser_erreur_http_inattendue`
    (un journal inaccessible ne doit jamais empêcher l'erreur de remonter
    normalement)."""
    try:
        chemin = gui_logs.consoles_diverses_log_path()
        horodatage = datetime.datetime.now().isoformat(timespec="seconds")
        contient_espace = licence_key != licence_key.strip()
        redirection_suivie = url_demandee != url_atteinte
        with open(chemin, "a", encoding="utf-8") as fichier:
            fichier.write(
                f"{horodatage} diagnostic licence : longueur={len(licence_key)}, "
                f"espace_parasite={contient_espace}, sha256_envoyee={_hash_prefix(licence_key)}, "
                f"code_serveur={code!r}, statut_http={statut_http}, "
                f"url_demandee={url_demandee!r}, url_atteinte={url_atteinte!r}, "
                f"redirection_suivie={redirection_suivie}\n"
            )
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
    injoignable, délai dépassé, réponse invalide/trop grande).

    **Vérifié directement (enquête « clé identique de bout en bout, mais
    refusée par la GUI »), les trois points suivants sont corrects et ne
    sont pas la cause -- capturé sur un vrai socket local, `git blame`
    de cette note en garde la preuve pour ne pas les réinvestiguer :**
    - **URL finale.** `server_url.rstrip("/") + "/recherche"` ne produit
      jamais de barre oblique double ni de segment manquant, que
      `server_url` se termine par `/` ou non.
    - **En-tête `X-Licence-Key`.** `Request.add_header` le stocke en
      interne sous une casse mutilée (`.capitalize()`, ex.
      `X-licence-key`), mais `AbstractHTTPHandler.do_open` retitre TOUS
      les en-têtes (`.title()`) juste avant l'envoi -- le nom réellement
      posé sur le fil est bien `X-Licence-Key`, casse restaurée. Sans
      incidence de toute façon : les noms d'en-tête HTTP sont
      insensibles à la casse par spécification, et l'API `Headers` de
      Cloudflare Workers les normalise en minuscules à la réception,
      quelle que soit la casse envoyée.
    - **Encodage du corps.** `json.dumps(..., ensure_ascii=True)` (défaut)
      échappe tout caractère non-ASCII en `\\uXXXX` avant l'`.encode
      ("utf-8")` -- le corps posté est donc toujours de l'ASCII pur,
      jamais un problème de charset malgré l'absence de paramètre
      `charset` explicite sur `Content-Type` (JSON est UTF-8 par défaut
      sans ce paramètre, RFC 8259).

    Une redirection HTTP suivie silencieusement par `urllib` reste elle
    une piste ouverte -- voir `_journaliser_diagnostic_licence` ci-dessus,
    qui la détecte désormais (`redirection_suivie`, comparaison entre
    l'URL demandée et celle où l'erreur a été levée)."""
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
        erreur = _erreur_depuis_corps_http(exc.code, raw_error)
        if erreur.code in _CODES_LICENCE:
            _journaliser_diagnostic_licence(
                licence_key,
                erreur.code,
                statut_http=exc.code,
                url_demandee=url,
                url_atteinte=getattr(exc, "url", None) or url,
            )
        raise erreur from exc
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
