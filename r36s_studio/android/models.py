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

"""Modèles de données du package `android/` (étape 1, docs/android-adb.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Sentinelle pour une propriété absente du dump `adb shell getprop` --
# même principe et même mot que `consoles_diverses/models.py::
# _VALEUR_INCONNUE` (traduit à l'écran, jamais affiché brut).
VALEUR_INCONNUE = "inconnu"


@dataclass
class AdbDeviceEntry:
    """Une ligne de `adb devices -l` -- `state` est la valeur brute d'adb
    (`device`/`unauthorized`/`offline`...), jamais traduite ici : la
    traduction en message convivial reste côté GUI (§5 du CLAUDE.md
    racine, vocabulaire)."""

    serial: str
    state: str


@dataclass
class AndroidDeviceInfo:
    """Les cinq propriétés lues par `adb.get_device_props` (§ Détection du
    brief) -- une valeur absente du dump `getprop` vaut `VALEUR_INCONNUE`,
    jamais une exception : un dump partiel reste exploitable."""

    serial: str
    manufacturer: str
    model: str
    product_name: str
    android_version: str
    abi: str


@dataclass
class DetectionResult:
    """Résultat de `adb.detect_connected_device` -- `state` pilote l'écran
    affiché (§ Interface du brief) :

    - `adb_missing` -- adb introuvable (ni dans le PATH, ni déjà
      téléchargé par l'app) ; l'écran de consentement au téléchargement
      s'affiche.
    - `adb_error` -- une commande adb a échoué ou dépassé son délai
      maximal (`error_detail` porte le message brut, jamais affiché sans
      traduction, §5 vocabulaire).
    - `no_device` -- aucun appareil listé par `adb devices -l`.
    - `unauthorized` -- un appareil est listé mais aucun n'est à l'état
      `device` ; au moins un est `unauthorized`.
    - `multiple_devices` -- plusieurs appareils à l'état `device` en même
      temps -- aucun moyen de savoir lequel concerne l'utilisateur, cet
      outil ne propose pas de sélecteur à cette étape (brief, hors
      périmètre implicite : aucune mention d'un choix multi-appareils)."
    - `ready` -- exactement un appareil à l'état `device` ; `device` porte
      ses propriétés lues via `getprop`."""

    state: str
    device: Optional[AndroidDeviceInfo] = None
    devices: List[AdbDeviceEntry] = field(default_factory=list)
    error_detail: Optional[str] = None


__all__ = ["VALEUR_INCONNUE", "AdbDeviceEntry", "AndroidDeviceInfo", "DetectionResult"]
