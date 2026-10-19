# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Interface Telegram de R36S Studio, pour une machine sans interface
graphique possible (Eee PC i686 sous antiX : pas de PySide6 en 32 bits).

Le bot pilote le même cœur que la GUI, jamais une réimplémentation :
`doublons/run.py`, `tri/run.py`, `identify/firmware_download.py`.
**Règle d'import absolue** : rien sous `r36s_studio.gui` ni PySide6
(`tests/test_bot_imports.py`). Les chaînes viennent de `r36s_studio/
strings.py`, le même fichier que la GUI.

- `config.py` : jeton et liste blanche de chat_id (`telegram.json` à côté
  de `config.json`, chmod 600, jamais dans le dépôt) ;
- `progress.py` : progression -> édition de message, au plus une toutes
  les 2 à 3 s, édition finale garantie avec le compte exact ;
- `session.py`/`flows.py` : menu, questions à boutons, les trois outils ;
- `telegram_app.py` : adaptateur python-telegram-bot (`requirements-bot.txt`),
  importé seulement au lancement (`python -m r36s_studio.bot`)."""
