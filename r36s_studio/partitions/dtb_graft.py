# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Greffe des réglages d'écran d'un .dtb dans un autre (carte KNULLI R36S).

Cas réel (R36S noire d'origine, 2026-10-20) : KNULLI démarrait (musique)
mais l'écran restait noir ; remplacer tout `boot/rk3326-rg351mp-linux.dtb`
par le .dtb noyau d'usine (méthode de l'issue #64 de knulli-linux) empêchait
complètement le démarrage (plus de musique). Ce qui a marché : garder le
.dtb de KNULLI et n'y remplacer **que** les propriétés du nœud de l'écran
(`panel@…` sous le contrôleur DSI : `panel-init-sequence`, délais,
`display-timings/*`), par celles du .dtb d'usine. Les `phandle` ne sont
jamais copiés (ils désignent des nœuds du .dtb de KNULLI, `native-mode`
pointe dessus).

Seules les propriétés présentes **des deux côtés**, au même chemin relatif
au nœud de l'écran, sont remplacées : aucun nœud ni propriété n'est ajouté
ni supprimé, le reste du .dtb est recopié octet pour octet.

Format : Flattened Device Tree (spécification devicetree.org, v17), lu et
réécrit ici sans dépendance (pas de `dtc` sur les machines des
utilisateurs)."""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9
HEADER_SIZE = 40

# Propriété qui distingue le nœud d'un écran DSI des autres `panel@…`.
PANEL_MARKER = "panel-init-sequence"
# `native-mode` désigne un nœud par son phandle : celui du .dtb de KNULLI.
NEVER_COPIED = ("phandle", "linux,phandle", "native-mode")


class InvalidDtb(ValueError):
    """Le fichier n'est pas un .dtb lisible."""


def _align4(n: int) -> int:
    return (n + 3) & ~3


def _header(data: bytes) -> Tuple[int, ...]:
    if len(data) < HEADER_SIZE:
        raise InvalidDtb("fichier trop court")
    fields = struct.unpack(">10I", data[:HEADER_SIZE])
    magic, total, off_struct, off_strings, off_rsv, _ver, _lcv, _boot, size_strings, size_struct = fields
    if magic != FDT_MAGIC:
        raise InvalidDtb("signature absente")
    if total > len(data) or off_struct + size_struct > len(data) or off_strings + size_strings > len(data):
        raise InvalidDtb("tailles incohérentes")
    if not off_rsv <= off_struct <= off_strings:
        raise InvalidDtb("ordre des blocs inattendu")
    return fields


def _string(data: bytes, off_strings: int, size_strings: int, offset: int) -> str:
    start = off_strings + offset
    end = data.find(b"\0", start, off_strings + size_strings)
    if offset >= size_strings or end < 0:
        raise InvalidDtb("nom de propriété hors limites")
    return data[start:end].decode("ascii", errors="replace")


def _walk(data: bytes):
    """Parcourt le bloc de structure : (jeton, chemin, nom, valeur, début, fin)."""
    _magic, _total, off_struct, off_strings, _rsv, _v, _l, _b, size_strings, size_struct = _header(data)
    end_struct = off_struct + size_struct
    i = off_struct
    stack: List[str] = []
    while i + 4 <= end_struct:
        start = i
        token = struct.unpack(">I", data[i : i + 4])[0]
        i += 4
        if token == FDT_BEGIN_NODE:
            name_end = data.find(b"\0", i, end_struct)
            if name_end < 0:
                raise InvalidDtb("nom de nœud non terminé")
            stack.append(data[i:name_end].decode("ascii", errors="replace"))
            i = _align4(name_end + 1)
            yield token, "/".join(stack), None, None, start, i
        elif token == FDT_END_NODE:
            if not stack:
                raise InvalidDtb("fin de nœud sans début")
            stack.pop()
            yield token, "/".join(stack), None, None, start, i
        elif token == FDT_PROP:
            if i + 8 > end_struct:
                raise InvalidDtb("propriété tronquée")
            length, name_off = struct.unpack(">II", data[i : i + 8])
            value = data[i + 8 : i + 8 + length]
            if len(value) != length:
                raise InvalidDtb("valeur tronquée")
            i = _align4(i + 8 + length)
            name = _string(data, off_strings, size_strings, name_off)
            yield token, "/".join(stack), name, value, start, i
        elif token == FDT_NOP:
            yield token, "/".join(stack), None, None, start, i
        elif token == FDT_END:
            yield token, "/".join(stack), None, None, start, i
            return
        else:
            raise InvalidDtb(f"jeton inconnu {token}")
    raise InvalidDtb("fin de structure absente")


def properties(data: bytes) -> Dict[Tuple[str, str], bytes]:
    """{(chemin du nœud, nom): valeur} -- chemin sans le nœud racine vide."""
    return {(path, name): value for token, path, name, value, _s, _e in _walk(data) if token == FDT_PROP}


def panel_node(props: Dict[Tuple[str, str], bytes]) -> Optional[str]:
    """Chemin du nœud de l'écran (`…/panel@…` portant `panel-init-sequence`),
    `None` s'il n'y en a pas exactement un."""
    found = sorted({path for path, name in props if name == PANEL_MARKER and path.rsplit("/", 1)[-1].startswith("panel")})
    return found[0] if len(found) == 1 else None


def has_panel(data: bytes) -> bool:
    try:
        return panel_node(properties(data)) is not None
    except InvalidDtb:
        return False


def _panel_settings(props: Dict[Tuple[str, str], bytes], node: str) -> Dict[Tuple[str, str], bytes]:
    """Propriétés du nœud de l'écran et de ses sous-nœuds, chemin relatif."""
    result = {}
    for (path, name), value in props.items():
        if name in NEVER_COPIED:
            continue
        if path == node or path.startswith(node + "/"):
            result[(path[len(node) :], name)] = value
    return result


def graft_panel(base: bytes, donor: bytes) -> Optional[bytes]:
    """`base` (le .dtb de KNULLI) avec les réglages d'écran de `donor` (le
    .dtb d'usine). `None` si l'un des deux n'a pas de nœud d'écran
    reconnaissable ou n'est pas un .dtb lisible -- jamais de greffe à moitié."""
    try:
        base_props = properties(base)
        donor_props = properties(donor)
    except InvalidDtb:
        return None
    base_node, donor_node = panel_node(base_props), panel_node(donor_props)
    if base_node is None or donor_node is None:
        return None
    wanted = _panel_settings(donor_props, donor_node)

    fields = _header(base)
    magic, _total, off_struct, off_strings, off_rsv, version, last_comp, boot_cpu, size_strings, size_struct = fields
    out = bytearray()
    for token, path, name, value, start, end in _walk(base):
        if token != FDT_PROP:
            out += base[start:end]
            continue
        relative = None
        if path == base_node or path.startswith(base_node + "/"):
            relative = (path[len(base_node) :], name)
        if relative is not None and name not in NEVER_COPIED and relative in wanted:
            value = wanted[relative]
            name_off = struct.unpack(">I", base[start + 8 : start + 12])[0]
            out += struct.pack(">III", FDT_PROP, len(value), name_off) + value + b"\0" * (_align4(len(value)) - len(value))
        else:
            out += base[start:end]

    new_off_struct = off_struct
    new_off_strings = new_off_struct + len(out)
    strings = base[off_strings : off_strings + size_strings]
    total = new_off_strings + len(strings)
    header = struct.pack(
        ">10I", magic, total, new_off_struct, new_off_strings, off_rsv, version, last_comp, boot_cpu, len(strings), len(out)
    )
    return header + base[HEADER_SIZE:off_struct] + bytes(out) + strings


__all__ = ["InvalidDtb", "graft_panel", "has_panel", "panel_node", "properties"]
