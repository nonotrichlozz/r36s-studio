"""Adaptateur python-telegram-bot (`bot/telegram_app.py::PtbPort`) contre une
fausse bibliothèque `telegram` (aucune dépendance installée, aucun réseau)."""

from __future__ import annotations

import asyncio
import types
from unittest.mock import patch

import pytest

from r36s_studio.bot.session import Button


class RetryAfter(Exception):
    def __init__(self, retry_after):
        super().__init__("flood")
        self.retry_after = retry_after


class BadRequest(Exception):
    pass


def _fake_telegram():
    telegram = types.ModuleType("telegram")
    telegram.InlineKeyboardButton = lambda text, callback_data: ("btn", text, callback_data)
    telegram.InlineKeyboardMarkup = lambda rows: ("inline", rows)
    telegram.ReplyKeyboardMarkup = lambda rows, **kw: ("menu", rows, kw)
    error = types.ModuleType("telegram.error")
    error.RetryAfter = RetryAfter
    error.BadRequest = BadRequest
    telegram.error = error
    return {"telegram": telegram, "telegram.error": error}


class FakeBot:
    def __init__(self, failures=()):
        self.calls = []
        self._failures = list(failures)

    async def _maybe_fail(self):
        if self._failures:
            raise self._failures.pop(0)

    async def send_message(self, **kwargs):
        await self._maybe_fail()
        self.calls.append(("send", kwargs))
        return types.SimpleNamespace(message_id=7)

    async def edit_message_text(self, **kwargs):
        await self._maybe_fail()
        self.calls.append(("edit", kwargs))


@pytest.fixture
def port_class():
    with patch.dict("sys.modules", _fake_telegram()):
        from r36s_studio.bot.telegram_app import PtbPort

        yield PtbPort


def test_send_builds_inline_buttons_or_the_persistent_menu(port_class):
    bot = FakeBot()
    port = port_class(bot)

    assert asyncio.run(port.send(1, "question", [[Button("Oui", "q0:yes")]])) == 7
    assert asyncio.run(port.send(1, "menu", None, [["Chercher les doublons"]])) == 7

    assert bot.calls[0][1]["reply_markup"] == ("inline", [[("btn", "Oui", "q0:yes")]])
    menu = bot.calls[1][1]["reply_markup"]
    assert menu[0] == "menu" and menu[2]["is_persistent"] is True


def test_rate_limited_edit_is_retried_after_the_requested_delay(port_class):
    bot = FakeBot(failures=[RetryAfter(0)])
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with patch("r36s_studio.bot.telegram_app.asyncio.sleep", fake_sleep):
        asyncio.run(port_class(bot).edit(1, 7, "1 900 fichier(s)"))

    assert sleeps == [0.5] and bot.calls == [("edit", {"chat_id": 1, "message_id": 7, "text": "1 900 fichier(s)", "reply_markup": None})]


def test_identical_edit_is_not_an_error_but_others_are(port_class):
    asyncio.run(port_class(FakeBot(failures=[BadRequest("Message is not modified")])).edit(1, 7, "x"))
    with pytest.raises(BadRequest):
        asyncio.run(port_class(FakeBot(failures=[BadRequest("Chat not found")])).edit(1, 7, "x"))
