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

"""Point d'entrée du binaire empaqueté par PyInstaller (§6/§7).

Un seul et même exécutable sert à deux usages :

- lancé sans argument (double-clic depuis le Finder) : `main()` retombe sur
  la sous-commande `gui` (voir `r36s_studio/__main__.py`) et affiche
  l'assistant graphique ;
- relancé avec des arguments (`backup --device ... --worker ...`) : c'est
  ainsi que `gui/elevate.py` élève le worker une fois l'app packagée
  (`sys.frozen` vaut alors `True`, et `sys.executable` pointe vers CE
  binaire — voir `_worker_command`) ; `main()` dispatche alors vers
  `cmd_backup`/`cmd_flash`/etc. comme en ligne de commande normale.

Volontairement un fichier à part, plutôt que de pointer PyInstaller
directement sur `r36s_studio/__main__.py` : nommer le script d'entrée
`__main__.py` entrerait en conflit avec le module `__main__` que Python
crée déjà à l'exécution, un piège classique de PyInstaller."""

from r36s_studio.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
