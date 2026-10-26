"""Liste blanche (`bot/dispatch.py`) : une conversation absente de
`chat_ids` ne déclenche **aucune** opération -- ni sauvegarde, ni
effacement, ni aucun autre outil, ni même une réponse."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from r36s_studio.bot.config import BotConfig
from r36s_studio.bot.dispatch import Dispatcher
from r36s_studio.bot.flows import flows_by_label
from r36s_studio.bot.session import menu_labels

from tests.test_bot_flows import FakePort

ALLOWED, INTRUDER = 1001, 666


def _dispatcher(port, flows):
    return Dispatcher(BotConfig(token="1:x", chat_ids=frozenset({ALLOWED})), port, flows=lambda: flows)


def test_an_unknown_conversation_can_trigger_nothing(capsys):
    labels = [row[0] for row in menu_labels()]
    flows = {label: AsyncMock() for label in labels}
    assert set(flows) == set(flows_by_label())  # tous les outils, dont sauvegarde et effacement
    port = FakePort()

    async def main():
        dispatcher = _dispatcher(port, flows)
        with patch("r36s_studio.bot.flows.run_worker") as run_worker:
            await dispatcher.on_start(INTRUDER)
            for label in labels:
                await dispatcher.on_text(INTRUDER, label)
            await dispatcher.on_callback(INTRUDER, "q0:erase")
            await asyncio.sleep(0.05)
        return dispatcher, run_worker

    dispatcher, run_worker = asyncio.run(main())
    assert all(flow.await_count == 0 for flow in flows.values())
    run_worker.assert_not_called()
    assert port.order == [] and dispatcher.sessions == {}  # pas même une réponse
    assert f"conversation refusée (absente de chat_ids) : {INTRUDER}" in capsys.readouterr().err


def test_an_intruder_cannot_answer_a_question_asked_to_the_allowed_conversation():
    port = FakePort()
    answered = []

    async def flow(session):
        answered.append(await session.ask("Effacer la carte ?", [[("Effacer", "erase"), ("Annuler", "cancel")]]))

    async def main():
        dispatcher = _dispatcher(port, {"Remettre": flow})
        await dispatcher.on_text(ALLOWED, "Remettre")
        await asyncio.sleep(0.05)
        token_data = port.messages[port.order[-1]][1][0][0].data  # « Effacer »
        await dispatcher.on_callback(INTRUDER, token_data)
        await asyncio.sleep(0.05)
        assert answered == []  # l'intrus n'a rien déclenché
        await dispatcher.on_callback(ALLOWED, token_data.replace("erase", "cancel"))
        await asyncio.sleep(0.05)

    asyncio.run(main())
    assert answered == ["cancel"]


def test_non_integer_ids_are_never_allowed():
    dispatcher = _dispatcher(FakePort(), {})
    assert not dispatcher.allowed(str(ALLOWED)) and not dispatcher.allowed(None) and dispatcher.allowed(ALLOWED)
