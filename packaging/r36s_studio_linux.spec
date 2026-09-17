# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour la construction Linux (§6/§7, phase 7).

Comme sous Windows (`r36s_studio_windows.spec`), l'élévation Linux
(`pkexec`, repli `sudo`, voir `gui/elevate.py`) relance directement le
binaire lui-même (`sys.executable`) sans identité de paquet particulière
à obtenir au préalable -- un simple exécutable onedir suffit.

Construction (locale ou CI, voir packaging/build_linux.sh et le workflow
`.github/workflows/build.yml`) :

    packaging/build_linux.sh

Résultat : `dist/R36S Studio/R36S Studio` (+ ses dépendances à côté).
Distribué en `.tar.gz` (§7) -- un vrai AppImage (§6 du brief) reste une
amélioration future, pas implémentée ici : elle demanderait au minimum une
icône dédiée et un fichier `.desktop`, ni l'un ni l'autre n'existant
encore dans ce dépôt (§5 : `icon=None` côté macOS/Windows aussi, pas
d'icône pour l'instant)."""

import sys
from datetime import datetime
from pathlib import Path

block_cipher = None

PACKAGING_DIR = Path(SPECPATH)
PROJECT_ROOT = PACKAGING_DIR.parent
ENTRY_SCRIPT = str(PACKAGING_DIR / "entry.py")

sys.path.insert(0, str(PROJECT_ROOT))

APP_NAME = "R36S Studio"

BUILD_TIMESTAMP_FILE = PROJECT_ROOT / "build" / "build_timestamp.txt"
BUILD_TIMESTAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
BUILD_TIMESTAMP_FILE.write_text(datetime.now().strftime("%d/%m/%Y à %H:%M"), encoding="utf-8")

ASSETS_DIR = PROJECT_ROOT / "r36s_studio" / "gui" / "assets"
EXTRA_DATAS = [
    (str(ASSETS_DIR / name), "assets")
    for name in ("console.png", "circuit.png")
    if (ASSETS_DIR / name).exists()
]

# `keyring` (consoles_diverses/settings_store.py) choisit son backend par
# introspection au moment de l'exécution -- PyInstaller ne le détecte pas
# automatiquement, il faut le déclarer explicitement (voir CLAUDE.md
# racine, § durcissement consoles_diverses, point 5). Linux n'a pas de
# backend natif unique : `SecretService`/`libsecret` (GNOME) et `kwallet`
# (KDE) sont les deux backends de bureau possibles, `chainer`/`fail` les
# deux repli génériques -- sans trousseau de bureau actif (headless,
# certains environnements minimalistes), `keyring` retombe sur `fail`, ce
# que `settings_store.trousseau_disponible()` détecte alors comme
# indisponible (repli mémoire-session, jamais d'écriture en clair).
KEYRING_HIDDEN_IMPORTS = [
    "keyring.backends.SecretService",
    "keyring.backends.libsecret",
    "keyring.backends.kwallet",
    "keyring.backends.chainer",
    "keyring.backends.fail",
]

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[(str(BUILD_TIMESTAMP_FILE), ".")] + EXTRA_DATAS,
    hiddenimports=KEYRING_HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # app graphique : jamais de fenêtre de terminal au double-clic
    icon=None,  # pas d'icône pour l'instant (§6 : à ajouter avant diffusion)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
