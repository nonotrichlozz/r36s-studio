"""Tests du protocole JSON Lines (protocol.py), y compris la redirection
`configure()` utilisée par le worker élevé (§3, gui/elevate.py)."""

from __future__ import annotations

import io
import json

from r36s_studio import protocol


def teardown_function() -> None:
    # `configure` modifie un état module-level : le remettre à stdout après
    # chaque test pour ne pas polluer les autres tests du fichier.
    protocol.configure(None)


def test_emit_writes_json_line_to_stdout_by_default(capsys):
    protocol.emit({"type": "log", "level": "info", "msg": "bonjour"})
    out = capsys.readouterr().out
    assert json.loads(out.strip()) == {"type": "log", "level": "info", "msg": "bonjour"}


def test_configure_redirects_emit_to_given_stream(capsys):
    buffer = io.StringIO()
    protocol.configure(buffer)

    protocol.emit({"type": "done", "ok": True})

    assert capsys.readouterr().out == ""  # rien sur stdout
    assert json.loads(buffer.getvalue().strip()) == {"type": "done", "ok": True}


def test_configure_none_restores_stdout(capsys):
    buffer = io.StringIO()
    protocol.configure(buffer)
    protocol.configure(None)

    protocol.emit({"type": "log", "level": "info", "msg": "retour à stdout"})

    assert buffer.getvalue() == ""
    assert "retour à stdout" in capsys.readouterr().out


def test_emit_progress_rounds_speed():
    buffer = io.StringIO()
    protocol.configure(buffer)

    protocol.emit_progress(done=100, total=1000, speed=123.7)

    event = json.loads(buffer.getvalue().strip())
    assert event == {"type": "progress", "done": 100, "total": 1000, "speed": 124}


def test_emit_error_and_emit_done_shapes():
    buffer = io.StringIO()
    protocol.configure(buffer)

    protocol.emit_error("IO_ERROR", "boom")
    protocol.emit_done(False)

    lines = [json.loads(line) for line in buffer.getvalue().splitlines()]
    assert lines == [
        {"type": "error", "code": "IO_ERROR", "msg": "boom"},
        {"type": "done", "ok": False},
    ]
