"""Identification de la console à partir des `.dtb` du BOOT d'origine
(§4.5/§4.6, enchaînement identification → téléchargement ArkOS)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from .dtb import DtbInfo, InvalidDtbError, parse_dtb_file

__all__ = [
    "identify_from_boot_directory",
    "DtbInfo",
    "InvalidDtbError",
    "IdentifyResult",
    "IdentifyFailureReason",
]


class IdentifyFailureReason(Enum):
    """Cause de l'échec d'identification (étape 2 du mode assisté, §5) --
    chacune a son propre message, plutôt qu'un « impossible d'identifier »
    générique qui ne dit rien de ce qui s'est passé ni de la marche à
    suivre."""

    MOUNT_FAILED = "mount_failed"  # BOOT non montable -- carte illisible/défaillante, courant sur les cartes fournies avec la console
    NO_DTB_FOUND = "no_dtb_found"  # partition lisible, aucun .dtb dessus
    ALL_DTB_INVALID = "all_dtb_invalid"  # .dtb présents mais tous illisibles/corrompus


@dataclass
class IdentifyResult:
    info: Optional[DtbInfo] = None
    failure_reason: Optional[IdentifyFailureReason] = None

    @property
    def ok(self) -> bool:
        return self.info is not None


def identify_from_boot_directory(directory: Union[str, Path]) -> IdentifyResult:
    """Cherche le premier `.dtb` exploitable dans `directory` -- le
    mountpoint de la partition BOOT (étape 2 du mode assisté, avant toute
    copie) ou un dossier d'archive déjà extrait (mode expert, après
    `extract_boot`) : les deux ne sont qu'un dossier contenant les
    fichiers du BOOT. Distingue `NO_DTB_FOUND` (rien de ce nom, ou dossier
    absent/illisible) de `ALL_DTB_INVALID` (des `.dtb` existent mais
    aucun n'est un DTB valide) -- ne lève jamais."""
    root = Path(directory)
    try:
        candidates = sorted(root.rglob("*.dtb"))
    except OSError:
        candidates = []

    if not candidates:
        return IdentifyResult(failure_reason=IdentifyFailureReason.NO_DTB_FOUND)

    for candidate in candidates:
        try:
            return IdentifyResult(info=parse_dtb_file(candidate))
        except (InvalidDtbError, OSError):
            continue

    return IdentifyResult(failure_reason=IdentifyFailureReason.ALL_DTB_INVALID)
