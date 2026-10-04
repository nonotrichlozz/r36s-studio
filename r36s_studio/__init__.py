# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""R36S Studio — préparation de cartes SD pour la console R36S.

Phase 1 : détection des périphériques (`devices`) et garde-fou de sécurité
(`safety`) uniquement. Pas d'écriture disque, pas d'interface graphique.
"""

# Source de vérité unique : --version, vérification des mises à jour
# (update_check.py) et tag de release (vX.Y.Z, contrôlé par release.yml).
APP_VERSION = "0.1.1"
__version__ = APP_VERSION
