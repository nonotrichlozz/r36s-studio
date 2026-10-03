# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Résolution des fichiers liés (docs/doublons.md, règle critique) : un
jeu peut tenir en plusieurs fichiers -- `.cue`+`.bin`, `.m3u`+plusieurs
`.chd`, `.gdi`+ses pistes. Ce module lit le contenu de ces trois formats
de manifeste pour savoir *quels autres fichiers* ils décrivent, sans
jamais rien décider lui-même de ce qui doit se passer si un fichier
référencé est introuvable -- ça reste la responsabilité de l'appelant
(`scan.py`), qui doit exclure et signaler, jamais déplacer un groupe
incomplet."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List

__all__ = ["LinkedResolution", "resolve_manifest"]

_CUE_FILE_RE = re.compile(r'FILE\s+"([^"]+)"', re.IGNORECASE)
_GDI_QUOTED_RE = re.compile(r'"([^"]+)"')


def _parse_cue(text: str) -> List[str]:
    """`FILE "xxx.bin" BINARY` -- une piste par ligne `FILE`, un `.cue`
    multi-pistes en a donc plusieurs."""
    return _CUE_FILE_RE.findall(text)


def _parse_m3u(text: str) -> List[str]:
    """Texte brut, un chemin par ligne -- lignes vides et commentaires
    (`#...`, convention M3U) ignorés."""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def _parse_gdi(text: str) -> List[str]:
    """Première ligne = nombre de pistes (ignorée, pas un nom de fichier).
    Chaque ligne suivante : `num lba type taille_secteur nom_fichier ...`,
    le nom de fichier étant le 5e champ, ou entre guillemets s'il contient
    des espaces."""
    lines = text.splitlines()
    filenames: List[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped:
            continue
        quoted = _GDI_QUOTED_RE.search(stripped)
        if quoted:
            filenames.append(quoted.group(1))
            continue
        parts = stripped.split()
        if len(parts) >= 5:
            filenames.append(parts[4])
    return filenames


_PARSERS: Dict[str, Callable[[str], List[str]]] = {
    ".cue": _parse_cue,
    ".m3u": _parse_m3u,
    ".gdi": _parse_gdi,
}


@dataclass
class LinkedResolution:
    manifest: Path
    members: List[Path]  # fichiers référencés réellement trouvés sur le disque
    missing: List[str]  # noms référencés introuvables -- le groupe doit être exclu


def resolve_manifest(manifest_path: Path) -> LinkedResolution:
    """Lit `manifest_path` (`.cue`/`.m3u`/`.gdi`) et résout chaque fichier
    qu'il référence -- recherche insensible à la casse, dans le même
    dossier que le manifeste uniquement (jamais dans un sous-dossier :
    aucun des trois formats ne décrit de son propre contenu une
    arborescence, seulement des noms de fichiers)."""
    parser = _PARSERS[manifest_path.suffix.lower()]
    try:
        text = manifest_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return LinkedResolution(manifest=manifest_path, members=[], missing=[])

    referenced_names = parser(text)
    directory = manifest_path.parent
    try:
        entries = {entry.name.lower(): entry for entry in directory.iterdir() if entry.is_file()}
    except OSError:
        entries = {}

    members: List[Path] = []
    missing: List[str] = []
    for name in referenced_names:
        resolved = entries.get(Path(name).name.lower())
        if resolved is None:
            missing.append(name)
        else:
            members.append(resolved)
    return LinkedResolution(manifest=manifest_path, members=members, missing=missing)
