# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Empêche les sous-processus console (PowerShell) de faire apparaître leur
propre fenêtre visible sous Windows (§1 : « aucune ligne de commande, jamais,
à aucune étape »).

Bug corrigé, confirmé sur le binaire empaqueté réel (jamais reproduit depuis
les sources) : chaque appel `subprocess.run(["powershell", ...])` de ce
projet (détection des périphériques, verrouillage de volumes, formatage,
éjection...) ouvrait sa propre fenêtre de console visible -- plusieurs par
opération -- dès que le processus appelant n'a lui-même aucune console à
laquelle rattacher l'enfant. Depuis les sources, l'interpréteur Python
tourne presque toujours avec une console déjà attachée (héritée par les
enfants sans en ouvrir de nouvelle) ; une fois empaqueté avec PyInstaller
(`console=False`, §6), le processus n'a plus aucune console du tout --
Windows en ouvre alors une nouvelle, visible, pour chaque sous-processus
console lancé. C'est précisément cette différence qui a révélé le problème :
invisible depuis les sources, systématique sur le binaire réel.

`CREATE_NO_WINDOW` (indicateur natif de `CreateProcess`, exposé par
`subprocess.CREATE_NO_WINDOW`) supprime cette fenêtre inconditionnellement,
qu'une console existe déjà ou non -- la solution retenue plutôt que
`STARTUPINFO`/`SW_HIDE` (qui ne fait que *masquer* une fenêtre qui continue
d'exister brièvement, un correctif partiel déjà écarté ailleurs dans ce
projet pour les fenêtres système, voir `gui/elevate.py::_launch_windows`).

N'existe que sous Windows (`subprocess.CREATE_NO_WINDOW` est absent du
module sur macOS/Linux, et `creationflags` lève `ValueError` si transmis en
dehors de Windows) -- `no_console_kwargs()` retourne donc un dict vide sur
les autres OS, à étaler (`**no_console_kwargs()`) dans n'importe quel appel
`subprocess.run`/`Popen` existant plutôt que de remplacer `subprocess.run`
lui-même : les appelants gardent leur appel direct (donc les tests déjà en
place, qui patchent `subprocess.run` au même endroit qualifié, n'ont pas
besoin de changer de cible)."""

from __future__ import annotations

import subprocess
import sys


def no_console_kwargs() -> dict:
    """`{"creationflags": subprocess.CREATE_NO_WINDOW}` sous Windows,
    `{}` ailleurs -- voir le docstring de module pour le contexte complet."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
