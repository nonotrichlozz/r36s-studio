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

# `keyring` (consoles_diverses/settings_store.py) : aucun `hiddenimports`
# manuel nécessaire ici -- PyInstaller fournit son propre hook officiel
# (`hook-keyring.py`, `collect_submodules('keyring.backends')` +
# `copy_metadata('keyring')`, cette dernière indispensable puisque
# `keyring` découvre ses backends via les points d'entrée setuptools de sa
# propre métadonnée) qui s'applique automatiquement dès que `keyring` est
# importé quelque part dans le code -- vérifié en conditions réelles sur
# le binaire Windows (même hook, non spécifique à un OS -- voir
# `r36s_studio_windows.spec` pour le détail de cette vérification ; non
# encore reconstruit sur du vrai matériel Linux à ce jour, notamment le
# cas d'un environnement sans `SecretService`/`kwallet` actif, où
# `keyring` retombe sur son backend `fail` -- lui aussi collecté par le
# même hook). Une première version de ce fichier déclarait une liste
# manuelle de backends par hypothèse -- retirée : elle n'ajoutait rien
# face au hook déjà présent.

a = Analysis(
    [ENTRY_SCRIPT],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[(str(BUILD_TIMESTAMP_FILE), ".")] + EXTRA_DATAS,
    hiddenimports=[],
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
