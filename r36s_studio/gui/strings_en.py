# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Alias de `r36s_studio.strings_en` (chaînes déplacées hors de `gui/` pour le
bot Telegram) : le même objet module, donc `from .strings_en import tr` et les
`patch("r36s_studio.gui.strings_en....")` des tests restent valables."""

import sys

from r36s_studio import strings_en as _module

sys.modules[__name__] = _module
