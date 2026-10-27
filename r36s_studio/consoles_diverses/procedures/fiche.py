# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Lecture défensive du champ `procedures` d'une fiche
(`r36s-studio-catalogue/schema/console.schema.json`, `$defs/procedure`) et
plan d'exécution du moteur.

Le moteur ne connaît pas une console, il connaît des **actions** (code
`action` de chaque étape). Une procédure dont une action lui est inconnue
(ex. `selectionner_partitions` de la restauration Super) est affichée mais
désactivée, avec sa raison -- jamais exécutée à moitié."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional

# Ordre d'exécution des phases du moteur. Chaque action du catalogue tombe
# dans une phase ; plusieurs actions peuvent partager la même (le flash
# couvre « armer », « mode Download », « flasher » et « fin » : CmdDloader
# est lancé d'abord et attend lui-même la console, comme UpgradeDownload).
PHASES = (
    "prerequis",
    "telechargement",
    "pilotes",
    "extraction",
    "verification_pac",
    "consignes",
    "flash",
    "premier_demarrage",
)

ACTION_VERS_PHASE = {
    "telecharger": "telechargement",
    "installer_prerequis": "prerequis",
    "installer_pilotes": "pilotes",
    "extraire_archive": "extraction",
    "charger_pac": "verification_pac",
    "retirer_sd": "consignes",
    "preparer_console": "consignes",
    "armer_flash": "flash",
    "mode_download": "flash",
    "flasher": "flash",
    "fin_flash": "flash",
    "attendre_premier_demarrage": "premier_demarrage",
    "configuration_initiale": "premier_demarrage",
}

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VID_PID = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{4}$")


@dataclass
class Variante:
    id: str
    nom: str
    description: str
    recommande: bool = False
    fichiers: List[str] = field(default_factory=list)
    fichier_final: Optional[str] = None
    # Nom affiché dans l'en-tête du .pac (ex. RG_ROTATE_GAMMAOS_NEXT_LITE).
    pac_nom: Optional[str] = None


@dataclass
class Fichier:
    nom: str
    url: str
    sha256: Optional[str] = None
    variante: Optional[str] = None
    description: str = ""


@dataclass
class Etape:
    ordre: int
    action: str
    automatisable: str
    detail: str
    avertissement: Optional[str] = None


@dataclass
class Depannage:
    symptome: str
    solution: str


@dataclass
class Procedure:
    id: str
    titre: str
    firmware: str
    version: str
    mode: str
    efface_donnees: bool
    plateformes: List[str]
    telechargements: List[Fichier]
    etapes: List[Etape]
    source_url: str
    variantes: List[Variante] = field(default_factory=list)
    vid_pid: List[str] = field(default_factory=list)
    vid_pid_a_verifier: bool = True
    mot_de_passe_requis: bool = False
    mot_de_passe_source: str = ""
    depannage: List[Depannage] = field(default_factory=list)
    # Nom de produit de l'en-tête du .pac (ex. ums512_1h10) : vérifié
    # avant tout flash, avec la version et le `pac_nom` de la variante.
    pac_produit: Optional[str] = None

    def fichiers_pour(self, variante: Optional[str]) -> List[Fichier]:
        """Fichiers communs (sans `variante`) + ceux de la variante choisie."""
        return [f for f in self.telechargements if f.variante in (None, variante)]

    def variante(self, variante_id: Optional[str]) -> Optional[Variante]:
        return next((v for v in self.variantes if v.id == variante_id), None)

    def phases(self) -> List[str]:
        """Phases du moteur à parcourir, dans l'ordre de `PHASES`. Un flash
        impose toujours les outils (téléchargement), les pilotes et la
        vérification du .pac, même si la fiche ne les liste pas."""
        voulues = {ACTION_VERS_PHASE[e.action] for e in self.etapes if e.action in ACTION_VERS_PHASE}
        if "flash" in voulues:
            voulues |= {"telechargement", "pilotes", "verification_pac"}
        return [p for p in PHASES if p in voulues]

    def etapes_de(self, phase: str) -> List[Etape]:
        return [e for e in self.etapes if ACTION_VERS_PHASE.get(e.action) == phase]


def motif_desactivation(procedure: Procedure, systeme: str) -> Optional[str]:
    """Code de la raison pour laquelle la procédure ne peut pas être lancée
    ici (`strings.py`, `procedure_desactivee_<code>`), ou `None`.
    `systeme` : `windows`/`macos`/`linux`."""
    if procedure.mode != "usb_download":
        return "mode"
    if any(e.action not in ACTION_VERS_PHASE for e in procedure.etapes):
        return "etape"
    if "flash" not in procedure.phases():
        return "etape"
    if systeme not in procedure.plateformes:
        return "systeme"
    if not procedure.pac_produit:
        return "pac"
    return None


def fichiers_a_telecharger(procedure: Procedure, variante: Optional[str]) -> List[Fichier]:
    """Fichiers que le moteur télécharge lui-même : https depuis GitHub,
    avec une SHA-256 publiée. Les autres (Google Drive...) sont demandés à
    l'utilisateur."""
    return [f for f in procedure.fichiers_pour(variante) if est_telechargeable(f)]


def est_telechargeable(fichier: Fichier) -> bool:
    return fichier.url.startswith("https://github.com/") and fichier.sha256 is not None


NOMS_SYSTEMES = {"windows": "Windows", "macos": "macOS", "linux": "Linux"}


def systeme_courant() -> str:
    """`windows`/`macos`/`linux`, comme `plateformes` dans la fiche."""
    if sys.platform == "win32":
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def auteur_depuis_url(url: str) -> Optional[str]:
    """Propriétaire d'un dépôt GitHub (`https://github.com/<auteur>/…`),
    pour créditer l'auteur du système ; `None` ailleurs."""
    m = re.match(r"^https://github\.com/([A-Za-z0-9-]{1,39})/", url)
    return m.group(1) if m else None


def premiere_url(texte: str) -> Optional[str]:
    """Premier lien https d'un texte de la fiche (ex. Discord/Patreon dans
    `mot_de_passe_archive.source`), sans ponctuation finale."""
    m = re.search(r"https://[^\s()<>\"']+", texte)
    return m.group(0).rstrip(".,;:") if m else None


def version_a_verifier(procedure: Procedure) -> Optional[str]:
    """Version comparée à l'en-tête du .pac -- seulement si c'est un vrai
    numéro (« 1.4.1 »), pas un libellé (« origine »)."""
    return procedure.version if any(c.isdigit() for c in procedure.version) else None


def _texte(valeur: Any, defaut: str = "") -> str:
    return valeur if isinstance(valeur, str) else defaut


def _liste(valeur: Any) -> list:
    return valeur if isinstance(valeur, list) else []


def _variante(data: Any) -> Optional[Variante]:
    if not isinstance(data, dict) or not _texte(data.get("id")) or not _texte(data.get("nom")):
        return None
    return Variante(
        id=data["id"],
        nom=data["nom"],
        description=_texte(data.get("description")),
        recommande=data.get("recommande") is True,
        fichiers=[f for f in _liste(data.get("fichiers")) if isinstance(f, str)],
        fichier_final=_nom_de_fichier(data.get("fichier_final")),
        pac_nom=_texte(data.get("pac_nom")) or None,
    )


def _nom_de_fichier(valeur: Any) -> Optional[str]:
    """Nom simple seulement : jamais un chemin (la fiche vient du réseau)."""
    if not isinstance(valeur, str) or not valeur or valeur in (".", ".."):
        return None
    if "/" in valeur or "\\" in valeur or ":" in valeur:
        return None
    return valeur


def _fichier(data: Any) -> Optional[Fichier]:
    if not isinstance(data, dict):
        return None
    nom, url = _texte(data.get("nom")), _texte(data.get("url"))
    if not nom or not url.startswith("https://"):
        return None
    sha = _texte(data.get("sha256")).lower()
    return Fichier(
        nom=nom,
        url=url,
        sha256=sha if _SHA256.match(sha) else None,
        variante=_texte(data.get("variante")) or None,
        description=_texte(data.get("description")),
    )


def _etape(data: Any) -> Optional[Etape]:
    if not isinstance(data, dict) or not _texte(data.get("action")):
        return None
    ordre = data.get("ordre")
    return Etape(
        ordre=ordre if isinstance(ordre, int) and not isinstance(ordre, bool) else 0,
        action=data["action"],
        automatisable=_texte(data.get("automatisable"), "non"),
        detail=_texte(data.get("detail")),
        avertissement=_texte(data.get("avertissement")) or None,
    )


def procedure_depuis_json(data: Any) -> Optional[Procedure]:
    """`None` pour une entrée inexploitable (champ obligatoire absent ou
    du mauvais type) : elle n'est simplement pas proposée."""
    if not isinstance(data, dict):
        return None
    for champ in ("id", "titre", "mode", "source_url"):
        if not _texte(data.get(champ)):
            return None
    if not isinstance(data.get("efface_donnees"), bool):
        return None
    etapes = [e for e in (_etape(x) for x in _liste(data.get("etapes"))) if e is not None]
    if not etapes:
        return None
    detection = data.get("detection") if isinstance(data.get("detection"), dict) else {}
    mot_de_passe = data.get("mot_de_passe_archive") if isinstance(data.get("mot_de_passe_archive"), dict) else {}
    depannage = [
        Depannage(symptome=d["symptome"], solution=d["solution"])
        for d in _liste(data.get("depannage"))
        if isinstance(d, dict) and _texte(d.get("symptome")) and _texte(d.get("solution"))
    ]
    return Procedure(
        id=data["id"],
        titre=data["titre"],
        firmware=_texte(data.get("firmware")),
        version=_texte(data.get("version")),
        mode=data["mode"],
        efface_donnees=data["efface_donnees"],
        plateformes=[p for p in _liste(data.get("plateformes")) if isinstance(p, str)],
        telechargements=[f for f in (_fichier(x) for x in _liste(data.get("telechargements"))) if f is not None],
        etapes=sorted(etapes, key=lambda e: e.ordre),
        source_url=data["source_url"],
        variantes=[v for v in (_variante(x) for x in _liste(data.get("variantes"))) if v is not None],
        vid_pid=[v.lower() for v in _liste(detection.get("usb_vid_pid")) if isinstance(v, str) and _VID_PID.match(v.lower())],
        vid_pid_a_verifier=detection.get("a_verifier") is not False,
        mot_de_passe_requis=mot_de_passe.get("requis") is True,
        mot_de_passe_source=_texte(mot_de_passe.get("source")),
        depannage=depannage,
        pac_produit=_texte(data.get("pac_produit")) or None,
    )


def procedures_depuis_json(data: Any) -> List[Procedure]:
    return [p for p in (procedure_depuis_json(x) for x in _liste(data)) if p is not None]


__all__ = [
    "PHASES",
    "ACTION_VERS_PHASE",
    "Variante",
    "Fichier",
    "Etape",
    "Depannage",
    "Procedure",
    "motif_desactivation",
    "fichiers_a_telecharger",
    "est_telechargeable",
    "NOMS_SYSTEMES",
    "systeme_courant",
    "auteur_depuis_url",
    "premiere_url",
    "version_a_verifier",
    "procedure_depuis_json",
    "procedures_depuis_json",
]
