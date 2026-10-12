# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Jeux de fichiers de rechange du BOOT : les lister, en appliquer un, revenir
à l'origine. Cas réels faits à la main avant ce module : choisir l'écran d'une
image (dossier `Panels/` des portages Android, `ScreenFiles/` d'un clone
ArkOS...), changer le
fichier d'écran de ROCKNIX (`overlays/panels/`, posé par
`identify/rocknix_r36s.py`). Ce module ne dit jamais quel jeu est le bon :
seul un démarrage de la console le dit.

Tout ce qui permet de revenir en arrière vit sur le BOOT lui-même, dans
`r36s-studio/` (même principe que `extlinux.conf.orig`) : il suit la carte
d'un ordinateur à l'autre, et un reflash l'efface en même temps qu'il remet
les fichiers d'origine.
- `carte.json` : identifiant de la carte (créé au premier essai) et jeu
  appliqué. L'identifiant sert de clé à l'historique des essais
  (`config.json::boot_set_trials`) : l'empreinte de `safety/card_fingerprint`
  hache les fichiers du BOOT et change donc à chaque essai.
- `origine/` : copie de chaque fichier du BOOT avant sa première
  modification, et `manifest.json` (fichier -> existait-il à l'origine ?),
  écrit **avant** toute modification -- une copie interrompue reste
  réversible.

Le montage est à la charge de l'appelant : ce module ne connaît qu'un
dossier (point de montage du BOOT, ou dossier de test)."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple, Union

PathLike = Union[str, Path]

STATE_DIR = "r36s-studio"
CARD_FILE = "carte.json"
ORIGINALS_DIR = "origine"
MANIFEST_FILE = "manifest.json"

# Dossiers d'écrans : le nom change d'une image à l'autre (`Panels/` des
# portages Android, `ScreenFiles/` d'un clone ArkOS, relevés sur de vraies
# cartes) -- on cherche donc les .dtb, jamais un nom de dossier. Sauf ces
# dossiers, propres au firmware (comparés sans la casse) : `device_trees/`
# de ROCKNIX contient tous ses .dtb, lus en place par extlinux.
SCREEN_FILE_SUFFIX = ".dtb"
NOT_SCREEN_DIRS = ("device_trees",)
# ROCKNIX : mêmes noms que `identify/rocknix_r36s.py` (dupliqués :
# `partitions/` n'importe pas `identify/`, qui dépend du réseau).
ROCKNIX_PANELS_DIR = "overlays/panels"
ROCKNIX_PANEL_PREFIX = "mipi-panel.dtbo."
ROCKNIX_PANEL_TARGET = "overlays/mipi-panel.dtbo"

_TMP_SUFFIX = ".r36s-tmp"


class UnknownBootSet(Exception):
    """Le jeu demandé n'existe pas (ou plus) sur ce BOOT."""


class OriginalsMissing(Exception):
    """La copie d'origine est incomplète : rien n'est restauré."""


@dataclass(frozen=True)
class BootFileSet:
    set_id: str  # chemin du jeu sur le BOOT, stable d'un branchement à l'autre
    name: str  # nom affiché (nom du dossier ou du fichier d'écran)
    files: Tuple[Tuple[str, str], ...]  # (source, destination), chemins POSIX relatifs au BOOT


@dataclass(frozen=True)
class BootSetState:
    card_id: Optional[str]  # None tant qu'aucun jeu n'a été essayé sur cette carte
    applied: Optional[str]  # set_id du dernier jeu appliqué
    can_restore: bool  # une copie d'origine existe


def list_sets(boot_root: PathLike) -> List[BootFileSet]:
    root = Path(boot_root)
    os.listdir(root)  # BOOT illisible (EFI sous Windows) : PermissionError, jamais « aucun jeu »
    return _screen_folder_sets(root) + _rocknix_overlay_sets(root)


def _screen_folder_sets(root: Path) -> List[BootFileSet]:
    """Tout dossier du BOOT, à n'importe quelle profondeur, qui contient
    directement un .dtb est un jeu ; tous ses fichiers vont à la racine du
    BOOT (relevé R36Droid : `Panels/Panel0` à `Panel8`, deux .dtb chacun).
    Nom affiché : chemin sous le dossier de premier niveau (« Panel 1 »),
    ou ce dossier lui-même s'il contient les .dtb."""
    sets = []
    for top in _sorted_dirs(root):
        if top.name.lower() == STATE_DIR or top.name.lower() in NOT_SCREEN_DIRS:
            continue
        pending = [top]
        while pending:
            variant = pending.pop(0)
            pending[:0] = _sorted_dirs(variant)
            try:  # ex. « System Volume Information » sous Windows
                files = [path for path in sorted(variant.iterdir(), key=lambda p: p.name.lower()) if path.is_file()]
            except OSError:
                continue
            if any(path.suffix.lower() == SCREEN_FILE_SUFFIX for path in files):
                name = _rel(variant, top).replace("/", " / ") if variant != top else top.name
                sets.append(BootFileSet(_rel(variant, root), name, tuple((_rel(path, root), path.name) for path in files)))
    return sets


def _rocknix_overlay_sets(root: Path) -> List[BootFileSet]:
    folder = root / ROCKNIX_PANELS_DIR
    if not folder.is_dir():
        return []
    return [
        BootFileSet(_rel(path, root), path.name[len(ROCKNIX_PANEL_PREFIX):], ((_rel(path, root), ROCKNIX_PANEL_TARGET),))
        for path in sorted(folder.iterdir())
        if path.is_file() and path.name.startswith(ROCKNIX_PANEL_PREFIX) and len(path.name) > len(ROCKNIX_PANEL_PREFIX)
    ]


def read_state(boot_root: PathLike) -> BootSetState:
    root = Path(boot_root)
    card = _read_json(root / STATE_DIR / CARD_FILE)
    card_id = card.get("card_id") if isinstance(card.get("card_id"), str) else None
    applied = card.get("applied") if isinstance(card.get("applied"), str) else None
    return BootSetState(card_id, applied, (root / STATE_DIR / ORIGINALS_DIR / MANIFEST_FILE).is_file())


def apply_set(boot_root: PathLike, set_id: str) -> BootSetState:
    root = Path(boot_root)
    chosen = next((s for s in list_sets(root) if s.set_id == set_id), None)
    if chosen is None:
        raise UnknownBootSet(set_id)
    for _, dest in chosen.files:
        _inside(root, dest)

    state_dir = root / STATE_DIR
    card = _read_json(state_dir / CARD_FILE)
    card_id = card.get("card_id") if isinstance(card.get("card_id"), str) else uuid.uuid4().hex

    originals = state_dir / ORIGINALS_DIR
    manifest = _read_manifest(originals)
    for _, dest in chosen.files:
        if dest in manifest:
            continue  # déjà sauvegardé : la copie d'origine n'est jamais écrasée
        current = root / dest
        manifest[dest] = current.is_file()
        if manifest[dest]:
            _copy_atomic(current, originals / dest)
    _write_json(originals / MANIFEST_FILE, {"files": manifest})

    for source, dest in chosen.files:
        _copy_atomic(root / source, root / dest)
    _write_json(state_dir / CARD_FILE, {"card_id": card_id, "applied": set_id})
    return read_state(root)


def restore_original(boot_root: PathLike) -> BootSetState:
    root = Path(boot_root)
    os.listdir(root)  # illisible : PermissionError, jamais « copie d'origine absente »
    state_dir = root / STATE_DIR
    originals = state_dir / ORIGINALS_DIR
    if not (originals / MANIFEST_FILE).is_file():
        raise OriginalsMissing(str(originals / MANIFEST_FILE))
    manifest = _read_manifest(originals)
    missing = [dest for dest, existed in manifest.items() if existed and not (originals / dest).is_file()]
    if missing:
        raise OriginalsMissing(", ".join(missing))

    for dest, existed in manifest.items():
        target = _inside(root, dest)
        if existed:
            _copy_atomic(originals / dest, target)
        elif target.is_file():
            target.unlink()
    shutil.rmtree(originals)
    card = _read_json(state_dir / CARD_FILE)
    if isinstance(card.get("card_id"), str):
        _write_json(state_dir / CARD_FILE, {"card_id": card["card_id"], "applied": None})
    return read_state(root)


def describe(boot_root: PathLike) -> dict:
    """État de la carte et jeux disponibles, sous la forme de l'événement
    `boot_sets_result` -- même dictionnaire en direct et via le worker."""
    state = read_state(boot_root)
    return {
        "card_id": state.card_id,
        "applied": state.applied,
        "can_restore": state.can_restore,
        "sets": [{"set_id": s.set_id, "name": s.name} for s in list_sets(boot_root)],
    }


def _sorted_dirs(folder: Path) -> List[Path]:
    try:
        return sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name.lower())
    except OSError:
        return []


def _rel(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _inside(root: Path, relative: str) -> Path:
    """Refuse toute destination hors du BOOT ou dans `r36s-studio/`."""
    rel = PurePosixPath(relative)
    if rel.is_absolute() or ".." in rel.parts or not rel.parts or rel.parts[0].lower() == STATE_DIR:
        raise ValueError(f"Destination refusée : {relative}")
    return root.joinpath(*rel.parts)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_manifest(originals: Path) -> Dict[str, bool]:
    files = _read_json(originals / MANIFEST_FILE).get("files")
    if not isinstance(files, dict):
        return {}
    return {k: v for k, v in files.items() if isinstance(k, str) and isinstance(v, bool)}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + _TMP_SUFFIX)
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _copy_atomic(source: Path, dest: Path) -> None:
    """Copie complète puis remplacement : jamais de fichier de démarrage à
    moitié écrit si la carte est retirée pendant la copie."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + _TMP_SUFFIX)
    with open(source, "rb") as src, open(tmp, "wb") as out:
        shutil.copyfileobj(src, out)
        out.flush()
        os.fsync(out.fileno())
    os.replace(tmp, dest)


__all__ = [
    "BootFileSet",
    "BootSetState",
    "OriginalsMissing",
    "UnknownBootSet",
    "apply_set",
    "describe",
    "list_sets",
    "read_state",
    "restore_original",
]
