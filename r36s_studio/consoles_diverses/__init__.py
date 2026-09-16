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

"""Section « Consoles diverses » (étape 1 : mode recherche) -- voir
`consoles_diverses/CLAUDE.md` pour le contrat HTTP et les décisions
d'isolation. Package volontairement indépendant du reste de R36S Studio :
un simple appel HTTP en lecture (`POST /recherche` vers `r36s-studio-cloud`)
et son affichage, sans aucun rapport avec le pipeline flash/backup/worker
élevé (§3 de CLAUDE.md à la racine)."""

from __future__ import annotations
