# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Gestion des dossiers d'archive BOOT/EASYROMS extraits de l'ancienne
carte (§4.4, workflow à deux cartes) : emplacement par défaut, nommage
horodaté, et liste des archives existantes — pour que l'injection sur la
carte neuve (étapes D/E) propose un choix plutôt que de redemander un
dossier à chaque fois.

`default_archives_dir()` n'est qu'une **proposition** : les étapes A/B
(§5, écran Choix du fichier) laissent toujours l'utilisateur l'accepter ou
choisir un autre emplacement, y compris un disque externe — l'horodatage
du nom de dossier, lui, reste toujours généré automatiquement à
l'intérieur de l'emplacement choisi, quel qu'il soit.

Nommage : `{LABEL}_{AAAA-MM-JJ}_{HH-MM}`, ex. `BOOT_2026-07-06_00-21`."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

ARCHIVES_DIR_NAME = "R36S Studio"
TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M"
_ARCHIVE_NAME_RE = re.compile(r"^(?P<label>[A-Za-z0-9]+)_(?P<timestamp>\d{4}-\d{2}-\d{2}_\d{2}-\d{2})$")


def default_archives_dir() -> Path:
    """Emplacement proposé par défaut pour les extractions BOOT/EASYROMS
    (§5, écran Choix du fichier) — jamais imposé, jamais `~/.config` (§6) :
    un dossier visible de l'utilisateur, dans ses Documents, qu'il peut
    remplacer par n'importe quel autre emplacement."""
    return Path.home() / "Documents" / ARCHIVES_DIR_NAME


def new_archive_path(label: str, base_dir: Optional[Path] = None, now: Optional[datetime] = None) -> Path:
    """Chemin (non créé) de la prochaine archive `label` — l'horodatage est
    toujours généré ici, jamais laissé au choix de l'appelant, pour que le
    nommage reste cohérent et que `list_archives` puisse les retrouver."""
    base = base_dir if base_dir is not None else default_archives_dir()
    timestamp = (now or datetime.now()).strftime(TIMESTAMP_FORMAT)
    return base / f"{label}_{timestamp}"


def list_archives(label: str, base_dir: Optional[Path] = None) -> List[Path]:
    """Archives `label` existantes, la plus récente d'abord. Liste vide si
    le dossier n'existe pas encore (première utilisation) — jamais une
    erreur."""
    base = base_dir if base_dir is not None else default_archives_dir()
    if not base.is_dir():
        return []
    matches = [p for p in base.iterdir() if p.is_dir() and p.name.startswith(f"{label}_")]
    return sorted(matches, key=lambda p: p.name, reverse=True)


def parse_archive_timestamp(path: Path) -> Optional[datetime]:
    """Extrait l'horodatage du nom de dossier (`None` si le dossier n'a pas
    été nommé par `new_archive_path` — ex. sélectionné manuellement via
    Parcourir) pour un affichage convivial (§5) plutôt que le nom brut."""
    match = _ARCHIVE_NAME_RE.match(path.name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("timestamp"), "%Y-%m-%d_%H-%M")
    except ValueError:
        return None


__all__ = ["default_archives_dir", "new_archive_path", "list_archives", "parse_archive_timestamp"]
