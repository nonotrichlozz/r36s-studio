# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Flash par `CmdDloader.exe` (outil en ligne de commande des outils SPRD,
`SPRD_Download_Tool/`, version 27.24.2301).

Syntaxe relevée dans le programme lui-même (texte d'aide intégré,
2026-10-27 ; jamais encore lancé sur une console) :

    CmdDloader.exe -pac <fichier.pac> -Version 2 -Port 0 -Timeout <ms> -Reset

- `-Version` : 0 ResearchDownload (défaut), 1 FactoryDownload,
  2 UpgradeDownload -- 2 = même mode que l'outil graphique de la procédure
  officielle (réglages `Setting/UpgradeDownload.ini`).
- `-Port 0` : premier appareil en mode Download trouvé (défaut).
- `-Timeout` : délai en ms entre le lancement et le début du flash
  (60 000 par défaut) -- il couvre aussi le chargement du .pac (~2 min pour
  6,7 Go), d'où une valeur large.
- `-Reset` : redémarre la console à la fin (`-PowerOff` l'éteindrait ;
  les deux ensemble sont refusés).
- Autres options connues, non utilisées : `-Policy`, `-Baudrate`,
  `-SkipFileID`, `-SendFlag`, `-WriteSN1/2`, `-ReadNV`, `-WriteEfuse`,
  `-WriteTimeStamp`, `-EZMode`, `-DDDP`, `-Help`.

Lignes affichées (formats `printf` relevés dans le programme) :

    Loading packet progress is  42%
    PACKET: <nom>; Version: <v>; Packet Size: <x>MB; LoadTime = ...
    Please connect the DUT in  57s
    PORT = COM4
    No.001 FDL                        Progress:  50%; Size: ...
    [Status] 37%
    Download Result = Passed;
    Download Result = Failed; Error Messag = <message>
    Connect DUT timeout( 60s )
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

DELAI_PAR_DEFAUT_MS = 15 * 60 * 1000

_CHARGEMENT = re.compile(r"Loading packet progress is\s*(\d+)%", re.I)
_PAQUET = re.compile(r"PACKET:\s*([^;]+);\s*Version:\s*([^;]+);", re.I)
_ATTENTE = re.compile(r"Please connect the DUT in\s*(\d+)\s*s", re.I)
_PORT = re.compile(r"PORT\s*=\s*COM(\d+)", re.I)
_FICHIER = re.compile(r"No\.\s*\d+\s+(\S+)\s+Progress:\s*(\d+)%", re.I)
_STATUT = re.compile(r"\[Status\]\s*(\d+)%", re.I)
_RESULTAT = re.compile(r"Download Result\s*=\s*(Passed|Failed)\s*;?\s*(?:Error Messag\w*\s*=\s*(.*))?", re.I)
_DELAI = re.compile(r"Connect DUT timeout|Download timeout", re.I)


@dataclass
class Evenement:
    type: str  # chargement, paquet, attente, port, fichier, progression, resultat, delai
    valeur: object = None
    texte: str = ""


def commande(exe: Path, pac: Path, delai_ms: int = DELAI_PAR_DEFAUT_MS) -> List[str]:
    return [str(exe), "-pac", str(pac), "-Version", "2", "-Port", "0", "-Timeout", str(int(delai_ms)), "-Reset"]


def analyser_ligne(ligne: str) -> Optional[Evenement]:
    if (m := _RESULTAT.search(ligne)) is not None:
        reussi = m.group(1).lower() == "passed"
        return Evenement("resultat", reussi, (m.group(2) or "").strip())
    if (m := _CHARGEMENT.search(ligne)) is not None:
        return Evenement("chargement", int(m.group(1)))
    if (m := _PAQUET.search(ligne)) is not None:
        return Evenement("paquet", (m.group(1).strip(), m.group(2).strip()))
    if (m := _ATTENTE.search(ligne)) is not None:
        return Evenement("attente", int(m.group(1)))
    if (m := _PORT.search(ligne)) is not None:
        return Evenement("port", int(m.group(1)))
    if (m := _STATUT.search(ligne)) is not None:
        return Evenement("progression", int(m.group(1)))
    if (m := _FICHIER.search(ligne)) is not None:
        return Evenement("fichier", int(m.group(2)), m.group(1))
    if _DELAI.search(ligne):
        return Evenement("delai", None, ligne.strip())
    return None


__all__ = ["Evenement", "commande", "analyser_ligne", "DELAI_PAR_DEFAUT_MS"]
