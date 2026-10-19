# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Fichiers d'écran de la carte d'origine, mis de côté avant un flash puis
reposés sur la carte flashée comme un jeu de « Choisir l'écran de la
console » (`boot_sets.py`) -- le seul jeu dont on sait qu'il faisait
démarrer cette console.

1. Avant le flash (`save_original_screen`, côté interface, sans élévation) :
   les `.dtb` et le `boot.ini` de la racine du BOOT sont copiés sur
   l'ordinateur, dans un dossier par carte avec `origine.json` (empreinte
   de la carte, `safety/card_fingerprint.py`). Une carte déjà sauvegardée
   (même empreinte) n'est jamais recopiée ni écrasée.
2. Après le flash (`install_original_screen`, dans le worker) : les `.dtb`
   sont posés dans `ecran-d-origine/` sur le BOOT de la carte flashée,
   **renommés** comme ceux du firmware écrit. Cas réel : dArkOSen attend
   `rg351mp-uboot.dtb` et `rk3326-r36s-linux.dtb`, une R36S d'usine a
   `rg351mp-kernel.dtb` et `rk3326-r35s-linux.dtb` (README de dArkOSen :
   « make copies of your original dtbs and rename them »). Le `boot.ini`
   d'origine n'y va pas : il désigne le noyau d'usine, l'appliquer sur un
   autre firmware empêcherait le démarrage -- il reste sur l'ordinateur.

3. Import depuis l'ordinateur (« Utiliser des fichiers d'écran de mon
   ordinateur… » dans « Choisir l'écran de la console ») : même pose que 2,
   à partir d'un dossier choisi -- cas fréquent d'un BOOT sauvegardé à la
   main un jour, puis la carte reflashée ou perdue.

Les doublons macOS (`._*`) sont ignorés."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .boot_sets import ORIGINAL_SCREEN_DIR, SCREEN_FILE_SUFFIX, is_kernel_screen_dtb, knulli_kernel_dtb

PathLike = Union[str, Path]

BACKUPS_DIR_NAME = "Ecrans d'origine"  # sous ~/Documents/R36S Studio
INFO_FILE = "origine.json"
BOOT_INI = "boot.ini"


def _root_files(boot_root: PathLike) -> List[Path]:
    return sorted(
        (p for p in Path(boot_root).iterdir() if p.is_file() and not p.name.startswith("._")),
        key=lambda p: p.name.lower(),
    )


def _screen_files(boot_root: PathLike) -> List[Path]:
    return [p for p in _root_files(boot_root) if p.suffix.lower() == SCREEN_FILE_SUFFIX]


def _find_saved(backups_dir: Path, fingerprint: str) -> Optional[Path]:
    if not backups_dir.is_dir():
        return None
    for folder in sorted(backups_dir.iterdir()):
        try:
            info = json.loads((folder / INFO_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(info, dict) and info.get("fingerprint") == fingerprint:
            return folder
    return None


def save_original_screen(
    boot_root: PathLike, backups_dir: PathLike, fingerprint: str, now: Optional[datetime] = None
) -> Optional[Tuple[Path, bool]]:
    """(dossier de la sauvegarde, créée maintenant ?), `None` si le BOOT n'a
    aucun `.dtb` à sa racine. Lève `OSError` si le BOOT est illisible --
    à l'appelant de ne jamais bloquer le flash pour autant."""
    dtbs = _screen_files(boot_root)
    if not dtbs:
        return None
    backups = Path(backups_dir)
    existing = _find_saved(backups, fingerprint)
    if existing is not None:
        return existing, False
    files = dtbs + [p for p in _root_files(boot_root) if p.name.lower() == BOOT_INI]
    stamp = (now or datetime.now()).strftime("%Y-%m-%d_%H-%M")
    dest = backups / f"{stamp}_{fingerprint[:12]}"
    tmp = dest.with_name(dest.name + ".partiel")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for path in files:
        shutil.copyfile(path, tmp / path.name)
    info = {"fingerprint": fingerprint, "date": stamp, "files": [p.name for p in files]}
    (tmp / INFO_FILE).write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(dest)  # jamais une sauvegarde à moitié copiée sous son vrai nom
    return dest, True


def _family(name: str) -> str:
    """`rg351mp-kernel.dtb` et `rg351mp-uboot.dtb` jouent le même rôle
    (lu par u-boot), `rk3326-r35s-linux.dtb` et `rk3326-r36s-linux.dtb`
    aussi (lu par le noyau)."""
    lower = name.lower()
    for prefix in ("rk3326", "rg351"):
        if lower.startswith(prefix):
            return prefix
    return lower


def _model(name: str) -> str:
    return name.lower().split("-", 1)[0]  # « rg351mp » de rg351mp-kernel.dtb


def target_names(saved: List[str], target: List[str]) -> Dict[str, str]:
    """Nom à donner à chaque `.dtb` sauvegardé sur la carte flashée : celui
    du `.dtb` de même rôle du firmware écrit, s'il y en a exactement un ;
    à plusieurs, celui du même modèle (dArkOSen a `rg351mp-uboot.dtb` pour
    les R36S **et** `rg351v-uboot.dtb` pour les clones, relevé le
    2026-10-14 sur une vraie carte). Sinon le nom d'origine (jamais deux
    fichiers vers le même nom)."""
    by_family: Dict[str, List[str]] = {}
    for name in target:
        by_family.setdefault(_family(name), []).append(name)
    saved_counts: Dict[str, int] = {}
    for name in saved:
        saved_counts[_family(name)] = saved_counts.get(_family(name), 0) + 1
    result = {}
    for name in saved:
        family = _family(name)
        candidates = by_family.get(family, [])
        if len(candidates) > 1:
            candidates = [c for c in candidates if _model(c) == _model(name)]
        result[name] = candidates[0] if len(candidates) == 1 and saved_counts[family] == 1 else name
    return result


def has_screen_files(folder: PathLike) -> bool:
    """Le dossier choisi contient-il des `.dtb` à sa racine ? (import depuis
    l'ordinateur : refus clair plutôt qu'un jeu vide)."""
    try:
        return bool(_screen_files(folder))
    except OSError:
        return False


def install_original_screen(saved_dir: PathLike, boot_root: PathLike) -> Optional[Dict[str, str]]:
    """Pose les `.dtb` sauvegardés dans `ecran-d-origine/` du BOOT flashé.
    `None` si le firmware écrit n'a aucun `.dtb` à la racine de son BOOT
    (ROCKNIX : écran par overlay, rien à remplacer), ou pour une carte
    KNULLI R36S sans exactement un .dtb noyau sauvegardé. Renvoie
    {nom d'origine: nom posé}."""
    saved = [p.name for p in _screen_files(saved_dir)]
    knulli = knulli_kernel_dtb(boot_root)
    if knulli is not None:
        # KNULLI R36S : seul le .dtb noyau d'origine est posé, sous le nom du
        # .dtb noyau de KNULLI (`boot_sets.py`) -- jamais celui d'u-boot.
        kernels = [name for name in saved if is_kernel_screen_dtb(name)]
        if len(kernels) != 1:
            return None
        names = {kernels[0]: Path(knulli).name}
    else:
        target = [p.name for p in _screen_files(boot_root)]
        if not target or not saved:
            return None
        names = target_names(saved, target)
    folder = Path(boot_root) / ORIGINAL_SCREEN_DIR
    shutil.rmtree(folder, ignore_errors=True)  # un import précédent ne laisse aucun reste dans le jeu
    folder.mkdir()
    for original, placed in names.items():
        shutil.copyfile(Path(saved_dir) / original, folder / placed)
    return names


__all__ = [
    "BACKUPS_DIR_NAME",
    "ORIGINAL_SCREEN_DIR",
    "has_screen_files",
    "install_original_screen",
    "save_original_screen",
    "target_names",
]
