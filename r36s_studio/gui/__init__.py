"""Squelette GUI PySide6 (phase 4), branché sur les phases 1–3 : `devices`,
`safety`, `imaging` (backup/flash). Un processus séparé (`gui/elevate.py`,
même binaire relancé avec `--worker`) fait l'écriture disque avec les
privilèges administrateur — la GUI elle-même ne tourne jamais élevée (§3).

`inject_boot`, `copy_games` et le mode assisté (phases 5–6) ne sont pas
implémentés ici : leurs tuiles apparaissent grisées sur l'écran d'accueil
plutôt que simulées."""
