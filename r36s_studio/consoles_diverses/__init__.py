# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Section « Consoles diverses » (étape 1 : mode recherche) -- voir
`consoles_diverses/CLAUDE.md` pour le contrat HTTP et les décisions
d'isolation. Package volontairement indépendant du reste de R36S Studio :
un simple appel HTTP en lecture (`POST /recherche` vers `r36s-studio-cloud`)
et son affichage, sans aucun rapport avec le pipeline flash/backup/worker
élevé (§3 de CLAUDE.md à la racine)."""

from __future__ import annotations
