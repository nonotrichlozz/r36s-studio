# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Appareils USB branchés (Windows) et reconnaissance de la console :
mode Download Unisoc, ou console démarrée normalement sous Android.

Liste par `Get-CimInstance Win32_PnPEntity` (PowerShell, JSON) plutôt que
`pnputil` : les noms de champs ne dépendent pas de la langue de Windows.

Constaté (2026-10-27, PC Windows 10 d'Arnaud) : en mode Download, la console
apparaît comme `SPRD U2S Diag (COMn)`, `USB\\VID_1782&PID_4D00`, pilote
`sprdvcom.sys` -- console exacte (RG Rotate ou RG Vita) à confirmer. Le
VID:PID sous Android reste inconnu : **tout** nouvel appareil est journalisé
(`nouveaux`) pour compléter la fiche."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

_ID = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.I)
_NOMS_DOWNLOAD = ("sprd u2s diag", "unisoc", "spreadtrum")
_NOMS_ANDROID = ("adb", "android", "mtp", "composite adb")
_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)

COMMANDE = [
    "powershell", "-NoProfile", "-NonInteractive", "-Command",
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
    "Get-CimInstance Win32_PnPEntity -Filter \"PNPDeviceID LIKE 'USB%'\" | "
    "Select-Object PNPDeviceID,Name | ConvertTo-Json -Compress",
]


@dataclass(frozen=True)
class Appareil:
    identifiant: str  # PNPDeviceID complet
    nom: str

    @property
    def vid_pid(self) -> Optional[str]:
        m = _ID.search(self.identifiant)
        return f"{m.group(1)}:{m.group(2)}".lower() if m else None


def analyser(sortie: str) -> List[Appareil]:
    """JSON de `COMMANDE` -> appareils. Un seul appareil donne un objet,
    plusieurs une liste ; rien ou une sortie illisible donne `[]`."""
    try:
        donnees = json.loads(sortie or "[]")
    except ValueError:
        return []
    if isinstance(donnees, dict):
        donnees = [donnees]
    if not isinstance(donnees, list):
        return []
    return [
        Appareil(str(d.get("PNPDeviceID") or ""), str(d.get("Name") or ""))
        for d in donnees
        if isinstance(d, dict) and d.get("PNPDeviceID")
    ]


def lister(timeout: float = 20.0) -> List[Appareil]:
    try:
        sortie = subprocess.run(
            COMMANDE, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=_SANS_FENETRE,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return analyser(sortie)


def classer(appareil: Appareil, vid_pids: Iterable[str]) -> Optional[str]:
    """`"download"`, `"android"` ou `None`."""
    nom = appareil.nom.lower()
    if appareil.vid_pid in {v.lower() for v in vid_pids} or any(n in nom for n in _NOMS_DOWNLOAD):
        return "download"
    if any(n in nom for n in _NOMS_ANDROID):
        return "android"
    return None


def nouveaux(avant: Iterable[Appareil], apres: Iterable[Appareil]) -> List[Appareil]:
    connus = {a.identifiant for a in avant}
    return [a for a in apres if a.identifiant not in connus]


def etat(appareils: Iterable[Appareil], vid_pids: Iterable[str]) -> Dict[str, List[Appareil]]:
    resultat: Dict[str, List[Appareil]] = {"download": [], "android": []}
    for appareil in appareils:
        genre = classer(appareil, vid_pids)
        if genre:
            resultat[genre].append(appareil)
    return resultat


__all__ = ["Appareil", "COMMANDE", "analyser", "lister", "classer", "nouveaux", "etat"]
