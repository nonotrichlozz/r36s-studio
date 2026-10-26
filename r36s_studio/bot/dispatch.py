# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Point d'entrée unique de tout ce qui arrive de Telegram (commande,
texte, clic) : **liste blanche** d'abord. Une conversation absente de
`chat_ids` n'obtient ni session, ni réponse, ni opération -- critique depuis
que le bot sauvegarde et efface des cartes (worker élevé). Son identifiant
est seulement écrit sur la sortie d'erreur, pour l'installation.

Une conversation autorisée a sa propre `BotSession` : un clic ne répond
qu'aux questions posées dans sa propre conversation."""

from __future__ import annotations

import sys
from typing import Callable, Dict, Optional

from .config import BotConfig
from .flows import flows_by_label
from .session import BotSession, Port

__all__ = ["Dispatcher"]


class Dispatcher:
    def __init__(self, config: BotConfig, port: Port, flows: Optional[Callable[[], Dict]] = None):
        self._config = config
        self._port = port
        self._flows = flows or flows_by_label
        self.sessions: Dict[int, BotSession] = {}

    def allowed(self, chat_id) -> bool:
        return isinstance(chat_id, int) and chat_id in self._config.chat_ids

    def _session(self, chat_id) -> Optional[BotSession]:
        if not self.allowed(chat_id):
            print(f"[bot] conversation refusée (absente de chat_ids) : {chat_id}", file=sys.stderr)
            return None
        if chat_id not in self.sessions:
            self.sessions[chat_id] = BotSession(self._port, chat_id)
        return self.sessions[chat_id]

    async def on_start(self, chat_id) -> None:
        session = self._session(chat_id)
        if session is not None:
            await session.on_start()

    async def on_text(self, chat_id, text: str) -> None:
        session = self._session(chat_id)
        if session is not None:
            await session.on_text(text, self._flows())

    async def on_callback(self, chat_id, data: str) -> None:
        session = self._session(chat_id)
        if session is not None:
            await session.on_callback(data)
