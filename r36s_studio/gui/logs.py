# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Alias de `r36s_studio.logs` (déplacé hors de `gui/` : le cœur et le bot
Telegram l'utilisent sans jamais importer `gui`) -- le même objet module,
donc `from . import logs` et les `patch("r36s_studio.gui.logs....")`
restent valables."""

import sys

from r36s_studio import logs as _module

sys.modules[__name__] = _module
