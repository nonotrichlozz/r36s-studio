# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Famille de la console (R36S d'origine, clone, « soysauce ») d'après sa
chaîne matérielle. Source : `dtb/r36_devices.ini` de l'image dArkOSRE
(southoz/dArkOSRE-R36, relevé sur `dArkOSRE_R36_trixie_03082026.img`),
recopié tel quel.

La chaîne est la ligne `Hardware:` de /proc/cpuinfo, que le noyau Rockchip
4.4 remplit avec la propriété `model` racine du `.dtb` démarré (vérifié :
chaque `.dtb` de dArkOSRE porte comme `model` le nom de sa section). Les
suffixes « Variant N », « Panel N A », « 2550 »... sont ceux de dArkOSRE :
le `model` des `.dtb` R36S-V21 vaut `R36S-V21 2024-12-18`, d'où la
correspondance par préfixe.

Ajouts hors dArkOSRE (marqués dans la table) : modèles du sélecteur de
dArkOSen `dArkOSen_R36_10152026` (2026-10-14), firmware réservé aux
consoles d'origine, d'où la famille R36S.

Non vérifié : qu'un `.dtb` de carte d'usine porte bien ces chaînes
(aucun disponible au moment de l'écriture)."""

from __future__ import annotations

from typing import Optional, Set

R36S = "r36s"
CLONE = "clone"
SOYSAUCE = "soysauce"

# (chaîne matérielle, famille), ordre et casse de r36_devices.ini.
HARDWARE_TABLE = (
    ("HL-R36H-V20 2024-05-18", R36S),
    ("R36S-V12 2023-08-18 Panel 0", R36S),
    ("R36S-V12 2023-08-18 Panel 4", R36S),
    ("R36S-V21 2024-12-18 2550", R36S),
    ("R36S-V21 2024-12-18 2552", R36S),
    ("R36S-V22 2024-12-18", R36S),
    ("R36S-Y02 2024-12-18", R36S),
    ("R36XX-V21 2024-12-18", R36S),
    # Sélecteur de dArkOSen 10152026, absents de r36_devices.ini.
    ("R36S-V21 2024-12-18 2537", R36S),
    ("HL-R50S-V30 2025-12-18", R36S),
    ("G80C-MB V1.1-20250319 Panel 8", CLONE),
    ("G80C-MB V1.1-20250319 Panel 9", CLONE),
    ("G80CA-MB V1.2-20250422 Panel 8", CLONE),
    ("G80CA-MB V1.2-20250422 Panel 9", CLONE),
    ("G80CA-MB V1.2-20250423 Panel 8", CLONE),
    ("G80CA-MB V1.2-20250423 Panel 9", CLONE),
    ("G80CA-MB V1.3-20251212 Panel 8", CLONE),
    ("R36S-V12 2023-08-18 Variant 1 Panel 3 A", CLONE),
    ("R36S-V12 2023-08-18 Variant 1 Panel 8 A", CLONE),
    ("R36S-V12 2023-08-18 Variant 2 Panel 1", CLONE),
    ("R36S-V12 2023-08-18 Variant 2 Panel 1 A", CLONE),
    ("R36S-V12 2023-08-18 Variant 3 Panel A", CLONE),
    ("R36S-V12 2023-08-18 Variant 3 Panel 3", CLONE),
    ("Y3506_V03_20241104", SOYSAUCE),
    ("Y3506_v03_20241210", SOYSAUCE),
    ("Y3506_V03_20250317", SOYSAUCE),
    ("Y3506_V04_20250529 2548", SOYSAUCE),
    ("Y3506_V04_20250529 2533", SOYSAUCE),
    ("Y3506_V05_20251215 2551", SOYSAUCE),
    ("Y3506_V05_20251215 2601", SOYSAUCE),
)


def _norm(text: str) -> str:
    return " ".join(text.upper().split())


def families_for_hardware(text: Optional[str]) -> Set[str]:
    """Familles des entrées qui correspondent (égalité, ou l'une préfixe de
    l'autre à un mot près). Plusieurs : référence ambiguë -- ex.
    `R36S-V12 2023-08-18` seul, présent chez les R36S et chez les clones."""
    wanted = _norm(text or "")
    if not wanted:
        return set()
    return {
        family
        for name, family in HARDWARE_TABLE
        if (entry := _norm(name)) == wanted or entry.startswith(wanted + " ") or wanted.startswith(entry + " ")
    }


def family_for_hardware(text: Optional[str]) -> Optional[str]:
    """Famille si toutes les entrées qui correspondent s'accordent ; `None`
    sinon (aucune, ou référence ambiguë)."""
    families = families_for_hardware(text)
    return families.pop() if len(families) == 1 else None
