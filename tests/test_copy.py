"""Tests de la boucle de copie par blocs (imaging/copy.py) — uniquement des
objets `BytesIO` en mémoire, aucun périphérique ni fichier réel."""

from __future__ import annotations

import io

import pytest

from r36s_studio.imaging.copy import BLOCK_SIZE, OperationCancelled, copy_range


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


# --- mode non borné (total_bytes=None, utilisé pour le flash) -------------


def test_unbounded_copy_stops_at_source_eof():
    data = b"w" * 5000
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copied = copy_range(source, destination, total_bytes=None, block_size=1024)

    assert copied == len(data)
    assert destination.getvalue() == data


def test_unbounded_copy_reports_done_as_total():
    data = b"v" * 3000
    source = io.BytesIO(data)
    destination = io.BytesIO()
    events = []

    copy_range(source, destination, total_bytes=None, on_progress=events.append, block_size=1024)

    assert events
    last = events[-1]
    assert last.done == len(data)
    assert last.total == len(data)  # jamais une estimation trompeuse (§2 n°5)


def test_total_bytes_defaults_to_none_meaning_unbounded():
    data = b"u" * 2000
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copied = copy_range(source, destination, block_size=512)  # total_bytes omis

    assert copied == len(data)


# --- alignement secteur (écriture Windows, §4.3) ---------------------------


def test_sector_padding_rounds_final_block_up_but_done_counts_real_bytes():
    data = b"p" * 1500  # ni multiple de 512, ni de block_size
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copied = copy_range(source, destination, total_bytes=None, block_size=1024, sector_size=512)

    assert copied == len(data)  # "done" ne compte jamais le remplissage
    written = destination.getvalue()
    assert written[: len(data)] == data
    assert len(written) % 512 == 0  # chaque écriture reste alignée sur le secteur
    assert all(b == 0 for b in written[len(data) :])  # le remplissage est bien à zéro


def test_no_padding_when_sector_size_not_given():
    data = b"q" * 1500
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copy_range(source, destination, total_bytes=None, block_size=1024)

    assert len(destination.getvalue()) == len(data)  # aucun octet ajouté


# --- annulation (bouton Annuler de l'écran Exécution, §5) ------------------


def test_should_cancel_stops_copy_and_raises():
    data = b"c" * 10_000
    source = io.BytesIO(data)
    destination = io.BytesIO()
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 2  # annule après 2 blocs

    with pytest.raises(OperationCancelled) as excinfo:
        copy_range(source, destination, total_bytes=None, block_size=1024, should_cancel=should_cancel)

    assert excinfo.value.done == 2048  # 2 blocs de 1024 déjà écrits
    assert destination.getvalue() == data[:2048]


def test_should_cancel_preserves_data_already_written():
    """Ce qui a déjà été écrit au moment de l'annulation doit être flush
    (et fsync si possible) -- pas de données perdues en mémoire tampon."""
    data = b"d" * 4096
    source = io.BytesIO(data)
    destination = io.BytesIO()
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1  # annule après le premier bloc

    with pytest.raises(OperationCancelled) as excinfo:
        copy_range(
            source, destination, total_bytes=None, block_size=1024, should_cancel=should_cancel
        )

    assert excinfo.value.done == 1024
    assert destination.getvalue() == data[:1024]


def test_should_cancel_before_any_read_writes_nothing():
    data = b"d" * 4096
    source = io.BytesIO(data)
    destination = io.BytesIO()

    with pytest.raises(OperationCancelled) as excinfo:
        copy_range(
            source, destination, total_bytes=None, block_size=1024, should_cancel=lambda: True
        )

    assert excinfo.value.done == 0
    assert destination.getvalue() == b""


def test_no_cancellation_when_should_cancel_always_false():
    data = b"e" * 4096
    source = io.BytesIO(data)
    destination = io.BytesIO()

    copied = copy_range(
        source, destination, total_bytes=None, block_size=1024, should_cancel=lambda: False
    )

    assert copied == len(data)
