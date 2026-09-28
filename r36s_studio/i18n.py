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

"""Langue de l'interface -- état partagé par `gui/strings.py` et
`consoles_diverses/strings.py`, sans dépendance de l'un vers l'autre
(règle d'isolation, `consoles_diverses/CLAUDE.md`) ni vers PySide6.

Fixée une seule fois au démarrage (`gui/app.py::run`, depuis
`config.json`), avant la création du moindre widget : les écrans lisent
`tr()` à leur construction, un changement en cours de route ne
s'applique donc qu'au lancement suivant.

Ajouter une langue : un code ici, un `strings_<code>.py` dans `gui/` et
dans `consoles_diverses/`, et rien d'autre -- mais seulement quand
quelqu'un peut relire la traduction : un avertissement faux avant une
écriture destructive (§2 n°6 de CLAUDE.md) est pire qu'aucune
traduction. Le CLI et le worker restent en français (journal brut, jamais
le message principal, §5 vocabulaire)."""

from __future__ import annotations

DEFAULT_LANGUAGE = "fr"

# Nom de chaque langue écrit dans cette langue même -- jamais traduit :
# quelqu'un qui ne lit pas le français doit pouvoir trouver « English »
# dans le sélecteur sans comprendre le reste de l'écran.
LANGUAGE_NAMES = {
    "fr": "Français",
    "en": "English",
}

SUPPORTED_LANGUAGES = tuple(LANGUAGE_NAMES)

_current = DEFAULT_LANGUAGE


def set_language(code: str) -> None:
    """Langue inconnue -> français, silencieusement (même principe de
    repli que `config.load_config`)."""
    global _current
    _current = code if code in LANGUAGE_NAMES else DEFAULT_LANGUAGE


def get_language() -> str:
    return _current


__all__ = ["DEFAULT_LANGUAGE", "LANGUAGE_NAMES", "SUPPORTED_LANGUAGES", "get_language", "set_language"]
