# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

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
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import VALEUR_INCONNUE, AndroidDeviceInfo

# Jamais affirmé sans vérification humaine sur la page officielle du
# projet (demandé explicitement) -- l'écran affiche "à vérifier" plutôt
# que "gratuit"/"payant" tant qu'une entrée porte cette valeur.
SENTINEL_A_VERIFIER = "a_verifier"

# Statut du projet lui-même (demandé explicitement, distinct de `licence`/
# `prix` ci-dessus) : `actif`/`abandonne` sont vérifiés au moment de
# l'ajout d'une entrée (date du dernier commit/release, annonce officielle
# d'arrêt...), `a_verifier` quand la recherche n'a pas permis de trancher
# avec certitude -- jamais affirmé "actif" par défaut faute de mieux.
STATUT_PROJET_VALUES = {"actif", "abandonne", "a_verifier"}

_DATA_SUBDIR = "android/data"
_DATA_FILENAME = "emulateurs.json"

_REQUIRED_FIELDS = (
    "id",
    "nom",
    "systemes_emules",
    "licence",
    "prix",
    "statut_projet",
    "url_officielle",
    "source_url",
)


@dataclass
class EmulatorVariant:
    """Une variante téléchargeable distincte du même émulateur (signalé :
    "un émulateur peut proposer plusieurs variantes (standard, edge,
    DS...)") -- ex. deux forks communautaires réels et vérifiés
    individuellement (`NetherSX2-patch`/`NetherSX2-classic`,
    `melonDS-android`/`WatermelonDS`), jamais une variante inventée.
    Mêmes deux liens que l'entrée elle-même (`url_officielle`/
    `source_url`), jamais une licence/un prix séparés -- ce niveau de
    détail n'a jamais été demandé par le brief."""

    nom: str
    url_officielle: str
    source_url: str


@dataclass
class EmulatorEntry:
    id: str
    nom: str
    systemes_emules: List[str]
    licence: str
    prix: str
    statut_projet: str
    url_officielle: str
    source_url: str
    telechargement_auto_autorise: bool = False
    # Filtre par capacité de l'appareil (signalé : "la liste d'émulateurs
    # est identique quelle que soit la console"), optionnels -- `None`
    # signifie "aucune restriction connue sur cet axe", jamais une
    # restriction inventée faute de mieux. Vérifiés individuellement sur
    # la page/le dépôt officiel de chaque projet avant d'être renseignés
    # (ex. Eden : "32-bit Android is unsupported" + "Android 12 or newer
    # required") -- jamais une estimation à partir du SoC/de la puissance
    # perçue, ce projet ne lit d'ailleurs aucune information de SoC
    # (§ Détection du brief : seulement fabricant/modèle/nom de produit/
    # version d'Android/architecture, `android.adb.get_device_props`).
    architecture_minimale: Optional[str] = None  # ex. "arm64-v8a"
    android_minimum: Optional[str] = None  # ex. "8.0", "12"
    # Variantes téléchargeables distinctes (ci-dessus) -- liste vide pour
    # la grande majorité des entrées, jamais inventée faute de mieux.
    variantes: List[EmulatorVariant] = field(default_factory=list)


@dataclass
class EmulatorCatalog:
    avertissement: str
    emulateurs: List[EmulatorEntry]


@dataclass
class FilteredEmulatorCatalog:
    """Résultat de `filter_for_device` -- `generique` est vrai quand
    aucun filtrage n'a pu être appliqué (aucun appareil détecté, ou
    architecture/version d'Android non lues, `android.models.
    VALEUR_INCONNUE`) : `emulateurs` contient alors le catalogue complet,
    jamais une liste vide faute d'information (demandé explicitement :
    "Si l'information manque, affiche toute la liste avec une mention
    « liste générique »")."""

    avertissement: str
    emulateurs: List[EmulatorEntry]
    generique: bool


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
    statut_projet = str(data["statut_projet"])
    if statut_projet not in STATUT_PROJET_VALUES:
        raise ValueError(
            f"Entrée d'émulateur invalide : 'statut_projet' doit être l'un de {sorted(STATUT_PROJET_VALUES)}, "
            f"reçu {statut_projet!r}."
        )
    architecture_minimale = data.get("architecture_minimale")
    android_minimum = data.get("android_minimum")
    return EmulatorEntry(
        id=str(data["id"]),
        nom=str(data["nom"]),
        systemes_emules=[str(item) for item in data["systemes_emules"]],
        licence=str(data["licence"]),
        prix=str(data["prix"]),
        statut_projet=statut_projet,
        url_officielle=str(data["url_officielle"]),
        source_url=str(data["source_url"]),
        telechargement_auto_autorise=bool(data.get("telechargement_auto_autorise", False)),
        architecture_minimale=str(architecture_minimale) if architecture_minimale else None,
        android_minimum=str(android_minimum) if android_minimum else None,
        variantes=_variantes_from_json(data.get("variantes")),
    )


def _variantes_from_json(data: Any) -> List[EmulatorVariant]:
    if not isinstance(data, list):
        return []
    variantes = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Variante d'émulateur invalide (pas un objet JSON).")
        for champ in ("nom", "url_officielle", "source_url"):
            if champ not in item:
                raise ValueError(f"Variante d'émulateur invalide : champ '{champ}' manquant.")
        variantes.append(
            EmulatorVariant(
                nom=str(item["nom"]),
                url_officielle=str(item["url_officielle"]),
                source_url=str(item["source_url"]),
            )
        )
    return variantes


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


def _parse_version(version: str) -> Optional[Tuple[int, ...]]:
    """`"8.0"`/`"12"`/`"13.1"` -> `(8, 0)`/`(12,)`/`(13, 1)` -- `None` si le
    format ne suit pas ce schéma simple (jamais deviné, la comparaison
    d'`is_realistic_for_device` laisse alors passer plutôt que de risquer
    un rejet sur une donnée mal comprise)."""
    parts = version.strip().split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_realistic_for_device(entry: EmulatorEntry, device: AndroidDeviceInfo) -> bool:
    """Compare aux deux seuls axes que `android.adb.get_device_props` lit
    réellement (§ Détection du brief) -- architecture et version d'Android,
    jamais le SoC (non lu par ce projet, voir le commentaire sur `Emulator
    Entry.architecture_minimale`). Une comparaison qui ne peut pas être
    tranchée (version dans un format inattendu) laisse toujours passer
    plutôt que d'écarter une entrée sur une supposition."""
    if entry.architecture_minimale and device.abi != VALEUR_INCONNUE and device.abi != entry.architecture_minimale:
        return False
    if entry.android_minimum and device.android_version != VALEUR_INCONNUE:
        device_version = _parse_version(device.android_version)
        minimum_version = _parse_version(entry.android_minimum)
        if device_version is not None and minimum_version is not None and device_version < minimum_version:
            return False
    return True


def filter_for_device(catalog: EmulatorCatalog, device: Optional[AndroidDeviceInfo]) -> FilteredEmulatorCatalog:
    """Signalé : « la liste d'émulateurs est identique quelle que soit la
    console détectée ». Ne retient que les entrées réalistes pour
    `device` (architecture/version d'Android, ci-dessus) -- `generique`
    vrai (catalogue complet, non filtré) si `device` est absent ou si
    l'une ou l'autre de ces deux propriétés n'a pas pu être lue
    (`android.models.VALEUR_INCONNUE`) : un filtrage partiel, appliqué
    sur un seul axe alors que l'autre est inconnu, resterait trompeur --
    demandé explicitement plutôt qu'une liste vide ou un filtrage
    hasardeux sur une information manquante."""
    if device is None or device.abi == VALEUR_INCONNUE or device.android_version == VALEUR_INCONNUE:
        return FilteredEmulatorCatalog(
            avertissement=catalog.avertissement, emulateurs=list(catalog.emulateurs), generique=True
        )
    emulateurs = [entry for entry in catalog.emulateurs if is_realistic_for_device(entry, device)]
    return FilteredEmulatorCatalog(avertissement=catalog.avertissement, emulateurs=emulateurs, generique=False)


# --- Classement par console émulée (§ écran Console Android) --------------
#
# Demandé explicitement : "Le champ 'systemes' de emulateurs.json sert au
# classement" -- aucun nouveau champ de données pour la catégorie, une
# classification calculée à partir du texte déjà présent dans `systemes_
# emules` (dont certaines entrées, ex. NetherSX2/Azahar, portent aussi une
# phrase descriptive qui ne nomme aucun système -- volontairement ignorée
# ici, `_CATEGORY_PATTERNS` ne cherche que des motifs de nom de console).
#
# Liste et ordre d'affichage exacts demandés ; "Rétro" sert de repli pour
# tout émulateur multi-système/généraliste (RetroArch) ou dont le système
# ne correspond à aucune des quatorze consoles nommées (ex. Nintendo 64,
# absent de la liste demandée).
CATEGORIES: List[Tuple[str, str]] = [
    ("gc_wii", "GameCube / Wii"),
    ("wii_u", "Wii U"),
    ("switch", "Switch"),
    ("ds", "DS"),
    ("n3ds", "3DS"),
    ("ps1", "PS1"),
    ("ps2", "PS2"),
    ("ps3", "PS3"),
    ("psp", "PSP"),
    ("ps_vita", "PS Vita"),
    ("xbox", "Xbox"),
    ("xbox360", "Xbox 360"),
    ("dreamcast", "Dreamcast"),
    ("pc", "PC"),
    ("retro", "Rétro"),
]
CATEGORY_LABELS: Dict[str, str] = dict(CATEGORIES)

# Ordre déterminant : les catégories les plus spécifiques d'abord, pour
# qu'un texte contenant "3DS" ne matche jamais "DS", ni "Wii U" "GameCube /
# Wii" -- chaque motif est une regex insensible à la casse, `\b` pour ne
# jamais matcher un sous-mot (ex. "PS1" ne doit pas matcher dans un futur
# "PS10" hypothétique).
_CATEGORY_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    # "Wii U" doit primer sur "Wii" seul (gc_wii) -- lookahead négatif sur
    # la branche "wii" de gc_wii, ci-dessous, plutôt qu'un simple ordre de
    # priorité : `categorize` collecte tous les motifs qui correspondent,
    # un ordre de liste seul ne suffirait pas à empêcher un double
    # classement sur le même texte.
    ("wii_u", re.compile(r"\bwii\s*u\b", re.IGNORECASE)),
    ("n3ds", re.compile(r"\b3ds\b", re.IGNORECASE)),
    ("xbox360", re.compile(r"\bxbox\s*360\b", re.IGNORECASE)),
    ("gc_wii", re.compile(r"\bgamecube\b|\bwii\b(?!\s*u\b)", re.IGNORECASE)),
    ("ds", re.compile(r"\bdsi?\b", re.IGNORECASE)),
    ("switch", re.compile(r"\bswitch\b", re.IGNORECASE)),
    ("ps1", re.compile(r"\bps ?1\b|\bplaystation 1\b", re.IGNORECASE)),
    ("ps2", re.compile(r"\bps ?2\b|\bplaystation 2\b", re.IGNORECASE)),
    ("ps3", re.compile(r"\bps ?3\b|\bplaystation 3\b", re.IGNORECASE)),
    ("psp", re.compile(r"\bpsp\b", re.IGNORECASE)),
    ("ps_vita", re.compile(r"\bvita\b", re.IGNORECASE)),
    # "Xbox 360" doit primer sur "Xbox" seul -- même principe que wii_u/
    # gc_wii ci-dessus (lookahead négatif plutôt qu'un ordre de liste).
    ("xbox", re.compile(r"\bxbox\b(?!\s*360\b)", re.IGNORECASE)),
    ("dreamcast", re.compile(r"\bdreamcast\b", re.IGNORECASE)),
    ("pc", re.compile(r"\bwindows\b|\bwine\b", re.IGNORECASE)),
]


def categorize(entry: EmulatorEntry) -> List[str]:
    """Catégories (identifiants de `CATEGORIES`) correspondant à `entry`,
    déduites de `systemes_emules` -- jamais vide : repli sur `["retro"]`
    si aucun motif ne correspond à aucune des chaînes de la liste
    (généraliste/multi-système, ou système non couvert par les quatorze
    catégories nommées). Un émulateur peut apparaître dans plusieurs
    catégories à la fois (demandé explicitement) si son texte nomme
    plusieurs consoles distinctes."""
    matched: List[str] = []
    for texte in entry.systemes_emules:
        for category_id, pattern in _CATEGORY_PATTERNS:
            if category_id not in matched and pattern.search(texte):
                matched.append(category_id)
    if not matched:
        return ["retro"]
    return matched


def count_by_category(emulateurs: List[EmulatorEntry]) -> Dict[str, int]:
    """Nombre d'émulateurs par catégorie (§ écran Console Android, colonne
    de gauche) -- toutes les catégories de `CATEGORIES` sont présentes,
    y compris à 0 (ex. Xbox/Xbox 360/Wii U/PS3, aucun émulateur Android
    fonctionnel connu à ce jour, § android/data/emulateurs.json) : la
    colonne reste stable plutôt que de faire disparaître une catégorie
    vide, qui resterait alors invisible sans explication."""
    counts = {category_id: 0 for category_id, _ in CATEGORIES}
    for entry in emulateurs:
        for category_id in categorize(entry):
            counts[category_id] += 1
    return counts


def filter_by_category(emulateurs: List[EmulatorEntry], category_id: Optional[str]) -> List[EmulatorEntry]:
    """`category_id=None` (pseudo-catégorie "Toutes") renvoie la liste
    complète, inchangée -- même convention que `filter_for_device`
    (`device=None` -> catalogue complet)."""
    if category_id is None:
        return list(emulateurs)
    return [entry for entry in emulateurs if category_id in categorize(entry)]


__all__ = [
    "SENTINEL_A_VERIFIER",
    "STATUT_PROJET_VALUES",
    "CATEGORIES",
    "CATEGORY_LABELS",
    "EmulatorEntry",
    "EmulatorVariant",
    "EmulatorCatalog",
    "FilteredEmulatorCatalog",
    "load_emulators",
    "is_realistic_for_device",
    "filter_for_device",
    "categorize",
    "count_by_category",
    "filter_by_category",
]
