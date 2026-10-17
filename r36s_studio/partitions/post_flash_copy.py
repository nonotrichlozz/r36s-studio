# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Copies de fichiers à l'intérieur d'une partition de la carte, juste après
un flash -- étapes manuelles qu'un firmware demande une seule fois après
l'écriture de son image (ex. ROCKNIX sur H700 : copier
`device_trees/sun50i-h700-anbernic-rg40xx-v.dtb` à la racine de la
partition ROCKNIX sous le nom `dtb.img`).

Décrites par la fiche du catalogue (`options.*[].telechargement.
apres_flash`, donnée externe) puis transmises au worker élevé
(`flash --copy-after-flash ÉTIQUETTE SOURCE DESTINATION`) : tout est donc
validé deux fois, ici, avec les mêmes règles -- côté GUI avant l'élévation,
côté worker avant d'écrire. Chemins relatifs uniquement, segments simples
(lettres, chiffres, `.`, `_`, `-`), jamais `..`, et la destination doit
rester à l'intérieur de la partition une fois résolue. Aucune suppression,
aucun écrasement d'un fichier de la source elle-même : seule une copie,
dans la même partition.

Ne dépend jamais de `gui/` (§5, dépendances de `partitions/`)."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Union

_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
MAX_COPIES = 8

PathLike = Union[str, "os.PathLike[str]"]


class PostFlashCopyError(Exception):
    """Une copie demandée est invalide (chemin refusé) ou a échoué."""


@dataclass(frozen=True)
class PostFlashCopy:
    partition: str
    source: str
    destination: str


def chemin_relatif_sur(path: Any) -> bool:
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")):
        return False
    segments = path.split("/")
    for segment in segments:
        if segment in ("", ".", "..") or not _SEGMENT_PATTERN.match(segment):
            return False
    return True


def etiquette_sure(label: Any) -> bool:
    return isinstance(label, str) and bool(_LABEL_PATTERN.match(label))


def valider(copie: PostFlashCopy) -> None:
    if not etiquette_sure(copie.partition):
        raise PostFlashCopyError(f"Partition refusée : {copie.partition!r}")
    for chemin in (copie.source, copie.destination):
        if not chemin_relatif_sur(chemin):
            raise PostFlashCopyError(f"Chemin refusé : {chemin!r}")
    if copie.source == copie.destination:
        raise PostFlashCopyError("Source et destination identiques")


def copies_depuis_json(data: Any) -> Optional[List[PostFlashCopy]]:
    """Parsing défensif de `apres_flash` (fiche du catalogue). `None` si la
    liste est absente ; `None` aussi si UNE entrée est invalide -- jamais
    une installation à moitié réglée : le bouton n'est alors pas proposé
    (`telechargement.py`), plutôt qu'un flash qui laisserait une console
    qui ne démarre pas."""
    if data is None:
        return []
    if not isinstance(data, list) or len(data) > MAX_COPIES:
        return None
    copies: List[PostFlashCopy] = []
    for item in data:
        if not isinstance(item, dict):
            return None
        copie = PostFlashCopy(
            partition=item.get("partition"),
            source=item.get("copier"),
            destination=item.get("vers"),
        )
        try:
            valider(copie)
        except PostFlashCopyError:
            return None
        copies.append(copie)
    return copies


def appliquer(partition_root: PathLike, copies: Iterable[PostFlashCopy]) -> List[str]:
    """Applique `copies` sur la partition montée en `partition_root`.
    Renvoie les destinations écrites. Lève `PostFlashCopyError` (source
    absente, chemin qui sortirait de la partition) -- l'appelant
    (`__main__.py`) en fait un avertissement clair, jamais un échec du
    flash déjà vérifié."""
    root = Path(partition_root).resolve()
    ecrites: List[str] = []
    for copie in copies:
        valider(copie)
        source = (root / copie.source).resolve()
        destination = (root / copie.destination).resolve()
        for chemin in (source, destination):
            if root != chemin and root not in chemin.parents:
                raise PostFlashCopyError(f"Chemin hors de la partition : {chemin}")
        if not source.is_file():
            raise PostFlashCopyError(f"Fichier introuvable sur la carte : {copie.source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        ecrites.append(copie.destination)
    return ecrites


__all__ = [
    "MAX_COPIES",
    "PostFlashCopy",
    "PostFlashCopyError",
    "appliquer",
    "chemin_relatif_sur",
    "copies_depuis_json",
    "etiquette_sure",
    "valider",
]
