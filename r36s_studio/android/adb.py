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

"""Détection et lecture d'une console Android connectée en USB via adb
(étape 1, docs/android-adb.md) -- lecture seule uniquement : jamais
`adb root`, jamais aucune commande qui modifie le système (règle explicite
du brief). Toute commande passe par un paramètre `runner` injectable (même
contrat que `subprocess.run`) avec un délai maximal par appel
(`COMMAND_TIMEOUT_SECONDS`, brief : "délai maximal par commande") -- aucun
test de ce module n'exécute adb pour de vrai."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable, List, Optional

from . import platform_tools
from .models import VALEUR_INCONNUE, AdbDeviceEntry, AndroidDeviceInfo, DetectionResult

COMMAND_TIMEOUT_SECONDS = 10.0

Runner = Callable[[List[str], float], "subprocess.CompletedProcess"]


class AdbCommandError(Exception):
    """adb a démarré mais a échoué (délai dépassé, ou n'a pas pu être
    lancé) -- jamais laissé remonter tel quel à l'écran (§5 vocabulaire du
    CLAUDE.md racine) : `detect_connected_device` la convertit en état de
    détection prudent (`adb_error`)."""


def _default_runner(args: List[str], timeout: float) -> "subprocess.CompletedProcess":
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)


def resolve_adb_path() -> Optional[str]:
    """adb déjà dans le PATH en priorité (brief : "Si adb est déjà installé
    sur la machine (dans le PATH), l'utiliser."), sinon la copie
    téléchargée par l'app elle-même (`platform_tools.installed_adb_path`),
    sinon `None` -- l'appelant (GUI) affiche alors l'écran de consentement
    au téléchargement plutôt que d'échouer silencieusement."""
    found = shutil.which("adb")
    if found:
        return found
    installed = platform_tools.installed_adb_path()
    return str(installed) if installed is not None else None


# `adb devices -l` : une ligne d'en-tête ("List of devices attached"), puis
# une ligne par appareil ("SERIAL\tSTATE  product:... model:... device:...").
# Seules les deux premières colonnes (numéro de série, état) nous
# intéressent ici -- les colonnes `-l` supplémentaires ne portent pas les
# cinq propriétés précises demandées par le brief, lues séparément via
# `getprop` (`get_device_props`).
_DEVICES_LINE_RE = re.compile(r"^(\S+)\s+(\S+)")


def list_devices(
    adb_path: str, *, runner: Runner = _default_runner, timeout: float = COMMAND_TIMEOUT_SECONDS
) -> List[AdbDeviceEntry]:
    try:
        result = runner([adb_path, "devices", "-l"], timeout)
    except subprocess.TimeoutExpired as exc:
        raise AdbCommandError(f"adb devices -l : délai dépassé ({timeout}s).") from exc
    except OSError as exc:
        raise AdbCommandError(f"adb devices -l : {exc}") from exc

    entries: List[AdbDeviceEntry] = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("List of devices attached"):
            continue
        match = _DEVICES_LINE_RE.match(stripped)
        if not match:
            continue
        entries.append(AdbDeviceEntry(serial=match.group(1), state=match.group(2)))
    return entries


# Format d'une ligne `adb shell getprop` : `[clé]: [valeur]` -- la valeur
# peut être vide (`[]`) mais jamais absente de guillemets.
_GETPROP_LINE_RE = re.compile(r"^\[(.+?)\]:\s*\[(.*)\]$")

# Les cinq propriétés demandées par le brief (§ Détection : "lire via adb
# shell getprop le fabricant, le modèle, le nom de produit, la version
# d'Android et l'architecture").
_GETPROP_KEYS = {
    "manufacturer": "ro.product.manufacturer",
    "model": "ro.product.model",
    "product_name": "ro.product.name",
    "android_version": "ro.build.version.release",
    "abi": "ro.product.cpu.abi",
}


def get_device_props(
    adb_path: str, serial: str, *, runner: Runner = _default_runner, timeout: float = COMMAND_TIMEOUT_SECONDS
) -> AndroidDeviceInfo:
    """Un seul aller-retour (`adb -s SERIAL shell getprop`, tout le dump)
    plutôt que cinq commandes séparées -- une propriété absente du dump
    retombe sur `VALEUR_INCONNUE` (même sentinelle et même traitement à
    l'affichage que `consoles_diverses/models.py::_VALEUR_INCONNUE`),
    jamais une exception : un dump partiel reste exploitable."""
    try:
        result = runner([adb_path, "-s", serial, "shell", "getprop"], timeout)
    except subprocess.TimeoutExpired as exc:
        raise AdbCommandError(f"adb shell getprop : délai dépassé ({timeout}s).") from exc
    except OSError as exc:
        raise AdbCommandError(f"adb shell getprop : {exc}") from exc

    values = {}
    for line in result.stdout.splitlines():
        match = _GETPROP_LINE_RE.match(line.strip())
        if match:
            values[match.group(1)] = match.group(2)

    def _get(key: str) -> str:
        raw = values.get(_GETPROP_KEYS[key], "")
        return raw if raw else VALEUR_INCONNUE

    return AndroidDeviceInfo(
        serial=serial,
        manufacturer=_get("manufacturer"),
        model=_get("model"),
        product_name=_get("product_name"),
        android_version=_get("android_version"),
        abi=_get("abi"),
    )


def detect_connected_device(adb_path: Optional[str], *, runner: Runner = _default_runner) -> DetectionResult:
    """Point d'entrée unique de détection (§ Détection du brief) -- jamais
    d'exception : toute commande adb qui échoue (délai dépassé, binaire
    introuvable) retombe sur l'état `adb_error` plutôt que de remonter
    jusqu'à l'écran."""
    if not adb_path:
        return DetectionResult(state="adb_missing")

    try:
        devices = list_devices(adb_path, runner=runner)
    except AdbCommandError as exc:
        return DetectionResult(state="adb_error", error_detail=str(exc))

    if not devices:
        return DetectionResult(state="no_device")

    ready = [entry for entry in devices if entry.state == "device"]

    if len(ready) > 1:
        # Aucun moyen fiable de savoir lequel concerne l'utilisateur --
        # cet outil ne propose pas de sélecteur à cette étape (brief, hors
        # périmètre implicite). L'utilisateur débranche les appareils en
        # trop et réessaie.
        return DetectionResult(state="multiple_devices", devices=devices)

    if not ready:
        if any(entry.state == "unauthorized" for entry in devices):
            return DetectionResult(state="unauthorized", devices=devices)
        # Un état adb existe (`offline`, `no permissions`...) qui n'est ni
        # prêt ni explicitement "non autorisé" -- traité comme "aucun
        # appareil exploitable" plutôt qu'inventer un état de plus non
        # demandé par le brief ; `devices` reste joint pour un diagnostic
        # en texte brut côté écran (brief : "sortie adb affichée en texte
        # brut").
        return DetectionResult(state="no_device", devices=devices)

    try:
        info = get_device_props(adb_path, ready[0].serial, runner=runner)
    except AdbCommandError as exc:
        return DetectionResult(state="adb_error", error_detail=str(exc), devices=devices)
    return DetectionResult(state="ready", device=info, devices=devices)


__all__ = [
    "COMMAND_TIMEOUT_SECONDS",
    "Runner",
    "AdbCommandError",
    "resolve_adb_path",
    "list_devices",
    "get_device_props",
    "detect_connected_device",
]
