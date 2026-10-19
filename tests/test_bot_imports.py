"""Règle d'import absolue du bot Telegram : rien sous `r36s_studio.gui`, ni
PySide6 -- la machine visée (Eee PC i686, antiX) n'a pas PySide6."""

from __future__ import annotations

import importlib
import sys

BOT_MODULES = (
    "r36s_studio.bot",
    "r36s_studio.bot.config",
    "r36s_studio.bot.progress",
    "r36s_studio.bot.session",
    "r36s_studio.bot.cards",
    "r36s_studio.bot.flows",
    "r36s_studio.bot.telegram_app",
    "r36s_studio.bot.__main__",
)


def test_bot_imports_without_pyside6_and_never_touches_gui():
    saved = dict(sys.modules)
    try:
        for name in list(sys.modules):
            if name.split(".")[0] in ("r36s_studio", "PySide6", "shiboken6"):
                del sys.modules[name]
        # PySide6 introuvable : tout `import PySide6...` lève ImportError.
        sys.modules["PySide6"] = None
        sys.modules["shiboken6"] = None
        for name in BOT_MODULES:
            importlib.import_module(name)
        loaded = [name for name in sys.modules if name == "r36s_studio.gui" or name.startswith("r36s_studio.gui.")]
        assert loaded == []
        assert "telegram" not in sys.modules  # la bibliothèque n'est chargée qu'au lancement
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


def test_requirements_keep_pyside6_out_of_the_bot():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent

    def requirements(name):
        lines = (root / name).read_text(encoding="utf-8").splitlines()
        return [line.split(">")[0].split("=")[0].strip().lower() for line in lines if line.strip() and not line.startswith("#")]

    assert requirements("requirements-bot.txt") == ["python-telegram-bot"]
    assert "python-telegram-bot" not in requirements("requirements.txt")
