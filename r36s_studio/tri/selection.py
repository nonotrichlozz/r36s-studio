# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Liste de jeux composée librement (fichiers choisis un par un, dossiers
entiers, glisser-déposer), sans Qt ni ADB : sert à « Copier des jeux sur
ma console (USB) » (`android/knulli.py`) et pourra servir à « Copier des
jeux sur la carte ».

Chaque fichier garde son **dossier de départ** (`root`) : le dossier ajouté,
ou le dossier parent d'un fichier choisi seul. C'est à partir de lui que le
système est déduit du chemin (`psx/…`), comme pour un dossier entier.

Jeux en plusieurs fichiers : choisir un `.cue`/`.m3u`/`.gdi` ajoute les
fichiers qu'il cite (en chaîne : `.m3u` -> `.cue` -> `.bin`), et choisir un
fichier cité par un manifeste du même dossier ajoute ce manifeste -- un
`.bin` ne part jamais sans son `.cue`. Retirer une ligne retire tout le
groupe. Un fichier cité mais absent du disque reste signalé par l'aperçu
(`disc_missing_files`)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

from r36s_studio.doublons.linked_files import resolve_manifest

from .identify import MANIFEST_EXTENSIONS
from .plan import _ALWAYS_IGNORED, _JOURNAL_FILENAMES, _linked_groups

__all__ = ["GameSelection", "walk_games"]


def walk_games(root: Path) -> List[Path]:
    """Tous les fichiers du dossier, sous-dossiers compris, sauf cachés et
    dossiers/journaux de mise de côté des outils de tri."""
    files = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in _ALWAYS_IGNORED)
        for name in sorted(names):
            if not name.startswith(".") and name not in _JOURNAL_FILENAMES:
                files.append(Path(directory) / name)
    return files


class GameSelection:
    def __init__(self) -> None:
        # fichier -> dossier de départ ; ordre d'ajout conservé, un fichier
        # ajouté deux fois (même par deux chemins) n'apparaît qu'une fois.
        self._entries: Dict[Path, Path] = {}

    def entries(self) -> List[Tuple[Path, Path]]:
        """(dossier de départ, fichier)."""
        return [(root, path) for path, root in self._entries.items()]

    def files(self) -> List[Path]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def _add(self, path: Path, root: Path) -> bool:
        if path in self._entries:
            return False
        self._entries[path] = root
        return True

    def add_folder(self, folder: str) -> int:
        root = Path(folder).resolve()
        return sum(self._add(path, root) for path in walk_games(root))

    def add_files(self, paths: Iterable[str]) -> int:
        added = 0
        for raw in paths:
            path = Path(raw).resolve()
            if path.is_dir():
                added += self.add_folder(str(path))
            elif path.is_file():
                added += self._add_linked(path, path.parent, set())
        return added

    # Glisser-déposer : fichiers et dossiers mélangés.
    add_paths = add_files

    def _add_linked(self, path: Path, root: Path, seen: Set[Path]) -> int:
        if path in seen:
            return 0
        seen.add(path)
        added = int(self._add(path, root))
        if path.suffix.lower() in MANIFEST_EXTENSIONS:
            for member in resolve_manifest(path).members:
                added += self._add_linked(member.resolve(), root, seen)
        for manifest in self._manifests_citing(path):
            added += self._add_linked(manifest, root, seen)
        return added

    @staticmethod
    def _manifests_citing(path: Path) -> List[Path]:
        try:
            siblings = [p for p in path.parent.iterdir() if p.suffix.lower() in MANIFEST_EXTENSIONS and p.is_file()]
        except OSError:
            return []
        name = path.name.lower()
        return [
            manifest.resolve()
            for manifest in siblings
            if any(member.name.lower() == name for member in resolve_manifest(manifest).members)
        ]

    def groups(self) -> List[List[Path]]:
        """Une ligne par jeu : fichiers liés regroupés (manifeste en tête),
        les autres seuls, dans l'ordre d'ajout."""
        linked, _missing = _linked_groups(self.files())
        group_of = {member: group for group in linked for member in group}
        rows, done = [], set()
        for path in self._entries:
            if path in done:
                continue
            group = group_of.get(path, [path])
            group = sorted(group, key=lambda p: (p.suffix.lower() not in MANIFEST_EXTENSIONS, p.suffix.lower() != ".m3u", p.name))
            done.update(group)
            rows.append(group)
        return rows

    def remove(self, path: Path) -> None:
        """Retire le fichier et tout son groupe (un `.cue` sans son `.bin`,
        ou l'inverse, ne doit jamais partir seul)."""
        for group in self.groups():
            if path in group:
                for member in group:
                    self._entries.pop(member, None)
                return

    def clear(self) -> None:
        self._entries.clear()
