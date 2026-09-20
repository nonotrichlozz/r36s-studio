# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

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
