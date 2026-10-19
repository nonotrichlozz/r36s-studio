"""Réglages du bot (`bot/config.py`) : jeton et liste blanche dans
`telegram.json`, chmod 600 exigé hors Windows, jeton jamais affiché."""

from __future__ import annotations

import json
import os
import platform
from unittest.mock import patch

import pytest

from r36s_studio.bot import __main__ as bot_main
from r36s_studio.bot.config import BotConfigError, load_bot_config, telegram_config_path, write_template

POSIX = platform.system() != "Windows"


def _write(path, data, mode=0o600):
    path.write_text(json.dumps(data), encoding="utf-8")
    os.chmod(path, mode)
    return path


def test_lives_next_to_config_json():
    from r36s_studio import config as app_config

    assert telegram_config_path() == app_config.config_dir() / "telegram.json"


def test_valid_file_is_read_and_token_never_shown(tmp_path):
    path = _write(tmp_path / "telegram.json", {"token": "123456:SECRET", "chat_ids": [42, -1001]})
    config = load_bot_config(path)
    assert config.token == "123456:SECRET" and config.chat_ids == {42, -1001}
    assert "SECRET" not in repr(config)


@pytest.mark.parametrize(
    "data",
    [
        {"chat_ids": [1]},
        {"token": "sans-deux-points", "chat_ids": [1]},
        {"token": "1:a", "chat_ids": []},
        {"token": "1:a", "chat_ids": ["1"]},
        {"token": "1:a", "chat_ids": [True]},
        ["pas un objet"],
    ],
)
def test_invalid_contents_are_refused(tmp_path, data):
    with pytest.raises(BotConfigError) as exc:
        load_bot_config(_write(tmp_path / "telegram.json", data))
    assert exc.value.key == "bot_config_invalid"


def test_missing_file(tmp_path):
    with pytest.raises(BotConfigError) as exc:
        load_bot_config(tmp_path / "absent.json")
    assert exc.value.key == "bot_config_missing"


@pytest.mark.skipif(not POSIX, reason="droits POSIX")
@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604, 0o660])
def test_readable_by_others_is_refused_before_reading_the_token(tmp_path, mode):
    path = _write(tmp_path / "telegram.json", {"token": "1:a", "chat_ids": [1]}, mode)
    with pytest.raises(BotConfigError) as exc:
        load_bot_config(path)
    assert exc.value.key == "bot_config_permissions"


def test_template_is_created_private(tmp_path):
    path = tmp_path / "sub" / "telegram.json"
    write_template(path)
    assert json.loads(path.read_text(encoding="utf-8")) == {"token": "", "chat_ids": []}
    if POSIX:
        assert path.stat().st_mode & 0o777 == 0o600


def test_main_creates_a_template_and_explains_when_missing(capsys):
    assert bot_main.main() == 2
    err = capsys.readouterr().err
    assert "token" in err and "chat_ids" in err
    assert telegram_config_path().is_file()


def test_main_without_the_library_says_how_to_install(tmp_path, capsys):
    _write(telegram_config_path(), {"token": "1:a", "chat_ids": [1]})
    with patch.dict("sys.modules", {"telegram": None}):
        assert bot_main.main() == 2
    assert "requirements-bot.txt" in capsys.readouterr().err
