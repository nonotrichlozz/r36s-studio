# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Une conversation avec le bot, indépendante de la bibliothèque Telegram :
`Port` (envoyer, éditer) est fourni par `telegram_app.py` en vrai et par
un faux dans les tests (aucun appel réseau).

- Menu à clavier persistant : les libellés des outils de la GUI.
- `ask` : question à boutons en ligne, attend la réponse (jamais de choix
  par défaut).
- `run_with_progress` : travail sur un thread, message de progression
  limité par `ProgressRelay`, bouton Annuler coopératif.
- Une seule opération à la fois par conversation.

Textes trop longs pour Telegram (4096 caractères) : coupés proprement."""

from __future__ import annotations

import asyncio
import itertools
import threading
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Sequence, Tuple

from r36s_studio.strings import tr

from .progress import DEFAULT_INTERVAL, DEFAULT_MIN_GAP, ProgressRelay

MAX_MESSAGE_CHARS = 4000

__all__ = ["BotSession", "Button", "Port", "menu_labels"]


@dataclass(frozen=True)
class Button:
    label: str
    data: str


Keyboard = List[List[Button]]
Choices = Sequence[Sequence[Tuple[str, str]]]  # lignes de (libellé, valeur)


class Port(Protocol):
    async def send(
        self, chat_id: int, text: str, buttons: Optional[Keyboard] = None, menu: Optional[List[List[str]]] = None
    ) -> int: ...

    async def edit(self, chat_id: int, message_id: int, text: str, buttons: Optional[Keyboard] = None) -> None: ...


def menu_labels() -> List[List[str]]:
    """Mêmes libellés que les outils de l'accueil de la GUI."""
    return [[tr("home_tile_find_duplicates")], [tr("home_tile_filter_games")], [tr("bot_menu_firmware")]]


def fit(text: str) -> str:
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return text[: MAX_MESSAGE_CHARS - 2].rstrip() + "\n…"


class BotSession:
    def __init__(
        self,
        port: Port,
        chat_id: int,
        interval: float = DEFAULT_INTERVAL,
        min_gap: float = DEFAULT_MIN_GAP,
    ):
        self._port = port
        self.chat_id = chat_id
        self._interval = interval
        self._min_gap = min_gap
        self._tokens = itertools.count()
        self._questions: Dict[str, "asyncio.Future"] = {}
        self._cancels: Dict[str, threading.Event] = {}
        self._task: Optional["asyncio.Task"] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # --- messages ------------------------------------------------------------

    async def send(self, text: str, buttons: Optional[Keyboard] = None, menu: bool = False) -> int:
        return await self._port.send(self.chat_id, fit(text), buttons, menu_labels() if menu else None)

    async def edit(self, message_id: int, text: str, buttons: Optional[Keyboard] = None) -> None:
        await self._port.edit(self.chat_id, message_id, fit(text), buttons)

    async def ask(self, text: str, choices: Choices, message_id: Optional[int] = None) -> str:
        """Envoie (ou réécrit `message_id`) `text` avec les boutons, attend
        le clic. Le message garde la réponse choisie, sans boutons."""
        token = f"q{next(self._tokens)}"
        labels = {value: label for row in choices for label, value in row}
        keyboard = [[Button(label, f"{token}:{value}") for label, value in row] for row in choices]
        future = asyncio.get_running_loop().create_future()
        self._questions[token] = future
        if message_id is None:
            message_id = await self.send(text, keyboard)
        else:
            await self.edit(message_id, text, keyboard)
        try:
            value = await future
        finally:
            self._questions.pop(token, None)
        await self.edit(message_id, f"{text}\n\n→ {labels.get(value, value)}")
        return value

    def ask_from_thread(self, text: str, choices: Choices) -> str:
        """`ask` depuis le thread de travail (question au milieu d'une
        opération : dossier volumineux, fichier qui résiste...)."""
        assert self.loop is not None
        return asyncio.run_coroutine_threadsafe(self.ask(text, choices), self.loop).result()

    async def on_callback(self, data: str) -> None:
        token, _, value = (data or "").partition(":")
        future = self._questions.get(token)
        if future is not None and not future.done():
            future.set_result(value)
        elif token in self._cancels:
            self._cancels[token].set()

    # --- travail long ----------------------------------------------------------

    async def run_with_progress(
        self,
        render: Callable[[Optional[Tuple]], str],
        work: Callable[[Callable[..., None], Callable[[], bool]], Any],
        cancellable: bool = True,
    ) -> Any:
        """`work(report, should_cancel)` sur un thread ; `render(valeurs)`
        donne le texte du message (`None` avant le premier événement)."""
        relay = ProgressRelay(self._interval, self._min_gap)
        cancel = threading.Event()
        token = f"c{next(self._tokens)}"
        buttons = [[Button(tr("bot_cancel"), f"{token}:")]] if cancellable else None
        self._cancels[token] = cancel
        message_id = await self.send(render(None), buttons)

        async def edit(values: Optional[Tuple], final: bool) -> None:
            await self.edit(message_id, render(values), None if final else buttons)

        job = asyncio.ensure_future(asyncio.to_thread(work, relay.report, cancel.is_set))
        try:
            return await relay.pump(job, edit)
        finally:
            self._cancels.pop(token, None)

    # --- menu ------------------------------------------------------------------

    async def on_start(self) -> None:
        await self.send(tr("bot_welcome"), menu=True)

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    async def on_text(self, text: str, flows: Dict[str, Callable[["BotSession"], Awaitable[None]]]) -> None:
        """`flows` : libellé du menu -> flux. Lancé en tâche de fond : les
        clics sur les boutons doivent continuer d'arriver pendant le flux."""
        self.loop = asyncio.get_running_loop()
        flow = flows.get((text or "").strip())
        if flow is None:
            await self.send(tr("bot_help"), menu=True)
            return
        if self.busy():
            await self.send(tr("bot_busy"))
            return
        self._task = asyncio.ensure_future(self._run_flow(flow))

    async def _run_flow(self, flow: Callable[["BotSession"], Awaitable[None]]) -> None:
        try:
            await flow(self)
        except Exception as exc:  # jamais une conversation figée sans réponse
            await self.send(tr("error_generic") + "\n\n" + tr("bot_detail", detail=f"{type(exc).__name__}: {exc}"))
