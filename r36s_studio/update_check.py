# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Vérification des mises à jour (docs/claude/packaging.md) : interroge la
dernière Release GitHub. Sans Qt -- appelée depuis un thread par
`gui/partition_runner.py::UpdateCheckRunner`. Toute erreur réseau ou de
format = `None`, jamais d'exception : l'app marche hors ligne (§1)."""

from __future__ import annotations

import json
import urllib.request
from typing import Optional, Tuple

from r36s_studio import APP_VERSION

_REPO = "nonotrichlozz/r36s-studio"
LATEST_RELEASE_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
# Boutique où sont vendus les installeurs (les Releases GitHub sont publiées
# sans fichiers, scripts/publish_release.sh) : seule destination du bouton
# de la fenêtre « Nouvelle version ».
# Page GitHub Pages (docs/site/index.html), qui redirigera vers la boutique.
STORE_URL = "https://nonotrichlozz.github.io/r36s-studio/"


def _version_tuple(version: str) -> Optional[Tuple[int, ...]]:
    try:
        return tuple(int(part) for part in version.strip().lstrip("vV").split("."))
    except ValueError:
        return None


def is_newer(tag: str, current: Optional[str] = None) -> bool:
    latest, mine = _version_tuple(tag), _version_tuple(current or APP_VERSION)
    return latest is not None and mine is not None and latest > mine


def fetch_latest(opener=urllib.request.urlopen, timeout: float = 5) -> Optional[Tuple[str, str]]:
    """`(tag_name, notes)` de la dernière Release, `None` sur toute erreur."""
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={"User-Agent": f"r36s-studio/{APP_VERSION}", "Accept": "application/vnd.github+json"},
    )
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data["tag_name"]), str(data.get("body") or "")
    except Exception:  # noqa: BLE001 -- silence total voulu (hors ligne, quota API, JSON inattendu)
        return None

