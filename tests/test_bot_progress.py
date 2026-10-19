"""Pont progression -> message (`bot/progress.py`) : regroupement des
événements (Telegram : ~1 message/s/conversation), édition finale toujours
faite avec le compte exact (§2 n°5)."""

from __future__ import annotations

import asyncio
import threading
import time

from r36s_studio.bot.progress import ProgressRelay


def _run(relay, work):
    edits = []
    stamps = []

    async def edit(values, final):
        edits.append((values, final))
        stamps.append(time.monotonic())

    async def main():
        job = asyncio.ensure_future(asyncio.to_thread(work))
        return await relay.pump(job, edit)

    return asyncio.run(main()), edits, stamps


def test_four_events_per_second_become_spaced_edits_and_the_last_count_is_exact():
    relay = ProgressRelay(interval=0.2, min_gap=0.1)

    def work():
        for count in range(1, 41):  # 40 événements à ~4/s accélérés (toutes les 10 ms)
            relay.report(count)
            time.sleep(0.01)
        return "fini"

    result, edits, stamps = _run(relay, work)

    assert result == "fini"
    assert edits[-1] == ((40,), True)  # dernier événement jamais perdu
    assert len(edits) <= 4  # ~0,4 s de travail, une édition toutes les 0,2 s au plus
    assert all(b - a >= 0.09 for a, b in zip(stamps, stamps[1:]))  # jamais deux éditions collées
    counts = [values[0] for values, _final in edits]
    assert counts == sorted(counts)  # jamais un compte simulé ou en arrière


def test_final_edit_happens_even_without_change_and_without_any_event():
    relay = ProgressRelay(interval=0.05, min_gap=0.0)
    _result, edits, _ = _run(relay, lambda: None)
    assert edits == [(None, True)]  # retire au moins le bouton Annuler


def test_final_edit_waits_the_minimum_gap_after_a_periodic_one():
    relay = ProgressRelay(interval=0.05, min_gap=0.3)
    done = threading.Event()

    def work():
        relay.report(1)
        time.sleep(0.12)  # une édition périodique a lieu ici
        relay.report(2)
        done.set()

    _result, edits, stamps = _run(relay, work)
    assert edits[0] == ((1,), False) and edits[-1] == ((2,), True)
    assert stamps[-1] - stamps[0] >= 0.29


def test_worker_exception_still_gets_the_final_edit_then_propagates():
    relay = ProgressRelay(interval=0.05, min_gap=0.0)

    def work():
        relay.report(7)
        raise OSError("carte retirée")

    edits = []

    async def edit(values, final):
        edits.append((values, final))

    async def main():
        job = asyncio.ensure_future(asyncio.to_thread(work))
        await relay.pump(job, edit)

    try:
        asyncio.run(main())
    except OSError:
        pass
    else:
        raise AssertionError("l'erreur du travail doit remonter")
    assert edits[-1] == ((7,), True)
