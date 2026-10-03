# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Persistance entre deux lancements de l'application pour l'outil
« Doublons de jeux » (signalé explicitement : « ne jamais obliger à
relancer une analyse ») -- `doublons/scan.py` reste volontairement en
lecture seule stricte (aucune écriture sur disque) ; ce module-ci est le
seul endroit qui écrit quoi que ce soit pour ce package, dans le dossier
de données de l'app (`config.config_dir()`, jamais les Documents de
l'utilisateur -- ce n'est pas un contenu qu'il a produit, § convention
déjà suivie pour `config.json`/les journaux).

Deux caches distincts, dans le même dossier (`default_cache_dir()`,
`~/.config/r36s-studio/doublons_scans/` ou l'équivalent Windows) :

- **Résultat d'analyse par dossier analysé** (§ demandé : « par dossier
  analysé ») -- un fichier JSON par racine déjà analysée, nommé d'après
  une empreinte de son chemin absolu résolu (`_cache_filename_for_root`) :
  deux dossiers différents ne se marchent jamais dessus, un même dossier
  retrouve toujours le même fichier d'une session à l'autre. Contient le
  résultat complet (`scan.ScanResult`) et, pour chaque fichier référencé,
  sa taille et sa date de modification au moment de l'analyse
  (`file_stats`) -- `verify_scan_cache` s'en sert pour détecter un fichier
  modifié ou disparu *avant* de réutiliser ce résultat, jamais après coup.
- **Empreintes SHA-256** (§ demandé : « cache des empreintes SHA-256 par
  (chemin, taille, date de modification) ») -- un seul fichier global,
  partagé par tous les dossiers analysés (les chemins qui y servent de
  clé sont déjà absolus, donc naturellement uniques même si deux dossiers
  analysés se recouvrent). `scan.find_duplicates(hash_cache=...)` le
  consulte et le complète en mémoire ; sauvegardé par l'appelant
  (`gui/doublons_runner.py`) après chaque analyse, jamais par `scan.py`
  lui-même."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from r36s_studio.config import config_dir

from .scan import ExactDuplicateGroup, ExclusionWarning, HashCache, ScanResult, Unit, VersionGroup

__all__ = [
    "CachedScan",
    "default_cache_dir",
    "default_hash_cache_path",
    "scan_cache_path_for_root",
    "save_scan_cache",
    "load_scan_cache",
    "find_most_recent_scan_cache",
    "load_hash_cache",
    "save_hash_cache",
    "verify_scan_cache",
]

_CACHE_SUBDIR = "doublons_scans"
_HASH_CACHE_FILENAME = "hash_cache.json"


@dataclass
class CachedScan:
    root: str
    scanned_at: str  # ISO 8601, UTC (même format que move.py::journal.json)
    result: ScanResult
    # Taille/date de modification de chaque fichier référencé, au moment
    # de l'analyse -- base de comparaison de `verify_scan_cache`, jamais
    # affichée ni utilisée ailleurs.
    file_stats: Dict[str, List[float]]


def default_cache_dir() -> Path:
    path = config_dir() / _CACHE_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_hash_cache_path() -> Path:
    return default_cache_dir() / _HASH_CACHE_FILENAME


def _cache_filename_for_root(root: str) -> str:
    """Nom de fichier déterministe à partir du chemin absolu résolu de
    `root` -- jamais le chemin lui-même comme nom de fichier (caractères
    interdits selon l'OS, longueur, casse)."""
    resolved = str(Path(root).resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:32]
    return f"{digest}.json"


def scan_cache_path_for_root(root: str) -> Path:
    return default_cache_dir() / _cache_filename_for_root(root)


# --- Sérialisation de ScanResult -------------------------------------------


def _unit_to_json(unit: Unit) -> Dict[str, Any]:
    return {
        "representative": str(unit.representative),
        "members": [str(member) for member in unit.members],
        "total_size_bytes": unit.total_size_bytes,
        "is_linked": unit.is_linked,
        "known_sha256": unit.known_sha256,
    }


def _unit_from_json(data: Dict[str, Any]) -> Unit:
    return Unit(
        representative=Path(data["representative"]),
        members=[Path(member) for member in data["members"]],
        total_size_bytes=data["total_size_bytes"],
        is_linked=data["is_linked"],
        known_sha256=data.get("known_sha256"),
    )


def _scan_result_to_json(result: ScanResult) -> Dict[str, Any]:
    exact_groups = []
    for group in result.exact_duplicate_groups:
        exact_groups.append({"units": [_unit_to_json(unit) for unit in group.units], "sha256": group.sha256})

    version_groups = []
    for group in result.version_groups:
        units_json = [_unit_to_json(unit) for unit in group.units]
        # `suggested_keep` est l'un des `units` (même objet) -- un index
        # dans la liste plutôt qu'une seconde copie, pour ne jamais
        # dupliquer les données ni risquer une incohérence à la relecture.
        suggested_index = group.units.index(group.suggested_keep)
        version_groups.append(
            {
                "system_folder": group.system_folder,
                "normalized_title": group.normalized_title,
                "units": units_json,
                "suggested_keep_index": suggested_index,
            }
        )

    excluded = [{"manifest": str(warning.manifest), "missing": warning.missing} for warning in result.excluded]

    return {
        "exact_duplicate_groups": exact_groups,
        "version_groups": version_groups,
        "excluded": excluded,
        "files_scanned": result.files_scanned,
    }


def _scan_result_from_json(data: Dict[str, Any]) -> ScanResult:
    exact_groups = [
        ExactDuplicateGroup(units=[_unit_from_json(u) for u in group["units"]], sha256=group["sha256"])
        for group in data.get("exact_duplicate_groups", [])
    ]

    version_groups = []
    for group in data.get("version_groups", []):
        units = [_unit_from_json(u) for u in group["units"]]
        index = group["suggested_keep_index"]
        version_groups.append(
            VersionGroup(
                system_folder=group["system_folder"],
                normalized_title=group["normalized_title"],
                units=units,
                suggested_keep=units[index],
            )
        )

    excluded = [
        ExclusionWarning(manifest=Path(warning["manifest"]), missing=warning["missing"])
        for warning in data.get("excluded", [])
    ]

    return ScanResult(
        exact_duplicate_groups=exact_groups,
        version_groups=version_groups,
        excluded=excluded,
        files_scanned=data.get("files_scanned", 0),
    )


def _all_referenced_files(result: ScanResult) -> List[Path]:
    """Tous les chemins de fichier que `result` référence, tous groupes et
    unités confondus -- sert à la fois à construire `file_stats` (§ save)
    et à vérifier leur fraîcheur avant réutilisation (§ verify)."""
    paths: List[Path] = []
    for group in result.exact_duplicate_groups:
        for unit in group.units:
            paths.extend(unit.members)
    for group in result.version_groups:
        for unit in group.units:
            paths.extend(unit.members)
    # Le manifeste d'un groupe exclu existe forcément (c'est ce qui a été
    # lu pour découvrir les membres manquants) -- inclus pour cohérence,
    # même s'il ne bloque jamais la réutilisation à lui seul (rien d'autre
    # n'en dépend, un groupe exclu n'est de toute façon jamais déplacé).
    for warning in result.excluded:
        paths.append(warning.manifest)
    return paths


def save_scan_cache(root: str, result: ScanResult, path: Optional[Path] = None) -> None:
    """Enregistre `result` pour `root`, avec la taille et la date de
    modification actuelles de chaque fichier référencé (`file_stats`) --
    la base de comparaison utilisée par `verify_scan_cache` au moment
    d'une reprise future. Un fichier devenu illisible entre-temps (ex.
    carte débranchée en plein milieu) est simplement omis de `file_stats`
    plutôt que d'empêcher la sauvegarde du reste -- il sera de toute façon
    traité comme modifié/disparu à la prochaine vérification, faute
    d'entrée correspondante."""
    real_path = path if path is not None else scan_cache_path_for_root(root)
    file_stats: Dict[str, List[float]] = {}
    for file_path in _all_referenced_files(result):
        try:
            stat = file_path.stat()
        except OSError:
            continue
        file_stats[str(file_path)] = [stat.st_size, stat.st_mtime]

    payload = {
        "root": str(Path(root).resolve()),
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "scan_result": _scan_result_to_json(result),
        "file_stats": file_stats,
    }
    real_path.parent.mkdir(parents=True, exist_ok=True)
    real_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _cached_scan_from_payload(payload: Dict[str, Any]) -> Optional[CachedScan]:
    try:
        return CachedScan(
            root=payload["root"],
            scanned_at=payload["scanned_at"],
            result=_scan_result_from_json(payload["scan_result"]),
            file_stats=payload.get("file_stats", {}),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_scan_cache(root: str, path: Optional[Path] = None) -> Optional[CachedScan]:
    """`None` si aucun cache n'existe encore pour `root`, ou s'il est
    corrompu -- jamais une exception : un cache manquant/invalide doit
    simplement se comporter comme s'il n'y en avait pas, pas empêcher
    l'outil de fonctionner."""
    real_path = path if path is not None else scan_cache_path_for_root(root)
    try:
        raw = json.loads(real_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    return _cached_scan_from_payload(raw)


def find_most_recent_scan_cache(cache_dir: Optional[Path] = None) -> Optional[CachedScan]:
    """Balaie tous les caches d'analyse connus (un par dossier déjà
    analysé) et renvoie celui dont `scanned_at` est le plus récent --
    alimente le bouton « Reprendre la dernière analyse » (§ demandé
    explicitement, un seul bouton pour la toute dernière analyse, quel
    que soit le dossier). `None` si aucun cache n'existe (première
    utilisation de l'outil, ou dossier de cache jamais créé) -- jamais une
    exception, même logique de tolérance que `load_scan_cache`."""
    real_dir = cache_dir if cache_dir is not None else default_cache_dir()
    try:
        candidates = list(real_dir.glob("*.json"))
    except OSError:
        return None

    most_recent: Optional[CachedScan] = None
    for candidate in candidates:
        if candidate.name == _HASH_CACHE_FILENAME:
            continue
        try:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(raw, dict) or "scan_result" not in raw:
            continue
        # Comparaison purement textuelle de deux horodatages ISO 8601 UTC,
        # tous produits par la même horloge (`datetime.isoformat`) --
        # toujours équivalente à une comparaison chronologique réelle pour
        # ce format précis (zéro-remplissage garanti par `isoformat`),
        # sans avoir à reparser chaque date.
        if most_recent is None or raw.get("scanned_at", "") > most_recent.scanned_at:
            cached = _cached_scan_from_payload(raw)
            if cached is not None:
                most_recent = cached
    return most_recent


# --- Cache des empreintes SHA-256 ------------------------------------------


def load_hash_cache(path: Optional[Path] = None) -> Dict[str, Tuple[int, float, str]]:
    real_path = path if path is not None else default_hash_cache_path()
    try:
        raw = json.loads(real_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    cache: Dict[str, Tuple[int, float, str]] = {}
    for key, value in raw.items():
        if (
            isinstance(value, list)
            and len(value) == 3
            and isinstance(value[0], int)
            and isinstance(value[1], (int, float))
            and isinstance(value[2], str)
        ):
            cache[key] = (value[0], float(value[1]), value[2])
    return cache


def save_hash_cache(cache: HashCache, path: Optional[Path] = None) -> None:
    real_path = path if path is not None else default_hash_cache_path()
    real_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {key: list(value) for key, value in cache.items()}
    real_path.write_text(json.dumps(serializable, ensure_ascii=False), encoding="utf-8")


# --- Vérification avant réutilisation ---------------------------------------


def _unit_is_fresh(unit: Unit, file_stats: Dict[str, List[float]]) -> bool:
    """Un `Unit` entier est jugé périmé dès que l'un de ses membres a
    disparu ou changé (taille/date de modification) -- jamais une
    réutilisation partielle d'une unité, même principe d'atomicité que le
    reste de cet outil (`move.py`, `linked_files.py`)."""
    for member in unit.members:
        recorded = file_stats.get(str(member))
        if recorded is None:
            return False
        try:
            stat = member.stat()
        except OSError:
            return False
        if stat.st_size != recorded[0] or stat.st_mtime != recorded[1]:
            return False
    return True


def verify_scan_cache(cached: CachedScan) -> Tuple[ScanResult, int]:
    """Vérifie rapidement (taille + date de modification, jamais un
    nouveau hachage) que les fichiers référencés par `cached.result`
    existent encore et n'ont pas changé depuis l'analyse -- retire les
    `Unit` devenues périmées (§ demandé explicitement : « retirer ceux qui
    ont changé »), et le groupe entier avec elles s'il ne reste plus assez
    d'unités pour former un doublon (moins de deux). Retourne le résultat
    nettoyé et le nombre d'unités retirées, jamais une exception -- un
    fichier illisible pendant cette vérification est traité comme
    "changé", pas comme une erreur qui interromprait toute la reprise."""
    result = cached.result
    file_stats = cached.file_stats
    removed = 0

    fresh_exact_groups: List[ExactDuplicateGroup] = []
    for group in result.exact_duplicate_groups:
        fresh_units = [unit for unit in group.units if _unit_is_fresh(unit, file_stats)]
        removed += len(group.units) - len(fresh_units)
        if len(fresh_units) >= 2:
            fresh_exact_groups.append(ExactDuplicateGroup(units=fresh_units, sha256=group.sha256))
        # Moins de deux -- le groupe entier disparaît (plus un doublon),
        # les unités restantes (0 ou 1) sont bien comptées dans `removed`.
        elif len(fresh_units) == 1:
            removed += 1

    fresh_version_groups: List[VersionGroup] = []
    for group in result.version_groups:
        fresh_units = [unit for unit in group.units if _unit_is_fresh(unit, file_stats)]
        removed += len(group.units) - len(fresh_units)
        if len(fresh_units) >= 2:
            suggested = group.suggested_keep if group.suggested_keep in fresh_units else fresh_units[0]
            fresh_version_groups.append(
                VersionGroup(
                    system_folder=group.system_folder,
                    normalized_title=group.normalized_title,
                    units=fresh_units,
                    suggested_keep=suggested,
                )
            )
        elif len(fresh_units) == 1:
            removed += 1

    fresh_result = ScanResult(
        exact_duplicate_groups=fresh_exact_groups,
        version_groups=fresh_version_groups,
        excluded=result.excluded,
        files_scanned=result.files_scanned,
    )
    return fresh_result, removed
