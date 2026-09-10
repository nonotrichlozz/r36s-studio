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

"""Parseur pur Python du format DTB (Flattened Device Tree), sans
dépendance externe -- juste assez pour extraire de quoi identifier une
console R36S/R35S à partir du `.dtb` de son BOOT d'origine : le
`compatible` racine (identifiant de carte, ex. `rk3326-evb-lp3-v12`), le
`compatible` du nœud panel (contrôleur d'écran, ex. `sitronix,st7703`) et
les propriétés de timing d'affichage.

Format binaire (spec Devicetree, structure `fdt_header` + bloc structure +
bloc chaînes) : toutes les valeurs numériques du bloc structure sont des
entiers non signés 32 bits big-endian. Ne lève jamais autre chose que
`InvalidDtbError` sur un fichier tronqué ou invalide -- appelé sur des
fichiers arbitraires trouvés dans une archive BOOT, jamais garantis
valides."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union

FDT_MAGIC = 0xD00DFEED

_FDT_BEGIN_NODE = 0x00000001
_FDT_END_NODE = 0x00000002
_FDT_PROP = 0x00000003
_FDT_NOP = 0x00000004
_FDT_END = 0x00000009

# Propriétés de timing demandées (§ identification écran) -- entiers
# big-endian 32 bits, collectées n'importe où dans le sous-arbre du nœud
# panel (directement dessus, ou dans un sous-nœud `display-timings`/
# `timing0`, selon le DTS d'origine).
_TIMING_PROPERTIES = (
    "hactive",
    "vactive",
    "clock-frequency",
    "hfront-porch",
    "hback-porch",
    "hsync-len",
    "vfront-porch",
    "vback-porch",
    "vsync-len",
    "dsi,lanes",
)


class InvalidDtbError(ValueError):
    """Fichier absent de magic FDT_MAGIC, tronqué, ou structurellement
    invalide -- jamais une exception bas niveau (`struct.error`,
    `IndexError`...) ne doit s'en échapper : ce module lit des fichiers
    arbitraires trouvés sur une carte SD, pas des DTB de confiance."""


@dataclass
class DtbInfo:
    board_compatible: Optional[str]
    panel_compatible: Optional[str]
    timings: Dict[str, int] = field(default_factory=dict)


def _read_u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise InvalidDtbError("Fichier DTB tronqué (lecture hors limites).")
    return struct.unpack_from(">I", data, offset)[0]


def _align4(offset: int) -> int:
    return (offset + 3) & ~3


def _read_cstring(data: bytes, offset: int) -> str:
    if offset < 0 or offset > len(data):
        raise InvalidDtbError("Chaîne DTB hors limites.")
    end = data.find(b"\x00", offset)
    if end == -1:
        raise InvalidDtbError("Chaîne DTB non terminée par un octet nul.")
    return data[offset:end].decode("utf-8", errors="replace")


def parse_dtb(data: bytes) -> DtbInfo:
    """Lève `InvalidDtbError` pour tout fichier qui n'est pas un DTB
    valide -- jamais une autre exception."""
    if len(data) < 40:
        raise InvalidDtbError("Fichier trop court pour être un DTB (en-tête incomplet).")

    magic = _read_u32(data, 0)
    if magic != FDT_MAGIC:
        raise InvalidDtbError(f"Magic DTB invalide : 0x{magic:08x} (attendu 0x{FDT_MAGIC:08x}).")

    off_dt_struct = _read_u32(data, 8)
    off_dt_strings = _read_u32(data, 12)

    board_compatible: Optional[str] = None
    panel_compatible: Optional[str] = None
    timings: Dict[str, int] = {}

    node_stack: list[str] = []
    panel_depth: Optional[int] = None  # profondeur du nœud panel, tant qu'on y est encore

    offset = off_dt_struct
    while True:
        token = _read_u32(data, offset)
        offset += 4

        if token == _FDT_BEGIN_NODE:
            name = _read_cstring(data, offset)
            offset = _align4(offset + len(name.encode("utf-8")) + 1)
            node_stack.append(name)
            if panel_depth is None and "panel" in name.lower():
                panel_depth = len(node_stack)

        elif token == _FDT_END_NODE:
            if not node_stack:
                raise InvalidDtbError("FDT_END_NODE sans nœud ouvert correspondant.")
            if panel_depth is not None and len(node_stack) == panel_depth:
                panel_depth = None
            node_stack.pop()

        elif token == _FDT_PROP:
            prop_len = _read_u32(data, offset)
            nameoff = _read_u32(data, offset + 4)
            offset += 8
            value = data[offset : offset + prop_len]
            if len(value) != prop_len:
                raise InvalidDtbError("Propriété DTB tronquée.")
            offset = _align4(offset + prop_len)
            prop_name = _read_cstring(data, off_dt_strings + nameoff)

            at_root = len(node_stack) == 1 and node_stack[0] == ""
            in_panel_subtree = panel_depth is not None
            at_panel_node = panel_depth is not None and len(node_stack) == panel_depth

            if prop_name == "compatible":
                first_value = value.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
                if at_root and board_compatible is None:
                    board_compatible = first_value
                if at_panel_node and panel_compatible is None:
                    panel_compatible = first_value
            elif in_panel_subtree and prop_name in _TIMING_PROPERTIES and prop_name not in timings:
                if len(value) == 4:
                    timings[prop_name] = struct.unpack(">I", value)[0]

        elif token == _FDT_NOP:
            continue

        elif token == _FDT_END:
            break

        else:
            raise InvalidDtbError(f"Jeton DTB inconnu : 0x{token:08x}.")

    return DtbInfo(board_compatible, panel_compatible, timings)


def parse_dtb_file(path: Union[str, Path]) -> DtbInfo:
    with open(path, "rb") as handle:
        data = handle.read()
    return parse_dtb(data)
