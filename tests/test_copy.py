"""Tests de la boucle de copie par blocs (imaging/copy.py) — uniquement des
objets `BytesIO` en mémoire, aucun périphérique ni fichier réel."""

from __future__ import annotations

import io

from r36s_studio.imaging.copy import BLOCK_SIZE, copy_range


def test_default_block_size_is_4_mib():
    assert BLOCK_SIZE == 4 * 1024 * 1024


def test_copies_exact_byte_count():
    data = bytes(range(256)) * 100  # 25 600 octets
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copied = copy_range(source, destination, total_bytes=len(data), block_size=1024)

    assert copied == len(data)
    assert destination.getvalue() == data


def test_stops_at_total_bytes_even_if_source_has_more():
    data = b"x" * 10_000
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copied = copy_range(source, destination, total_bytes=4096, block_size=1024)

    assert copied == 4096
    assert destination.getvalue() == data[:4096]


def test_handles_source_shorter_than_total():
    data = b"y" * 500
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copied = copy_range(source, destination, total_bytes=10_000, block_size=1024)

    assert copied == 500  # source épuisée avant d'atteindre "total"


def test_progress_callback_reports_final_done_and_total():
    data = b"z" * 8192
    source = io.BytesIO(data)
    destination = io.BytesIO()
    events = []

    copy_range(source, destination, total_bytes=len(data), on_progress=events.append, block_size=1024)

    assert events  # au moins l'événement final est toujours émis
    last = events[-1]
    assert last.done == len(data)
    assert last.total == len(data)


def test_no_progress_callback_by_default():
    data = b"a" * 4096
    source = io.BytesIO(data)
    destination = io.BytesIO()

    # Ne doit pas planter si on_progress n'est pas fourni.
    copied = copy_range(source, destination, total_bytes=len(data), block_size=512)
    assert copied == len(data)
