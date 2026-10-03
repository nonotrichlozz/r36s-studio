# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Séquencement du mode assisté (§5 mode assisté) : parcours de clonage à
5 étapes, chacune son propre job -- détecter la carte source, créer
l'image (copie complète ou système seul, au choix), détecter la carte
neuve (éjecte d'abord la source), restaurer l'image, éjecter. Plus simple
que l'ancien parcours à 7 étapes/8 jobs (identification DTB puis
extraction/injection BOOT-EASYROMS, propres à ArkOS) : ce parcours ne
travaille plus qu'en image disque brute, donc `current_job()` avance
toujours un-pour-un avec les étapes affichées, sans plus jamais avoir
besoin qu'un même écran recouvre deux jobs indépendants.

Ne pilote rien lui-même (aucun accès disque, aucun signal Qt) --
`main_window.py` interroge `current_job()`/`mark_done()` et déclenche
l'opération correspondante. Cette séparation rend la logique de reprise
testable sans QApplication ni matériel : un job qui échoue n'est jamais
marqué fait, donc « Reprendre » (qui relance `current_job()`) ne rejoue
jamais un job déjà réussi."""

from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


class WizardJob(Enum):
    DETECT_SOURCE = "detect_source"  # étape 1
    CREATE_IMAGE = "create_image"  # étape 2 (choix complet/système, puis copie)
    DETECT_TARGET = "detect_target"  # étape 3 (éjecte la source, puis détecte)
    RESTORE_IMAGE = "restore_image"  # étape 4
    EJECT = "eject"  # étape 5


_ORDER = [
    WizardJob.DETECT_SOURCE,
    WizardJob.CREATE_IMAGE,
    WizardJob.DETECT_TARGET,
    WizardJob.RESTORE_IMAGE,
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
