# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Alias de `r36s_studio.strings` (chaînes déplacées hors de `gui/` pour le
bot Telegram) : le même objet module, donc `from .strings import tr` et les
`patch("r36s_studio.gui.strings....")` des tests restent valables."""

import sys

from r36s_studio import strings as _module

sys.modules[__name__] = _module
