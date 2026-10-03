# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Identification de la console à partir des `.dtb` du BOOT d'origine
(§4.5/§4.6, enchaînement identification → téléchargement ArkOS).

**Consoles clones** : critère validé par l'outil officiel ArkOS -- le
*nom* du fichier `.dtb` présent sur la carte, pas son contenu. Confirmé
sur du vrai matériel : `rk3326-evb-lp3-v12-linux.dtb` désigne un clone,
tandis que `rk3326-r35s-linux.dtb`/`gameconsole-r36s.dtb` désignent une
R36S/R35S standard -- y compris quand le clone a été relevé avec deux
`.dtb` au contenu strictement identique (un seul portant ce nom). Les
images ArkOS et ROCKNIX standard ne démarrent pas sur ce matériel ;
EmuELEC, lui, fonctionne (`identify/releases.py::
EMUELEC_R36S_RELEASES_URL`, §5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Union

from .dtb import DtbInfo, InvalidDtbError, parse_dtb_file

__all__ = [
    "identify_from_boot_directory",
    "DtbInfo",
    "InvalidDtbError",
    "IdentifyResult",
    "IdentifyFailureReason",
    "CLONE_DTB_FILENAMES",
]

# Noms de fichier `.dtb` connus pour désigner une console clone plutôt
# qu'une R36S/R35S standard (voir note de module) -- en minuscules, la
# comparaison se fait insensible à la casse. Un seul cas confirmé à ce
# jour ; ensemble plutôt qu'une chaîne unique pour accueillir d'autres
# clones sans changer la forme de ce module.
CLONE_DTB_FILENAMES = {"rk3326-evb-lp3-v12-linux.dtb"}


class IdentifyFailureReason(Enum):
    """Cause de l'échec d'identification (étape 2 du mode assisté, §5) --
    chacune a son propre message, plutôt qu'un « impossible d'identifier »
    générique qui ne dit rien de ce qui s'est passé ni de la marche à
    suivre."""

    MOUNT_FAILED = "mount_failed"  # BOOT non montable -- carte illisible/défaillante, courant sur les cartes fournies avec la console
    NO_DTB_FOUND = "no_dtb_found"  # partition lisible, aucun .dtb dessus (ex. carte fraîchement flashée)
    ALL_DTB_INVALID = "all_dtb_invalid"  # .dtb présents mais tous illisibles, corrompus, ou sans compatible racine exploitable


@dataclass
class IdentifyResult:
    info: Optional[DtbInfo] = None
    failure_reason: Optional[IdentifyFailureReason] = None
    # Diagnostic à journaliser dans tous les cas (§5 mode assisté) --
    # `scanned_directory` reste `None` quand le montage lui-même a échoué
    # (rien n'a pu être scanné, voir `WizardIdentifyRunner`) ; `detail`
    # porte le message brut de l'exception dans ce même cas.
    scanned_directory: Optional[str] = None
    examined_files: List[str] = field(default_factory=list)
    detail: Optional[str] = None
    # Console clone (voir note de module) -- déterminé à partir du *nom*
    # des `.dtb` trouvés, indépendamment de leur validité de parsing ou du
    # `.dtb` retenu pour `info` (`identify_from_boot_directory`).
    is_clone: bool = False

    @property
    def ok(self) -> bool:
        return self.info is not None


def identify_from_boot_directory(directory: Union[str, Path]) -> IdentifyResult:
    """Cherche le premier `.dtb` exploitable dans `directory` -- le
    mountpoint de la partition BOOT (étape 2 du mode assisté, avant toute
    copie) ou un dossier d'archive déjà extrait (mode expert, après
    `extract_boot`) : les deux ne sont qu'un dossier contenant les
    fichiers du BOOT. Distingue `NO_DTB_FOUND` (rien de ce nom, ou dossier
    absent/illisible) de `ALL_DTB_INVALID` (des `.dtb` existent mais aucun
    n'est exploitable -- invalide/corrompu, ou structurellement valide
    mais sans `compatible` racine : une identification « ? » n'aide
    personne, ce n'est pas un succès). Ne lève jamais. `scanned_directory`/
    `examined_files` sont toujours renseignés, succès compris, pour
    pouvoir être journalisés (§5 mode assisté : « journalise dans tous
    les cas le chemin monté et la liste des fichiers examinés »)."""
    root = Path(directory)
    scanned_directory = str(root)
    try:
        candidates = sorted(root.rglob("*.dtb"))
    except OSError:
        candidates = []
    examined_files = [str(candidate) for candidate in candidates]
    # Sur le nom des fichiers trouvés, pas sur celui retenu pour `info`
    # ci-dessous (note de module) : une carte clone relevée sur du vrai
    # matériel porte deux `.dtb` au contenu identique, un seul portant le
    # nom qui l'identifie comme clone -- l'autre pourrait très bien être
    # celui choisi pour l'identification normale (tri alphabétique).
    is_clone = any(candidate.name.lower() in CLONE_DTB_FILENAMES for candidate in candidates)

    if not candidates:
        return IdentifyResult(
            failure_reason=IdentifyFailureReason.NO_DTB_FOUND,
            scanned_directory=scanned_directory,
            examined_files=examined_files,
            is_clone=is_clone,
        )

    for candidate in candidates:
        try:
            info = parse_dtb_file(candidate)
        except (InvalidDtbError, OSError):
            continue
        if not info.board_compatible:
            continue
        return IdentifyResult(
            info=info, scanned_directory=scanned_directory, examined_files=examined_files, is_clone=is_clone
        )

    return IdentifyResult(
        failure_reason=IdentifyFailureReason.ALL_DTB_INVALID,
        scanned_directory=scanned_directory,
        examined_files=examined_files,
        is_clone=is_clone,
    )
