# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Préparation d'une carte ROCKNIX pour une R36S, juste après le flash --
les deux réglages faits à la main le 10-11/10/2026 sur une R36S d'origine
(carte mère « R36S V12 2023-08 ») avant qu'elle démarre :

1. `extlinux/extlinux.conf` remplacé par `extlinux.conf.r36s` (fourni par
   l'image RK3326) : sans ça, `boot.scr` choisit le .dtb d'après une tension
   ADC où la R36S ne figure pas, et retombe sur celui de l'Odroid Go 2.
   L'original est gardé en `extlinux.conf.orig` (jamais écrasé).
2. `overlays/mipi-panel.dtbo` : le fichier d'écran. Le nom ne dit pas quelle
   console l'utilise (la R36S d'origine de test n'affiche le logo qu'avec
   `r36s_clone`) : on pose le premier de `PANELS`, et tous les fichiers
   disponibles sont copiés dans `overlays/panels/` pour pouvoir en changer
   ensuite sans internet.

Fichiers d'écran : release `panel_overlays` de stolen/rnix (fork de
ROCKNIX/distribution). Aucune licence explicite (GPL au mieux) : jamais
embarqués dans le paquet, téléchargés à la demande dans
`~/Documents/R36S Studio/Firmwares/panels/`. Le dépôt ne publie aucune
somme de contrôle : les empreintes ci-dessous ont été relevées le
2026-10-11 et tout fichier différent est refusé."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from .rocknix import RocknixAsset, RocknixReleaseError, _default_opener, default_firmware_downloads_dir, download_asset

PANEL_DOWNLOAD_BASE_URL = "https://github.com/stolen/rnix/releases/download/panel_overlays/"
PANEL_FILE_PREFIX = "mipi-panel.dtbo."

# Ordre d'essai demandé : r36s_clone (le seul qui a marché sur la R36S
# d'origine de test), puis panel4 -> panel1.
PANELS: Tuple[Tuple[str, str], ...] = (
    ("r36s_clone", "cb5f6fd860c7fbb82e2bc6b07c7e1db197388dbe9df74bfde5c28c3b3be9e743"),
    ("r36s-panel4", "846ee139c96f0c121116234c63025b97cf3f4f947147e6761185ab965f4b77f3"),
    ("r36s-panel3", "364921615dffcb772e33c6cfbe5af0d7079dbc9a22ca71a3fab0ab96e03b31a2"),
    ("r36s-panel2", "8d1dddc717f7b3aceeadc063209bf4f235092a37268e9549b7a92a5d848aa767"),
    ("r36s-panel1", "c2005751c98cd505c686d65d18308ad1abe105a9bd86c6beef87b35a22938054"),
)
DEFAULT_PANEL = PANELS[0][0]

PathLike = Union[str, Path]


class R36sConfigMissing(Exception):
    """`extlinux/extlinux.conf.r36s` absent : ce n'est pas l'image ROCKNIX
    RK3326 attendue -- rien n'est modifié."""


def panels_cache_dir() -> Path:
    return default_firmware_downloads_dir() / "panels"


def _sha256(path: Path) -> Optional[str]:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def available_panels(cache_dir: PathLike, panels: Sequence[Tuple[str, str]] = PANELS) -> List[str]:
    """Panneaux du cache dont l'empreinte est la bonne, dans l'ordre d'essai."""
    return [name for name, sha in panels if _sha256(Path(cache_dir) / f"{PANEL_FILE_PREFIX}{name}") == sha]


def download_missing_panels(
    cache_dir: PathLike, panels: Sequence[Tuple[str, str]] = PANELS, opener=_default_opener
) -> List[str]:
    """Télécharge les panneaux absents ou abîmés du cache ; renvoie ceux qui
    n'ont pas pu l'être (hors ligne, empreinte différente -- fichier jamais
    gardé). Ne lève jamais."""
    cache = Path(cache_dir)
    present = set(available_panels(cache, panels))
    failed = []
    for name, sha in panels:
        if name in present:
            continue
        filename = f"{PANEL_FILE_PREFIX}{name}"
        asset = RocknixAsset(name=filename, download_url=PANEL_DOWNLOAD_BASE_URL + filename, size_bytes=0)
        try:
            download_asset(asset, cache / filename, expected_sha256=sha, opener=opener)
        except (RocknixReleaseError, OSError):  # OSError : dossier du cache impossible à créer
            failed.append(name)
    return failed


def prepare_r36s_card(
    partition_root: PathLike,
    cache_dir: PathLike,
    preferred: str = DEFAULT_PANEL,
    panels: Sequence[Tuple[str, str]] = PANELS,
) -> Optional[str]:
    """Applique les deux réglages R36S sur la partition ROCKNIX montée en
    `partition_root`. Renvoie le panneau posé, ou `None` si aucun fichier
    d'écran n'est disponible (extlinux réglé quand même)."""
    root = Path(partition_root)
    extlinux = root / "extlinux"
    r36s_conf = extlinux / "extlinux.conf.r36s"
    if not r36s_conf.is_file():
        raise R36sConfigMissing(str(r36s_conf))
    conf, orig = extlinux / "extlinux.conf", extlinux / "extlinux.conf.orig"
    if conf.is_file() and not orig.exists():
        shutil.copyfile(conf, orig)
    shutil.copyfile(r36s_conf, conf)

    available = available_panels(cache_dir, panels)
    if not available:
        return None
    card_panels = root / "overlays" / "panels"
    card_panels.mkdir(parents=True, exist_ok=True)
    for name in available:
        shutil.copyfile(Path(cache_dir) / f"{PANEL_FILE_PREFIX}{name}", card_panels / f"{PANEL_FILE_PREFIX}{name}")
    chosen = preferred if preferred in available else available[0]
    shutil.copyfile(card_panels / f"{PANEL_FILE_PREFIX}{chosen}", root / "overlays" / "mipi-panel.dtbo")
    return chosen


__all__ = [
    "DEFAULT_PANEL",
    "PANELS",
    "R36sConfigMissing",
    "available_panels",
    "download_missing_panels",
    "panels_cache_dir",
    "prepare_r36s_card",
]
