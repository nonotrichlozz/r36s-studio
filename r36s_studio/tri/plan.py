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

"""Construction de l'aperçu du tri (docs/tri-roms.md) -- lecture seule :
rien n'est déplacé ici, `apply.py` s'en charge après confirmation.

Parcours récursif du dossier choisi. **Jamais descendus** : `_non_
identifies`, `_doublons`, les dossiers ignorés passés par l'appelant
(`bios`, `Imgs`...), les dossiers cachés, et **tout dossier dont le nom
est un nom de système du firmware cible** -- pas seulement ceux que
l'outil a créés : une collection déjà rangée à la main ne doit jamais
être redéplacée.

Trois issues pour chaque jeu (ou groupe de fichiers liés) :
- rangé dans `<dossier>/<nom du système pour ce firmware>/` ;
- déplacé dans `<dossier>/_non_identifies/<chemin d'origine>`, avec un
  motif (jamais rangé au hasard) ;
- laissé en place, avec un motif, quand le déplacer rendrait le jeu
  invisible (dossier de destination existant avec une autre casse)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

from r36s_studio.doublons.linked_files import resolve_manifest
from r36s_studio.doublons.safety import LARGE_FOLDER_FILE_THRESHOLD, is_filesystem_root, is_whole_user_folder

from .identify import MANIFEST_EXTENSIONS, identify_file
from .tables import FirmwareFolders, load_firmware_tables

__all__ = [
    "UNIDENTIFIED_DIR_NAME",
    "SORT_JOURNAL_FILENAME",
    "PlannedMove",
    "SortPlan",
    "SortCancelled",
    "SortRootRefused",
    "TooManyFiles",
    "build_plan",
]

UNIDENTIFIED_DIR_NAME = "_non_identifies"
SORT_JOURNAL_FILENAME = "_rangement_journal.json"
_ALWAYS_IGNORED = frozenset({UNIDENTIFIED_DIR_NAME.lower(), "_doublons"})


class SortCancelled(Exception):
    pass


class SortRootRefused(Exception):
    """Dossier refusé d'office : racine d'un disque, dossier personnel
    entier, ou dossier qui porte lui-même un nom de système (le trier
    créerait `snes/snes/`)."""

    def __init__(self, path: str, reason: str):
        super().__init__(f"{path} : {reason}")
        self.path = path
        self.reason = reason  # "filesystem_root" | "user_folder" | "system_folder"


class TooManyFiles(Exception):
    def __init__(self, count: int):
        super().__init__(f"plus de {count} fichiers")
        self.count = count


@dataclass
class PlannedMove:
    members: List[Path]
    system_id: Optional[str]
    # Dossier de destination relatif à la racine (« snes »,
    # « _non_identifies ») -- vide pour un élément laissé en place.
    folder: str
    reason: str
    detail: str = ""
    size_bytes: int = 0


@dataclass
class SortPlan:
    root: Path
    firmware_id: str
    moves: List[PlannedMove] = field(default_factory=list)
    unidentified: List[PlannedMove] = field(default_factory=list)
    left_in_place: List[PlannedMove] = field(default_factory=list)
    # Dossiers de système déjà présents, jamais parcourus (chemins
    # relatifs à la racine).
    kept_folders: List[str] = field(default_factory=list)
    # (chemin relatif trouvé, nom attendu) : même nom qu'un dossier de
    # système, mais une autre casse -- la console risque de ne pas le voir.
    case_warnings: List[Tuple[str, str]] = field(default_factory=list)
    files_seen: int = 0

    def moves_by_folder(self) -> Dict[str, List[PlannedMove]]:
        grouped: Dict[str, List[PlannedMove]] = {}
        for move in self.moves:
            grouped.setdefault(move.folder, []).append(move)
        return dict(sorted(grouped.items()))

    def file_count(self) -> int:
        return sum(len(move.members) for move in self.moves + self.unidentified)


def _size(paths: Iterable[Path]) -> int:
    total = 0
    for path in paths:
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def check_root(root: str, table: FirmwareFolders) -> None:
    if is_filesystem_root(root):
        raise SortRootRefused(root, "filesystem_root")
    if is_whole_user_folder(root):
        raise SortRootRefused(root, "user_folder")
    if Path(root).resolve().name.lower() in table.folder_names_lower():
        raise SortRootRefused(root, "system_folder")


def _walk(
    root: Path,
    ignored_lower: frozenset,
    system_names: Dict[str, str],
    plan: SortPlan,
    on_file: Callable[[], None],
) -> Iterable[Path]:
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_file = entry.is_file(follow_symlinks=False)
            except OSError:
                continue
            path = Path(entry.path)
            if is_dir:
                name_lower = entry.name.lower()
                if name_lower.startswith(".") or name_lower in ignored_lower or name_lower in _ALWAYS_IGNORED:
                    continue
                expected = system_names.get(name_lower)
                if expected is not None:
                    relative = path.relative_to(root).as_posix()
                    plan.kept_folders.append(relative)
                    if entry.name != expected:
                        plan.case_warnings.append((relative, expected))
                    continue
                stack.append(path)
            elif is_file:
                if directory == root and entry.name == SORT_JOURNAL_FILENAME:
                    continue
                on_file()
                yield path


def _linked_groups(files: List[Path]) -> Tuple[List[List[Path]], Dict[Path, List[str]]]:
    """Regroupe manifestes (`.cue`/`.m3u`/`.gdi`) et fichiers qu'ils
    citent, y compris en chaîne (`.m3u` -> `.cue` -> `.bin`) : un groupe
    se déplace entier ou pas du tout (même règle que docs/doublons.md)."""
    known = set(files)
    parent: Dict[Path, Path] = {}

    def find(path: Path) -> Path:
        while parent.get(path, path) != path:
            path = parent[path]
        return path

    def union(a: Path, b: Path) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    missing: Dict[Path, List[str]] = {}
    in_group: Set[Path] = set()
    for path in files:
        if path.suffix.lower() not in MANIFEST_EXTENSIONS:
            continue
        resolution = resolve_manifest(path)
        in_group.add(path)
        parent.setdefault(path, path)
        if resolution.missing:
            missing[path] = list(resolution.missing)
        for member in resolution.members:
            if member in known:
                parent.setdefault(member, member)
                in_group.add(member)
                union(path, member)

    groups: Dict[Path, List[Path]] = {}
    for path in files:
        if path in in_group:
            groups.setdefault(find(path), []).append(path)
    return list(groups.values()), missing


def build_plan(
    root: str,
    firmware_id: str,
    ignored_dirs: Iterable[str] = (),
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> SortPlan:
    table = load_firmware_tables()[firmware_id]
    check_root(root, table)
    root_path = Path(root).resolve()
    plan = SortPlan(root=root_path, firmware_id=firmware_id)

    system_names = {folder.lower(): folder for folder in table.folders.values()}
    ignored_lower = frozenset(name.lower() for name in ignored_dirs)

    def on_file() -> None:
        plan.files_seen += 1
        if should_cancel is not None and should_cancel():
            raise SortCancelled()
        if plan.files_seen > LARGE_FOLDER_FILE_THRESHOLD:
            raise TooManyFiles(LARGE_FOLDER_FILE_THRESHOLD)
        if on_progress is not None:
            on_progress(plan.files_seen)

    files = list(_walk(root_path, ignored_lower, system_names, plan, on_file))

    groups, missing = _linked_groups(files)
    grouped_files = {member for group in groups for member in group}
    for group in groups:
        manifests = [member for member in group if member in missing]
        detail = ", ".join(name for manifest in manifests for name in missing[manifest])
        plan.unidentified.append(
            PlannedMove(
                members=sorted(group),
                system_id=None,
                folder=UNIDENTIFIED_DIR_NAME,
                reason="disc_image_missing_files" if detail else "disc_image",
                detail=detail,
                size_bytes=_size(group),
            )
        )

    # Un dossier de destination déjà présent, mais avec une autre casse :
    # sur un système de fichiers insensible à la casse (Windows, cartes
    # FAT/exFAT), y « créer » `snes` écrirait en réalité dans `SNES` --
    # un dossier que la console risque de ne pas voir. Jamais rangé là.
    case_conflicts = {expected.lower() for relative, expected in plan.case_warnings if "/" not in relative}

    for path in files:
        if path in grouped_files:
            continue
        if should_cancel is not None and should_cancel():
            raise SortCancelled()
        result = identify_file(path)
        size = _size([path])
        if result.system_id is None:
            plan.unidentified.append(
                PlannedMove([path], None, UNIDENTIFIED_DIR_NAME, result.reason, result.detail, size)
            )
            continue
        folder = table.folders.get(result.system_id)
        if folder is None:
            plan.unidentified.append(
                PlannedMove([path], result.system_id, UNIDENTIFIED_DIR_NAME, "system_not_supported", result.detail, size)
            )
            continue
        accepted = table.accepted_extensions.get(result.system_id)
        if accepted is not None and path.suffix.lower() not in accepted:
            plan.unidentified.append(
                PlannedMove([path], result.system_id, UNIDENTIFIED_DIR_NAME, "extension_not_accepted", path.suffix, size)
            )
            continue
        if folder.lower() in case_conflicts:
            plan.left_in_place.append(PlannedMove([path], result.system_id, "", "folder_case_conflict", folder, size))
            continue
        plan.moves.append(PlannedMove([path], result.system_id, folder, result.reason, result.detail, size))

    return plan
