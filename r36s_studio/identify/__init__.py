"""Identification de la console à partir des `.dtb` du BOOT d'origine
(§4.5/§4.6, enchaînement identification → téléchargement ArkOS)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .dtb import DtbInfo, InvalidDtbError, parse_dtb_file

__all__ = ["identify_from_boot_directory", "DtbInfo", "InvalidDtbError"]


def identify_from_boot_directory(directory: Union[str, Path]) -> Optional[DtbInfo]:
    """Cherche le premier `.dtb` exploitable dans `directory` -- le
    mountpoint de la partition BOOT (étape 2 du mode assisté, avant toute
    copie) ou un dossier d'archive déjà extrait (mode expert, après
    `extract_boot`) : les deux ne sont qu'un dossier contenant les
    fichiers du BOOT. `None` si le dossier n'existe pas, ne contient aucun
    `.dtb`, ou qu'aucun n'est un DTB valide -- ne lève jamais."""
    root = Path(directory)
    try:
        candidates = sorted(root.rglob("*.dtb"))
    except OSError:
        return None

    for candidate in candidates:
        try:
            return parse_dtb_file(candidate)
        except (InvalidDtbError, OSError):
            continue
    return None
