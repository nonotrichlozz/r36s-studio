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

Console branchée sans le bon bouton (constaté le 2026-10-27, journaux
`SPRD_Download_Tool/Log/<date>/` d'UpgradeDownload) : elle apparaît en
« SPRD U2S Diag » mais ne répond pas au CHECK_BAUD
(`[SW2276]Check baud time out`), puis est lâchée après ~4 s. Que
CmdDloader l'affiche sur sa sortie n'est pas vérifié : les journaux qu'il
laisse dans `Log/` sont relus après un échec (`bouton_dans_journaux`).
"""

from __future__ import annotations

import re
import zipfile
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
_BOUTON = re.compile(r"SW2276|Check baud time ?out", re.I)


@dataclass
class Evenement:
    type: str  # chargement, paquet, attente, port, fichier, progression, resultat, delai, bouton
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
    if _BOUTON.search(ligne):
        return Evenement("bouton", None, ligne.strip())
    return None


def bouton_dans_journaux(dossier_log: Path, depuis: float) -> bool:
    """Vrai si un journal des outils SPRD écrit depuis `depuis` (horodatage
    `time.time()`) contient le refus du CHECK_BAUD -- `.log` en clair ou
    `Trace.log` dans les `.zip` d'un échec."""
    try:
        fichiers = [f for f in dossier_log.rglob("*") if f.is_file() and f.stat().st_mtime >= depuis]
    except OSError:
        return False
    for fichier in fichiers:
        try:
            if fichier.suffix.lower() == ".zip":
                with zipfile.ZipFile(fichier) as archive:
                    contenus = [archive.read(n) for n in archive.namelist() if n.lower().endswith(".log")]
            elif fichier.suffix.lower() == ".log":
                contenus = [fichier.read_bytes()]
            else:
                continue
        except (OSError, zipfile.BadZipFile):
            continue
        if any(_BOUTON.search(c.decode("utf-8", "replace")) for c in contenus):
            return True
    return False


__all__ = ["Evenement", "commande", "analyser_ligne", "bouton_dans_journaux", "DELAI_PAR_DEFAUT_MS"]
