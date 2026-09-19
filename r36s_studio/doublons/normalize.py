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

"""Normalisation de titre et priorité de conservation par défaut
(docs/doublons.md §« Deux niveaux de détection » palier 2, et
§« Version conservée par défaut dans un groupe de versions »).

Normalisation : minuscules, accents retirés, tags entre parenthèses/
crochets extraits puis retirés du titre, ponctuation et espaces
superflus retirés -- deux fichiers "Chrono Trigger (France).sfc" et
"Chrono Trigger (Europe) (Rev A).sfc" partagent le même titre normalisé
("chrono trigger") mais restent deux fichiers distincts dans le même
groupe de versions, jamais fusionnés en un seul.

Priorité de conservation : France/Fr > Europe > World > USA > Japan >
autre : à région égale, révision la plus haute ; à révision égale, le
fichier le plus gros. Sert uniquement à *suggérer* une version à
conserver dans l'interface -- jamais à précocher automatiquement une
suppression (règle du projet : le palier 2 n'est jamais présélectionné,
contrairement au palier 1 des copies identiques)."""

from __future__ import annotations

import re
import unicodedata
from typing import FrozenSet, List, Tuple

__all__ = ["extract_tags", "normalize_title", "region_rank", "revision_score", "priority_score"]

_TAG_RE = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_WORD_SPLIT_RE = re.compile(r"[^a-z]+")

# (France)/(Fr) et (Europe) sont deux tags distincts qui pointent vers la
# même priorité (rang 0) -- un seul groupe, pas deux rangs séparés
# malgré leur ordre d'écriture dans le brief.
_REGION_PRIORITY_GROUPS: List[FrozenSet[str]] = [
    frozenset({"france", "fr"}),
    frozenset({"europe"}),
    frozenset({"world"}),
    frozenset({"usa"}),
    frozenset({"japan"}),
]
_UNKNOWN_REGION_RANK = len(_REGION_PRIORITY_GROUPS)  # "autre", la priorité la plus basse

_VERSION_RE = re.compile(r"\bv(\d+(?:\.\d+)*)\b", re.IGNORECASE)
_REVISION_NUMBER_RE = re.compile(r"\brev(?:ision)?\.?\s*(\d+)\b", re.IGNORECASE)
_REVISION_LETTER_RE = re.compile(r"\brev(?:ision)?\.?\s*([a-z])\b", re.IGNORECASE)


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def extract_tags(stem: str) -> Tuple[str, List[str]]:
    """Retourne `(titre_sans_tags, [contenu_de_chaque_tag])` -- un tag est
    tout ce qui se trouve entre parenthèses ou crochets, ex. "(France)",
    "[!]", "(Rev A)"."""
    tags = _TAG_RE.findall(stem)
    title_only = _TAG_RE.sub("", stem)
    return title_only, tags


def normalize_title(stem: str) -> str:
    """Titre comparable entre deux fichiers du même jeu -- minuscules,
    accents retirés, tags retirés, ponctuation/espaces réduits à un seul
    espace entre mots."""
    title_only, _tags = extract_tags(stem)
    lowered = strip_accents(title_only).lower()
    collapsed = _NON_ALNUM_RE.sub(" ", lowered).strip()
    return re.sub(r"\s+", " ", collapsed)


def region_rank(tags: List[str]) -> int:
    """Rang le plus favorable trouvé parmi tous les tags (0 = France/Fr) ;
    `_UNKNOWN_REGION_RANK` si aucune région reconnue. Correspondance par
    mot entier (jamais une sous-chaîne) : "(Français)" ne doit jamais
    matcher "fr" par accident de sous-chaîne."""
    best = _UNKNOWN_REGION_RANK
    for tag in tags:
        words = set(_WORD_SPLIT_RE.split(strip_accents(tag).lower()))
        for rank, group in enumerate(_REGION_PRIORITY_GROUPS):
            if rank < best and group & words:
                best = rank
    return best


def revision_score(tags: List[str]) -> Tuple[int, ...]:
    """Meilleure indication de révision trouvée parmi les tags, sous forme
    d'un tuple comparable (plus grand = plus récent) -- `(0,)` si aucune
    trouvée, toujours inférieur à une révision explicite. Heuristique
    délibérément best-effort (pas un analyseur strict des conventions de
    nommage de scène) : sert uniquement de départage à région déjà
    égale, jamais seul critère de tri."""
    best: Tuple[int, ...] = (0,)
    for tag in tags:
        match = _VERSION_RE.search(tag)
        if match:
            parts = tuple(int(p) for p in match.group(1).split("."))
            best = max(best, (1,) + parts)
            continue
        match = _REVISION_NUMBER_RE.search(tag)
        if match:
            best = max(best, (1, int(match.group(1))))
            continue
        match = _REVISION_LETTER_RE.search(tag)
        if match:
            best = max(best, (1, ord(match.group(1).lower()) - ord("a") + 1))
    return best


def priority_score(filename_stem: str, size_bytes: int) -> Tuple[int, Tuple[int, ...], int]:
    """Score comparable (plus grand = à conserver en priorité) combinant
    région, révision puis taille -- `max()` sur les scores d'un groupe de
    versions donne la version suggérée, jamais précochée (voir docstring
    de module)."""
    _title, tags = extract_tags(filename_stem)
    return (-region_rank(tags), revision_score(tags), size_bytes)
