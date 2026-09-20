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

"""Catalogue local des émulateurs Android recommandés (§ Identification et
propositions du brief) -- chargé depuis `android/data/emulateurs.json`,
jamais en dur dans le code (même principe que `doublons/extensions.py`
pour les extensions de jeux). Rien n'est téléchargé automatiquement à
cette étape : `telechargement_auto_autorise` vaut `False` pour toutes les
entrées existantes (brief : "si le téléchargement automatique sera
autorisé plus tard").

**Aucune licence ni aucun prix n'est affirmé dans ce fichier de données**
(demandé explicitement) : `licence`/`prix` valent `SENTINEL_A_VERIFIER`
pour toutes les entrées de départ, jamais une valeur inventée comme
"gratuit" sans vérification humaine -- même principe que `consoles_
diverses`, où une fiche générée par IA peut se tromper sur ce point
précis (`licence_a_verifier`, `consoles_diverses/models.py`). `source_url`
porte la page qui a servi de référence pour le reste de la fiche (nom,
systèmes émulés, URL officielle) -- pas nécessairement une preuve de la
licence/du prix, à vérifier séparément avant toute diffusion."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

# Jamais affirmé sans vérification humaine sur la page officielle du
# projet (demandé explicitement) -- l'écran affiche "à vérifier" plutôt
# que "gratuit"/"payant" tant qu'une entrée porte cette valeur.
SENTINEL_A_VERIFIER = "a_verifier"

_DATA_SUBDIR = "android/data"
_DATA_FILENAME = "emulateurs.json"

_REQUIRED_FIELDS = (
    "id",
    "nom",
    "systemes_emules",
    "licence",
    "prix",
    "url_officielle",
    "source_url",
)


@dataclass
class EmulatorEntry:
    id: str
    nom: str
    systemes_emules: List[str]
    licence: str
    prix: str
    url_officielle: str
    source_url: str
    telechargement_auto_autorise: bool = False


@dataclass
class EmulatorCatalog:
    avertissement: str
    emulateurs: List[EmulatorEntry]


def _data_dir() -> Path:
    """Même mécanisme que `gui/asset_paths.py::assets_dir` -- fonctionne
    aussi bien en développement qu'une fois l'app empaquetée (PyInstaller
    copie ce dossier à côté du binaire, voir `packaging/*.spec`)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / _DATA_SUBDIR
    return Path(__file__).resolve().parent / "data"


def _entry_from_json(data: Any) -> EmulatorEntry:
    if not isinstance(data, dict):
        raise ValueError("Entrée d'émulateur invalide (pas un objet JSON).")
    for champ in _REQUIRED_FIELDS:
        if champ not in data:
            raise ValueError(f"Entrée d'émulateur invalide : champ '{champ}' manquant.")
    if not isinstance(data["systemes_emules"], list):
        raise ValueError("Entrée d'émulateur invalide : 'systemes_emules' doit être une liste.")
    return EmulatorEntry(
        id=str(data["id"]),
        nom=str(data["nom"]),
        systemes_emules=[str(item) for item in data["systemes_emules"]],
        licence=str(data["licence"]),
        prix=str(data["prix"]),
        url_officielle=str(data["url_officielle"]),
        source_url=str(data["source_url"]),
        telechargement_auto_autorise=bool(data.get("telechargement_auto_autorise", False)),
    )


def load_emulators(path: Optional[Path] = None) -> EmulatorCatalog:
    """`path` explicite en test, `_data_dir() / _DATA_FILENAME` sinon.
    Contrairement à une fiche serveur (donnée externe non fiable, `consoles_
    diverses/models.py`), ce fichier est propre au projet -- une entrée
    malformée fait échouer le chargement plutôt que d'être silencieusement
    ignorée, pour attraper une erreur de packaging/données au moment des
    tests plutôt qu'à l'écran de l'utilisateur final."""
    real_path = path if path is not None else (_data_dir() / _DATA_FILENAME)
    raw = json.loads(real_path.read_text(encoding="utf-8"))
    avertissement = str(raw.get("avertissement", ""))
    emulateurs = [_entry_from_json(item) for item in raw.get("emulateurs", [])]
    return EmulatorCatalog(avertissement=avertissement, emulateurs=emulateurs)


__all__ = [
    "SENTINEL_A_VERIFIER",
    "EmulatorEntry",
    "EmulatorCatalog",
    "load_emulators",
]
