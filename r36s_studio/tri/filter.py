# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""« Filtrer par région et par langue » (docs/tri-roms.md) -- fonction
distincte du tri : ne réorganise rien, écarte seulement les jeux qui ne
correspondent pas aux critères (`tri/regions.py`), dans
`<dossier>/_hors_filtre/<chemin d'origine>`.

N'importe quel dossier : un dossier de console seul (`snes`) ou une
collection déjà rangée, dont chaque sous-dossier est parcouru. Aucun
firmware : aucun dossier de système n'est créé, donc rien à refuser pour un
nom de console. La racine d'un lecteur (`E:\\`, partition de jeux d'une
carte ArkOS) n'est acceptée que si elle appartient à un périphérique retenu
par le garde-fou `safety` -- le même que pour les écritures sur carte
(amovible, pas le disque système, sous le seuil de taille), jamais sur
l'apparence de son contenu. Lecture seule ici ; `apply.apply_plan` déplace (journal
`FILTER_JOURNAL_FILENAME`, distinct de celui du tri) et `apply.undo_sort`
annule."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable, Optional

from r36s_studio.devices import list_devices
from r36s_studio.doublons.safety import LARGE_FOLDER_FILE_THRESHOLD, is_filesystem_root, is_whole_user_folder
from r36s_studio.partitions.locate import list_partitions
from r36s_studio.safety import SafetyConfig, filter_devices

from .identify import DISC_EXTENSIONS, MANIFEST_EXTENSIONS
from .plan import (
    FILTERED_DIR_NAME,
    PlannedMove,
    SortCancelled,
    SortPlan,
    SortRootRefused,
    TooManyFiles,
    _linked_groups,
    _size,
    _walk,
)
from .regions import KEEP, NO_REGION, RegionFilter, evaluate
from .tables import load_systems

__all__ = ["GAME_EXTENSIONS", "build_filter_plan"]

# Seuls les jeux sont jugés : une jaquette, un `filelist.csv` ou un `.txt`
# n'ont pas de région et rempliraient la liste « sans région » pour rien.
GAME_EXTENSIONS = frozenset(
    {extension for system in load_systems().values() for extension in system.extensions}
    | DISC_EXTENSIONS
    | {".bin", ".zip", ".7z"}
)


def _group_name(group: Iterable[Path]) -> Path:
    """Fichier dont le nom représente le jeu : le manifeste (`.m3u` avant
    `.cue`), sinon le premier fichier."""
    members = sorted(group)
    manifests = sorted((m for m in members if m.suffix.lower() in MANIFEST_EXTENSIONS), key=lambda m: m.suffix.lower() != ".m3u")
    return manifests[0] if manifests else members[0]


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(b).resolve()))


def safe_card_volume(root: str) -> Optional[str]:
    """« EASYROMS (E:) » si `root` est la racine d'un volume d'un
    périphérique retenu par `safety.filter_devices` (§4.2), sinon `None`
    (disque système, gros disque externe, simple dossier, ou détection
    impossible -- jamais d'exception)."""
    if not os.path.ismount(root):
        return None
    try:
        devices = filter_devices(list_devices(), SafetyConfig())
    except (NotImplementedError, OSError, ValueError, subprocess.CalledProcessError):
        return None
    for device in devices:
        for mountpoint in device.mountpoints:
            if not _same_path(mountpoint, root):
                continue
            shown = mountpoint.rstrip("\\/") or mountpoint
            try:
                label = next(
                    (p.label for p in list_partitions(device.path) if p.mountpoint and _same_path(p.mountpoint, root)),
                    "",
                )
            except (NotImplementedError, OSError, ValueError, subprocess.CalledProcessError):
                label = ""
            return f"{label or device.display} ({shown})"
    return None


def build_filter_plan(
    root: str,
    criteria: RegionFilter,
    ignored_dirs: Iterable[str] = (),
    on_progress: Optional[Callable[[int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> SortPlan:
    """`SortPlan` dont seuls `filtered_out` (à déplacer), `no_region` et
    `kept_count` (pour l'aperçu) sont remplis -- `moves` reste vide :
    aucun jeu gardé ne bouge."""
    card_volume = safe_card_volume(root)
    if is_filesystem_root(root) and card_volume is None:
        raise SortRootRefused(root, "filesystem_root")
    if is_whole_user_folder(root):
        raise SortRootRefused(root, "user_folder")
    root_path = Path(root).resolve()
    plan = SortPlan(root=root_path, firmware_id="", region_filter=criteria, card_volume=card_volume)
    if card_volume is not None:
        try:
            plan.card_volume_bytes = shutil.disk_usage(root_path).total
        except OSError:  # volume sans système de fichiers lisible (Linux sous Windows)
            pass
    ignored_lower = frozenset(name.lower() for name in ignored_dirs)

    def on_file() -> None:
        plan.files_seen += 1
        if should_cancel is not None and should_cancel():
            raise SortCancelled()
        if plan.files_seen > LARGE_FOLDER_FILE_THRESHOLD:
            raise TooManyFiles(LARGE_FOLDER_FILE_THRESHOLD)
        if on_progress is not None:
            on_progress(plan.files_seen)

    # Aucun nom de système à éviter : chaque sous-dossier de console est
    # parcouru (`_walk` ignore toujours `_hors_filtre`, `_doublons`...).
    files = [path for path in _walk(root_path, ignored_lower, {}, plan, on_file) if path.suffix.lower() in GAME_EXTENSIONS]
    groups, _missing = _linked_groups(files)
    grouped = {member for group in groups for member in group}
    units = groups + [[path] for path in files if path not in grouped]

    for members in units:
        name = _group_name(members)
        verdict = evaluate(name.stem, criteria)
        folder = name.parent.relative_to(root_path).as_posix()
        if verdict == KEEP:
            plan.kept_count += 1
            continue
        move = PlannedMove(sorted(members), None, FILTERED_DIR_NAME, verdict, folder, _size(members))
        if verdict == NO_REGION:
            plan.no_region.append(move)  # gardé, seulement signalé
            plan.kept_count += 1
        else:
            plan.filtered_out.append(move)
    return plan
