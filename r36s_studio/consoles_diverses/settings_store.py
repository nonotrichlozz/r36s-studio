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

"""Stockage de la clé de licence de la section « Consoles diverses » --
trousseau système (`keyring`), jamais en clair dans `config.py`/`config.
json` (§9 de CLAUDE.md racine : « aucun secret dans le code », même
principe étendu ici à la configuration utilisateur).

**Repli sans trousseau système (durcissement demandé, point 5).** Certains
environnements (typiquement Linux sans `SecretService`/`kwallet` actif)
n'ont aucun backend `keyring` fonctionnel. `trousseau_disponible()` sonde
une fois cet état réel (résultat mis en cache pour la session) ; quand il
est indisponible, la clé n'est **jamais** écrite en clair sur disque à sa
place -- elle reste uniquement dans une variable de module, pour la durée
du processus, à ressaisir au prochain lancement. Vérifié explicitement sur
Windows (Credential Manager, backend natif toujours disponible) ; macOS
(Keychain) et Linux sans trousseau restent à confirmer sur du vrai
matériel -- voir `consoles_diverses/CLAUDE.md`."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

import keyring

from .strings import tr

SERVICE_NAME = "r36s-studio-consoles-diverses"
_LICENCE_ACCOUNT = "licence"

_trousseau_disponible_cache: Optional[bool] = None
_licence_memoire_session: Optional[str] = None


def _sonder_trousseau() -> bool:
    """Tentative de lecture factice -- un compte absent renvoie `None`
    sans lever quand un backend fonctionnel existe ; seule l'absence de
    tout backend utilisable (aucun `SecretService`/`kwallet` sur Linux,
    par exemple) lève une exception ici. Capture volontairement large
    (`Exception`, pas seulement `keyring.errors.KeyringError`) : cette
    sonde ne doit jamais faire planter l'application, quelle que soit la
    cause exacte de l'échec du backend choisi."""
    try:
        keyring.get_password(SERVICE_NAME, _LICENCE_ACCOUNT)
    except Exception:
        return False
    return True


def trousseau_disponible() -> bool:
    """Résultat mis en cache pour la session -- sonder à chaque appel
    interrogerait inutilement le trousseau système à chaque affichage des
    réglages."""
    global _trousseau_disponible_cache
    if _trousseau_disponible_cache is None:
        _trousseau_disponible_cache = _sonder_trousseau()
    return _trousseau_disponible_cache


def reset_trousseau_disponible_cache() -> None:
    """Réservé aux tests -- `trousseau_disponible` met son résultat en
    cache pour la session, ce qu'un scénario de test doit pouvoir remettre
    à zéro entre deux cas (trousseau disponible / indisponible)."""
    global _trousseau_disponible_cache
    _trousseau_disponible_cache = None


def enregistrer_licence(cle: str) -> None:
    """Trousseau système si disponible ; repli mémoire-session sinon
    (jamais en clair sur disque, point 5 du durcissement). Un échec
    d'écriture *malgré* un trousseau détecté comme disponible (rare --
    permission refusée après coup, par exemple) retombe aussi sur la
    mémoire-session plutôt que de lever.

    Bug corrigé, confirmé en conditions réelles : une clé valide (confirmée
    via `Invoke-RestMethod` contre le serveur de production) était refusée
    par la GUI avec `licence_invalide`. Cause : un copier-coller depuis la
    plupart des sources (page web, gestionnaire de mots de passe) laisse
    souvent un espace ou un retour à la ligne parasite en tête/fin, jamais
    retiré avant l'enregistrement -- contrairement à l'adresse du serveur
    (`_on_save` de `settings_dialog.py`, déjà `.strip()`ée). Ce module est
    le seul point de passage entre la fenêtre de réglages et le stockage
    (trousseau ou mémoire-session) : un `.strip()` ici couvre tout appelant
    présent ou futur, pas seulement `settings_dialog.py`."""
    global _licence_memoire_session
    cle = cle.strip()
    if trousseau_disponible():
        try:
            keyring.set_password(SERVICE_NAME, _LICENCE_ACCOUNT, cle)
            return
        except Exception:
            pass
    _licence_memoire_session = cle


def lire_licence() -> Optional[str]:
    if trousseau_disponible():
        try:
            valeur = keyring.get_password(SERVICE_NAME, _LICENCE_ACCOUNT)
        except Exception:
            valeur = None
        if valeur is not None:
            return valeur
    return _licence_memoire_session


def effacer_licence() -> None:
    global _licence_memoire_session
    _licence_memoire_session = None
    if trousseau_disponible():
        try:
            keyring.delete_password(SERVICE_NAME, _LICENCE_ACCOUNT)
        except Exception:
            pass


def valider_adresse_serveur(url: str) -> Optional[str]:
    """Durcissement demandé, point 3 : `https://` toujours accepté ;
    `http://` seulement pour `localhost`/`127.0.0.1` -- sinon la clé de
    licence (en-tête `X-Licence-Key`) circulerait en clair sur le réseau.
    Retourne un message d'erreur clair (à afficher tel quel) si invalide,
    `None` si l'adresse est acceptable."""
    url = (url or "").strip()
    if not url:
        return tr("settings_url_empty")
    try:
        parts = urlsplit(url)
    except ValueError:
        return tr("settings_url_invalid_scheme")
    if parts.scheme == "https":
        return None
    if parts.scheme == "http":
        if parts.hostname in ("localhost", "127.0.0.1"):
            return None
        return tr("settings_url_http_remote_refused")
    return tr("settings_url_invalid_scheme")


__all__ = [
    "SERVICE_NAME",
    "trousseau_disponible",
    "reset_trousseau_disponible_cache",
    "enregistrer_licence",
    "lire_licence",
    "effacer_licence",
    "valider_adresse_serveur",
]
