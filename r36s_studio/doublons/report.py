# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Rapport texte brut (docs/doublons.md §Interface point 5, « Export du
rapport en texte avant action ») -- formatage local plutôt qu'un import
de `gui/screens.py::_format_size` : ce package reste sans dépendance
vers `gui/` (§ architecture, autonome). Base 1024, même convention que
le reste du projet (§5 vocabulaire du brief principal)."""

from __future__ import annotations

from typing import List

from .scan import ScanResult

__all__ = ["build_report"]


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if value < 1024 or unit == "To":
            return f"{int(value)} {unit}" if unit == "o" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} o"


def build_report(scan_result: ScanResult, root: str) -> str:
    lines: List[str] = [
        f"Rapport d'analyse des doublons -- {root}",
        f"Fichiers analysés : {scan_result.files_scanned}",
        f"Groupes de copies identiques : {len(scan_result.exact_duplicate_groups)}",
        f"Groupes de versions différentes : {len(scan_result.version_groups)}",
    ]
    if scan_result.excluded:
        lines.append(f"Groupes exclus (fichier lié introuvable) : {len(scan_result.excluded)}")

    lines.append("")
    lines.append("=== Copies identiques ===")
    for group in scan_result.exact_duplicate_groups:
        lines.append("")
        for unit in group.units:
            lines.append(f"  - {unit.representative} ({_format_size(unit.total_size_bytes)})")

    lines.append("")
    lines.append("=== Versions différentes ===")
    for group in scan_result.version_groups:
        title = f"{group.system_folder} — {group.normalized_title}" if group.system_folder else group.normalized_title
        lines.append("")
        lines.append(title)
        for unit in group.units:
            marker = " (suggérée)" if unit is group.suggested_keep else ""
            lines.append(f"  - {unit.representative} ({_format_size(unit.total_size_bytes)}){marker}")

    if scan_result.excluded:
        lines.append("")
        lines.append("=== Groupes exclus (fichier lié introuvable) ===")
        for warning in scan_result.excluded:
            lines.append(f"  - {warning.manifest} : {', '.join(warning.missing)}")

    return "\n".join(lines)
