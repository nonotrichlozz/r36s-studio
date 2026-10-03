# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Outil « Console Android » (étape 1, docs/android-adb.md) -- package
autonome : détection d'une console Android en USB via adb (lecture seule),
et propositions d'émulateurs. Ne touche jamais au code R36S existant
(`imaging/`, `partitions/`, `devices/`, `safety/`) ni à `consoles_diverses/`
(règle d'isolation du brief) -- aucune commande qui modifie le système,
jamais `adb root`, aucune élévation de privilèges n'est donc jamais
nécessaire ici."""

from __future__ import annotations

from .models import AdbDeviceEntry, AndroidDeviceInfo, DetectionResult

__all__ = [
    "AdbDeviceEntry",
    "AndroidDeviceInfo",
    "DetectionResult",
]
