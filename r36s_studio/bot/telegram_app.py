# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Adaptateur python-telegram-bot (`requirements-bot.txt`, jamais
`requirements.txt`) : traduit les messages Telegram vers `BotSession` et
`Port` vers l'API du bot. Seul module du paquet qui importe `telegram`,
et seulement dans `run`/`PtbPort` : le reste se teste sans la bibliothèque.

Liste blanche : seules les conversations de `telegram.json` sont servies ;
une autre ne reçoit rien, et son identifiant est écrit sur la sortie d'erreur
(pour le recopier dans `chat_ids` à l'installation)."""

from __future__ import annotations

import asyncio
import sys
from typing import Dict, List, Optional

from .config import BotConfig
from .flows import flows_by_label
from .session import BotSession, Keyboard

__all__ = ["PtbPort", "run"]

EDIT_ATTEMPTS = 3


class PtbPort:
    """`Port` au-dessus de `telegram.Bot`. Une édition refusée pour cause de
    débit (RetryAfter) est retentée après le délai demandé : l'édition
    finale d'une progression ne doit jamais se perdre."""

    def __init__(self, bot):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
        from telegram.error import BadRequest, RetryAfter

        self._bot = bot
        self._inline = lambda rows: InlineKeyboardMarkup(
            [[InlineKeyboardButton(b.label, callback_data=b.data) for b in row] for row in rows]
        )
        self._menu = lambda rows: ReplyKeyboardMarkup(rows, resize_keyboard=True, is_persistent=True)
        self._bad_request = BadRequest
        self._retry_after = RetryAfter

    def _markup(self, buttons: Optional[Keyboard], menu: Optional[List[List[str]]] = None):
        if buttons:
            return self._inline(buttons)
        return self._menu(menu) if menu else None

    async def _call(self, method, **kwargs):
        for attempt in range(EDIT_ATTEMPTS):
            try:
                return await method(**kwargs)
            except self._retry_after as exc:
                delay = exc.retry_after  # secondes, ou timedelta selon la version
                seconds = delay.total_seconds() if hasattr(delay, "total_seconds") else float(delay)
                await asyncio.sleep(seconds + 0.5)
                if attempt == EDIT_ATTEMPTS - 1:
                    raise
        return None

    async def send(self, chat_id: int, text: str, buttons: Optional[Keyboard] = None, menu=None) -> int:
        message = await self._call(
            self._bot.send_message, chat_id=chat_id, text=text, reply_markup=self._markup(buttons, menu)
        )
        return message.message_id

    async def edit(self, chat_id: int, message_id: int, text: str, buttons: Optional[Keyboard] = None) -> None:
        try:
            await self._call(
                self._bot.edit_message_text,
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=self._markup(buttons),
            )
        except self._bad_request as exc:
            if "not modified" not in str(exc).lower():  # même texte : déjà à jour
                raise


def run(config: BotConfig) -> None:
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

    application = Application.builder().token(config.token).build()
    port = PtbPort(application.bot)
    sessions: Dict[int, BotSession] = {}
    allowed = filters.Chat(chat_id=list(config.chat_ids))

    def session_for(chat_id: int) -> BotSession:
        if chat_id not in sessions:
            sessions[chat_id] = BotSession(port, chat_id)
        return sessions[chat_id]

    async def on_start(update, _context) -> None:
        await session_for(update.effective_chat.id).on_start()

    async def on_text(update, _context) -> None:
        await session_for(update.effective_chat.id).on_text(update.message.text, flows_by_label())

    async def on_callback(update, _context) -> None:
        query = update.callback_query
        await query.answer()
        chat_id = query.message.chat_id if query.message is not None else None
        if chat_id in config.chat_ids:
            await session_for(chat_id).on_callback(query.data)

    async def on_refused(update, _context) -> None:
        if update.effective_chat is not None:
            print(f"[bot] conversation refusée (absente de chat_ids) : {update.effective_chat.id}", file=sys.stderr)

    application.add_handler(CommandHandler("start", on_start, filters=allowed))
    application.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, on_text))
    application.add_handler(CallbackQueryHandler(on_callback))
    application.add_handler(MessageHandler(~allowed, on_refused))
    application.run_polling(allowed_updates=["message", "callback_query"])
