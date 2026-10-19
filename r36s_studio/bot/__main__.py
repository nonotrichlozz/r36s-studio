# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""`python -m r36s_studio.bot` : lance le bot Telegram (voir `__init__.py`)."""

from __future__ import annotations

import sys

from r36s_studio import config as app_config
from r36s_studio import i18n
from r36s_studio.strings import tr

from .config import BotConfigError, load_bot_config, write_template


def main() -> int:
    i18n.set_language(app_config.load_config().language)
    try:
        config = load_bot_config()
    except BotConfigError as exc:
        if exc.key == "bot_config_missing":
            try:
                write_template(exc.path)
            except OSError:
                pass
        print(tr(exc.key, path=str(exc.path)), file=sys.stderr)
        return 2
    try:
        import telegram  # dépendance absente : message clair plutôt qu'une trace

        from .telegram_app import run
    except ImportError:
        print(tr("bot_missing_dependency"), file=sys.stderr)
        return 2
    del telegram
    print(tr("bot_started"), file=sys.stderr)
    run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
