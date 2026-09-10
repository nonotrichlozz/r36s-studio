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

"""Squelette GUI PySide6 (phase 4), branché sur les phases 1–3 : `devices`,
`safety`, `imaging` (backup/flash). Un processus séparé (`gui/elevate.py`,
même binaire relancé avec `--worker`) fait l'écriture disque avec les
privilèges administrateur — la GUI elle-même ne tourne jamais élevée (§3).

`inject_boot`, `copy_games` et le mode assisté (phases 5–6) ne sont pas
implémentés ici : leurs tuiles apparaissent grisées sur l'écran d'accueil
plutôt que simulées."""
