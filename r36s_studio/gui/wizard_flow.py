"""Séquencement du mode assisté (§5 mode assisté) : 7 étapes affichées à
l'utilisateur, mais 8 « jobs » suivis en interne -- l'étape 3 (« Copie du
BOOT et d'EASYROMS ») recouvre en réalité deux jobs indépendants
(`EXTRACT_BOOT`, `EXTRACT_EASYROMS`), chacun avec son propre statut fait/
pas fait. C'est ce qui permet à la reprise après erreur de ne rejouer que
le job qui a réellement échoué : si le BOOT a été copié avec succès et
qu'EASYROMS échoue, `current_job()` continue de désigner EASYROMS après
l'échec (le BOOT reste marqué fait), donc « Reprendre » (qui relance
`current_job()`) ne refait jamais un job déjà réussi.

Ne pilote rien lui-même (aucun accès disque, aucun signal Qt) --
`main_window.py` interroge `current_job()`/`mark_done()` et déclenche
l'opération correspondante. Cette séparation rend la logique de reprise
testable sans QApplication ni matériel."""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


class WizardJob(Enum):
    DETECT_SOURCE = "detect_source"  # étape 1
    IDENTIFY = "identify"  # étape 2
    EXTRACT_BOOT = "extract_boot"  # étape 3 (a)
    EXTRACT_EASYROMS = "extract_easyroms"  # étape 3 (b)
    DETECT_TARGET = "detect_target"  # étape 4
    FLASH = "flash"  # étape 5
    INJECT_BOOT = "inject_boot"  # étape 6
    EJECT = "eject"  # étape 7


_ORDER = [
    WizardJob.DETECT_SOURCE,
    WizardJob.IDENTIFY,
    WizardJob.EXTRACT_BOOT,
    WizardJob.EXTRACT_EASYROMS,
    WizardJob.DETECT_TARGET,
    WizardJob.FLASH,
    WizardJob.INJECT_BOOT,
    WizardJob.EJECT,
]


class WizardFlow:
    def __init__(self) -> None:
        self._done: Dict[WizardJob, bool] = {}
        self.reset()

    def reset(self) -> None:
        self._done = {job: False for job in _ORDER}

    def current_job(self) -> Optional[WizardJob]:
        """Premier job non fait, dans l'ordre -- `None` une fois le
        parcours entièrement terminé."""
        for job in _ORDER:
            if not self._done[job]:
                return job
        return None

    def mark_done(self, job: WizardJob) -> None:
        self._done[job] = True

    def is_done(self, job: WizardJob) -> bool:
        return self._done[job]

    def is_finished(self) -> bool:
        return self.current_job() is None
