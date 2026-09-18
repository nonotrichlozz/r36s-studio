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

import datetime
import hashlib
from typing import Optional
from urllib.parse import urlsplit

import keyring

from r36s_studio.gui import logs as gui_logs

from .strings import tr

SERVICE_NAME = "r36s-studio-consoles-diverses"
_LICENCE_ACCOUNT = "licence"

_trousseau_disponible_cache: Optional[bool] = None
_licence_memoire_session: Optional[str] = None


def _hash_prefix(valeur: str) -> str:
    """8 premiers caractères hexadécimaux du SHA-256 -- jamais la clé
    elle-même, juste assez pour comparer deux valeurs entre elles dans le
    journal (diagnostic demandé)."""
    return hashlib.sha256(valeur.encode("utf-8")).hexdigest()[:8]


def _journaliser_diagnostic_enregistrement(cle: str, source: str) -> None:
    """Diagnostic demandé (clé confirmée valide via `Invoke-RestMethod`,
    mais la GUI en envoie apparemment une autre) : consigne le hash de la
    clé qu'on vient de demander d'enregistrer, le hash de ce que le
    trousseau système rend *immédiatement* en relecture directe (sans
    passer par le raccourci mémoire-session ci-dessous -- volontairement,
    pour tester l'aller-retour réel du trousseau lui-même), et la source
    finalement utilisée (`trousseau` ou `memoire`). Jamais la clé en clair.
    Même journal best-effort que les autres diagnostics de ce package
    (`gui/logs.py::consoles_diverses_log_path`)."""
    try:
        chemin = gui_logs.consoles_diverses_log_path()
        horodatage = datetime.datetime.now().isoformat(timespec="seconds")
        relue_trousseau: Optional[str] = None
        if trousseau_disponible():
            try:
                relue_trousseau = keyring.get_password(SERVICE_NAME, _LICENCE_ACCOUNT)
            except Exception:
                relue_trousseau = None
        hash_relue = _hash_prefix(relue_trousseau) if relue_trousseau is not None else "absente"
        with open(chemin, "a", encoding="utf-8") as fichier:
            fichier.write(
                f"{horodatage} diagnostic enregistrement licence : source={source}, "
                f"sha256_demandee={_hash_prefix(cle)}, sha256_trousseau_relue={hash_relue}\n"
            )
    except OSError:
        pass


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
    par la GUI avec `licence_invalide`. Cause n°1 (déjà corrigée) : un
    copier-coller laisse souvent un espace ou un retour à la ligne
    parasite en tête/fin, jamais retiré avant l'enregistrement --
    contrairement à l'adresse du serveur (`_on_save` de
    `settings_dialog.py`, déjà `.strip()`ée).

    Cause n°2, plus grave, trouvée en réexaminant la priorité trousseau/
    mémoire demandée par un signalement où la même valeur (longueur
    stable) était renvoyée après plusieurs ressaisies et un redémarrage :
    `keyring.set_password` peut lever *après* avoir déjà commencé à
    modifier le trousseau -- `WinVaultKeyring.set_password`, entre autres,
    relit et réécrit l'ancienne valeur sous une cible composée avant
    d'écrire la nouvelle (simulation multi-utilisateur, voir le
    commentaire du module `keyring.backends.Windows`) et peut lever à
    cette étape intermédiaire, *avant* que la nouvelle valeur n'ait jamais
    été écrite. L'ancien code retombait alors sur la mémoire-session
    (`_licence_memoire_session = cle`), mais `lire_licence()` continuait
    de préférer une lecture trousseau non vide -- qui rendait toujours
    l'ancienne valeur jamais remplacée, indéfiniment, quel que soit le
    nombre de ressaisies. `_licence_memoire_session` porte donc désormais
    la valeur qui vient d'être explicitement demandée dans tous les cas
    (trousseau ou repli) -- `lire_licence()` la préfère toujours à une
    relecture trousseau pour le reste de la session, ci-dessous."""
    global _licence_memoire_session
    cle = cle.strip()
    _licence_memoire_session = cle
    source = "memoire"
    if trousseau_disponible():
        try:
            keyring.set_password(SERVICE_NAME, _LICENCE_ACCOUNT, cle)
            source = "trousseau"
        except Exception:
            pass
    _journaliser_diagnostic_enregistrement(cle, source)


def lire_licence() -> Optional[str]:
    """Préfère la valeur explicitement enregistrée durant cette session
    (`_licence_memoire_session`, mise à jour par tout appel à
    `enregistrer_licence` -- trousseau ou repli, voir son commentaire) à
    une relecture du trousseau système, qui peut ne jamais avoir reçu la
    dernière valeur si l'écriture a levé en cours de route (bug corrigé
    ci-dessus). Sans registration cette session (premier appel après
    lancement, ou après `effacer_licence`), retombe sur le trousseau puis
    sur `None`."""
    if _licence_memoire_session is not None:
        return _licence_memoire_session
    if trousseau_disponible():
        try:
            return keyring.get_password(SERVICE_NAME, _LICENCE_ACCOUNT)
        except Exception:
            return None
    return None


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
