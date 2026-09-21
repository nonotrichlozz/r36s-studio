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

"""Analyse récursive d'un dossier et détection des doublons
(docs/doublons.md) -- lecture seule stricte, aucune écriture ici.

Un `Unit` (fichier seul, ou manifeste `.cue`/`.m3u`/`.gdi` + les fichiers
qu'il référence) est l'élément atomique de toute cette détection :
jamais scindé, jamais comparé par morceaux. Un fichier référencé par un
manifeste mais introuvable sur le disque exclut tout le groupe --
signalé séparément (`ScanResult.excluded`), jamais silencieusement
ignoré (règle critique du brief).

Deux paliers, comme demandé :

- **Palier 1 (copies identiques)** -- même taille puis même SHA-256,
  uniquement entre `Unit` à fichier unique en v1 (simplification
  assumée : comparer des groupes multi-fichiers liés octet par octet
  serait possible mais nettement plus complexe pour un bénéfice
  marginal, ces groupes restent couverts par le palier 2).
- **Palier 2 (versions du même jeu)** -- titre normalisé identique
  (`normalize.py`) au sein du même dossier de système (premier niveau
  de chemin sous la racine analysée -- jamais par nom seul, un même
  titre dans deux dossiers différents n'est jamais un doublon)."""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, Iterator, List, MutableMapping, Optional, Set, Tuple

from .extensions import ExtensionKind, classify
from .linked_files import resolve_manifest
from .normalize import normalize_title, priority_score
from .safety import LARGE_FOLDER_FILE_THRESHOLD

__all__ = [
    "Unit",
    "ExclusionWarning",
    "ExactDuplicateGroup",
    "VersionGroup",
    "ScanResult",
    "OperationCancelled",
    "HashCacheEntry",
    "HashCache",
    "find_duplicates",
]

# (taille, date de modification, empreinte SHA-256) -- clé : chemin absolu
# en `str`. Signalé explicitement : « une nouvelle analyse du même dossier
# ne recalcule que les fichiers modifiés ». Persisté d'une session à
# l'autre par `doublons/scan_cache.py` (jamais ici -- ce module reste en
# lecture seule stricte, sans écriture sur disque, § docstring du module) ;
# `find_duplicates` ne fait que consulter/compléter le dictionnaire fourni
# par l'appelant, qui décide seul quand le sauvegarder.
HashCacheEntry = Tuple[int, float, str]
HashCache = MutableMapping[str, HashCacheEntry]

# Jamais redescendu : un fichier déjà écarté lors d'un scan précédent ne
# doit jamais réapparaître comme "nouveau doublon" à découvrir (§move.py).
DUPLICATES_DIR_NAME = "_doublons"

_HASH_BLOCK_SIZE = 1024 * 1024


@dataclass
class Unit:
    """Élément atomique de détection -- `representative` sert de nom pour
    la normalisation de titre et le regroupement par dossier de système ;
    `members` contient tous les fichiers réellement déplacés ensemble.

    `known_sha256` : empreinte déjà calculée pendant l'analyse pour
    `representative` -- renseignée uniquement pour les unités d'une
    `ExactDuplicateGroup` (palier 1, `_find_exact_duplicates` ci-dessous),
    `None` sinon (palier 2, jamais recalculée ici pour ça). Réutilisée par
    `move.py` lors d'un déplacement vers un autre disque (copie + vérifie
    + supprime la source) pour vérifier « le SHA-256 si déjà calculé »
    (demandé explicitement) sans jamais imposer un nouveau calcul de
    hachage à ce stade -- potentiellement coûteux sur un gros fichier dont
    la taille seule suffisait jusqu'ici."""

    representative: Path
    members: List[Path]
    total_size_bytes: int
    is_linked: bool
    known_sha256: Optional[str] = None


@dataclass
class ExclusionWarning:
    manifest: Path
    missing: List[str]


@dataclass
class ExactDuplicateGroup:
    units: List[Unit]
    # Empreinte SHA-256 commune aux `units` (§ interface, affichée à côté
    # du titre du groupe) -- confirme visuellement que deux noms différents
    # peuvent être un contenu strictement identique, pas une coïncidence.
    sha256: str


@dataclass
class VersionGroup:
    system_folder: str
    normalized_title: str
    units: List[Unit]
    suggested_keep: Unit


@dataclass
class ScanResult:
    exact_duplicate_groups: List[ExactDuplicateGroup] = field(default_factory=list)
    version_groups: List[VersionGroup] = field(default_factory=list)
    excluded: List[ExclusionWarning] = field(default_factory=list)
    files_scanned: int = 0


class OperationCancelled(Exception):
    def __init__(self, files_scanned: int):
        super().__init__(f"Analyse annulée après {files_scanned} fichier(s).")
        self.files_scanned = files_scanned


def _walk_files(directory: Path, ignored_dirs_lower: frozenset) -> Iterator[Path]:
    """Même principe que `partitions/copy.py::_walk_files`/l'ancien
    `partitions/dedupe.py::_walk_rom_candidate_files` (`os.scandir`, un
    seul passage par dossier) -- un dossier ignoré (nom exact, insensible
    à la casse, ou commençant par un point) n'est jamais descendu, pas
    seulement filtré après coup."""
    try:
        entries = os.scandir(directory)
    except OSError:
        return
    with entries:
        for entry in entries:
            if entry.is_dir():
                name_lower = entry.name.lower()
                if name_lower.startswith(".") or name_lower in ignored_dirs_lower or entry.name == DUPLICATES_DIR_NAME:
                    continue
                yield from _walk_files(Path(entry.path), ignored_dirs_lower)
            elif entry.is_file():
                yield Path(entry.path)


def _hash_file(path: Path) -> Optional[str]:
    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_BLOCK_SIZE), b""):
                hasher.update(chunk)
    except OSError:
        return None
    return hasher.hexdigest()


def _hash_file_cached(path: Path, hash_cache: Optional[HashCache]) -> Optional[str]:
    """Même contrat que `_hash_file`, mais consulte/complète `hash_cache`
    d'abord -- une entrée n'est réutilisée que si la taille *et* la date
    de modification actuelles du fichier correspondent exactement à ce qui
    a été enregistré (§ demandé explicitement) : un fichier remplacé par
    un autre de même taille mais modifié plus tard n'est jamais confondu
    avec l'ancien. `hash_cache=None` retombe sur `_hash_file` sans aucune
    mise en cache, comportement historique (compatibilité)."""
    if hash_cache is None:
        return _hash_file(path)
    key = str(path)
    try:
        stat = path.stat()
    except OSError:
        return None
    cached = hash_cache.get(key)
    if cached is not None and cached[0] == stat.st_size and cached[1] == stat.st_mtime:
        return cached[2]
    digest = _hash_file(path)
    if digest is not None:
        hash_cache[key] = (stat.st_size, stat.st_mtime, digest)
    return digest


def _find_exact_duplicates(units: List[Unit], hash_cache: Optional[HashCache] = None) -> List[ExactDuplicateGroup]:
    by_size: Dict[int, List[Unit]] = defaultdict(list)
    for unit in units:
        if not unit.is_linked:
            by_size[unit.total_size_bytes].append(unit)

    groups: List[ExactDuplicateGroup] = []
    for same_size_units in by_size.values():
        if len(same_size_units) < 2:
            continue
        by_hash: Dict[str, List[Unit]] = defaultdict(list)
        for unit in same_size_units:
            digest = _hash_file_cached(unit.representative, hash_cache)
            if digest is not None:
                by_hash[digest].append(unit)
        for digest, hash_units in by_hash.items():
            if len(hash_units) >= 2:
                for unit in hash_units:
                    # Déjà calculé ici (palier 1) -- réutilisé par move.py
                    # sans jamais recalculer, § docstring de `Unit`.
                    unit.known_sha256 = digest
                groups.append(ExactDuplicateGroup(units=hash_units, sha256=digest))
    return groups


def _system_folder(root: Path, unit: Unit) -> str:
    try:
        relative_parts = unit.representative.relative_to(root).parts
    except ValueError:
        return ""
    return relative_parts[0] if len(relative_parts) > 1 else ""


def _find_version_groups(root: Path, units: List[Unit]) -> List[VersionGroup]:
    grouped: Dict[Tuple[str, str], List[Unit]] = defaultdict(list)
    for unit in units:
        key = (_system_folder(root, unit), normalize_title(unit.representative.stem))
        grouped[key].append(unit)

    result: List[VersionGroup] = []
    for (system_folder, normalized_title), group_units in grouped.items():
        if len(group_units) < 2:
            continue
        suggested = max(
            group_units,
            key=lambda u: priority_score(u.representative.stem, u.total_size_bytes),
        )
        result.append(
            VersionGroup(
                system_folder=system_folder,
                normalized_title=normalized_title,
                units=group_units,
                suggested_keep=suggested,
            )
        )
    return result


def find_duplicates(
    root: str,
    ignored_dirs: Iterable[str] = (),
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    confirm_large_folder: Optional[Callable[[], bool]] = None,
    hash_cache: Optional[HashCache] = None,
) -> ScanResult:
    """Analyse `root` (dossier déjà accessible, choisi par l'utilisateur --
    PC, carte SD ou disque externe, aucune notion de périphérique ici).

    `on_progress(nombre_de_fichiers_vus)` est appelé à chaque fichier
    rencontré (pas seulement les candidats retenus) -- une barre de
    progression a besoin de savoir que l'analyse avance, même sur un
    dossier qui ne contient presque aucune ROM. `should_cancel()` est
    vérifié à chaque fichier (annulation coopérative, même principe que
    partout ailleurs dans ce projet). `confirm_large_folder()`, s'il est
    fourni, n'est appelé qu'une fois, au franchissement de
    `LARGE_FOLDER_FILE_THRESHOLD` -- il doit bloquer jusqu'à obtenir une
    réponse (ex. un `threading.Event.wait()` côté appelant GUI) et
    renvoyer `True` pour continuer, `False` pour annuler ; `None` (par
    défaut, utilisé par les tests) désactive complètement ce garde-fou.

    `hash_cache` (§ demandé explicitement : « cache des empreintes SHA-256
    par (chemin, taille, date de modification) ») -- consulté et complété
    en place pour chaque fichier hashé pendant l'analyse (palier 1
    uniquement, seul endroit de ce module qui hache un fichier) ; `None`
    (par défaut) désactive la mise en cache, comportement historique. La
    persistance sur disque de ce dictionnaire entre deux lancements de
    l'application est à la charge de l'appelant (`doublons/scan_cache.py`),
    jamais de ce module (§ lecture seule stricte, docstring du module)."""
    root_path = Path(root)
    ignored_dirs_lower = frozenset(name.lower() for name in ignored_dirs)

    candidate_files: List[Path] = []
    manifest_files: List[Path] = []
    count = 0
    threshold_confirmed = False

    for path in _walk_files(root_path, ignored_dirs_lower):
        if should_cancel is not None and should_cancel():
            raise OperationCancelled(count)

        count += 1
        if on_progress is not None:
            on_progress(count)

        if count >= LARGE_FOLDER_FILE_THRESHOLD and not threshold_confirmed and confirm_large_folder is not None:
            if not confirm_large_folder():
                raise OperationCancelled(count)
            threshold_confirmed = True

        kind = classify(path.suffix)
        if kind is ExtensionKind.MANIFEST:
            manifest_files.append(path)
        elif kind is ExtensionKind.ATOMIC:
            candidate_files.append(path)
        # COMPANION_ONLY/UNKNOWN : jamais un candidat, jamais un manifeste --
        # ignorés ici, un COMPANION_ONLY n'est repris que s'il est
        # explicitement référencé par un manifeste (resolve_manifest fait
        # sa propre lecture du dossier, indépendante de cette liste).

    units: List[Unit] = []
    excluded: List[ExclusionWarning] = []
    consumed: Set[Path] = set()

    for manifest_path in manifest_files:
        resolution = resolve_manifest(manifest_path)
        if resolution.missing:
            excluded.append(ExclusionWarning(manifest=manifest_path, missing=resolution.missing))
            continue
        members = [manifest_path, *resolution.members]
        consumed.update(members)
        try:
            total_size = sum(member.stat().st_size for member in members)
        except OSError:
            continue
        units.append(Unit(representative=manifest_path, members=members, total_size_bytes=total_size, is_linked=True))

    for file_path in candidate_files:
        if file_path in consumed:
            # Déjà absorbé par un manifeste (ex. un .chd listé dans un
            # .m3u) -- ne doit jamais aussi compter comme unité solo.
            continue
        try:
            size = file_path.stat().st_size
        except OSError:
            continue
        units.append(Unit(representative=file_path, members=[file_path], total_size_bytes=size, is_linked=False))

    return ScanResult(
        exact_duplicate_groups=_find_exact_duplicates(units, hash_cache),
        version_groups=_find_version_groups(root_path, units),
        excluded=excluded,
        files_scanned=count,
    )
