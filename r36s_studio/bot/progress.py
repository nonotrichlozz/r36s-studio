# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Pont progression -> message Telegram.

Les fonctions du cœur (`doublons/run.py`...) tournent sur un thread et
signalent leur progression jusqu'à ~4 fois par seconde ; Telegram plafonne
à environ un message par seconde et par conversation, éditions comprises.
`ProgressRelay` ne garde que le dernier événement reçu et n'édite le
message qu'une fois toutes les `interval` secondes (2,5 s), seulement s'il
a changé. À la fin du travail, une **édition finale** porte toujours le
dernier compte exact reçu (§2 n°5 : jamais de progression simulée, jamais
de dernier événement perdu), au moins `min_gap` après l'édition précédente."""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Awaitable, Callable, Optional, Tuple

DEFAULT_INTERVAL = 2.5
DEFAULT_MIN_GAP = 1.1

__all__ = ["DEFAULT_INTERVAL", "DEFAULT_MIN_GAP", "ProgressRelay"]


class ProgressRelay:
    def __init__(
        self,
        interval: float = DEFAULT_INTERVAL,
        min_gap: float = DEFAULT_MIN_GAP,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._interval = interval
        self._min_gap = min_gap
        self._clock = clock
        self._lock = threading.Lock()
        self._latest: Optional[Tuple] = None
        self._shown: Optional[Tuple] = None
        self._last_edit = float("-inf")

    def report(self, *values) -> None:
        """Appelé depuis le thread de travail, à chaque événement."""
        with self._lock:
            self._latest = values

    @property
    def latest(self) -> Optional[Tuple]:
        with self._lock:
            return self._latest

    async def pump(self, job: "asyncio.Future", edit: Callable[[Optional[Tuple], bool], Awaitable[None]]):
        """Édite pendant que `job` tourne (`edit(valeurs, False)`), puis
        toujours une dernière fois avec le compte exact (`edit(valeurs,
        True)`, qui retire aussi le bouton Annuler) ; renvoie le résultat
        de `job`. Les valeurs valent `None` si aucun événement n'est venu."""
        while not job.done():
            await asyncio.wait({job}, timeout=self._interval)
            if not job.done():
                await self._push(edit, final=False)
        await self._push(edit, final=True)
        return job.result()

    async def _push(self, edit: Callable[[Optional[Tuple], bool], Awaitable[None]], final: bool) -> None:
        latest = self.latest
        if not final and (latest is None or latest == self._shown):
            return  # rien de nouveau
        wait = self._min_gap - (self._clock() - self._last_edit)
        if wait > 0:
            if not final:
                return  # trop tôt : la prochaine édition (ou la finale) le portera
            await asyncio.sleep(wait)
        await edit(latest, final)
        self._shown = latest
        self._last_edit = self._clock()
