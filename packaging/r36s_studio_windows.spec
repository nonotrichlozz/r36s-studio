# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour la construction Windows (§6/§7, phase 7).

Contrairement à macOS (`r36s_studio.spec`), l'élévation Windows passe par
`ShellExecuteW` (verbe `runas` -> invite UAC, voir `gui/elevate.py`) sur le
binaire lui-même (`sys.executable`, une fois `sys.frozen`) : aucune
identité de paquet particulière n'est nécessaire comme pour l'Accès
complet au disque macOS (§3) -- un simple exécutable onedir suffit.

Construction (locale ou CI, voir packaging/build_windows.ps1 et le
workflow `.github/workflows/build.yml`) :

    packaging/build_windows.ps1

Résultat : `dist/R36S Studio/R36S Studio.exe` (+ ses dépendances à côté,
onedir -- jamais onefile : PySide6 est sous LGPLv3, qui exige que les DLL
Qt restent des fichiers séparés et remplaçables plutôt que fusionnées dans
un binaire opaque, voir `packaging/README.md` §2 « Onedir, jamais onefile »
pour le détail. L'artefact est de toute façon distribué en `.zip`, §7)."""

import sys
from datetime import datetime
from pathlib import Path

block_cipher = None

# SPECPATH (fourni par PyInstaller) = dossier contenant ce fichier, donc
# packaging/ -- la racine du projet est son parent.
PACKAGING_DIR = Path(SPECPATH)
PROJECT_ROOT = PACKAGING_DIR.parent
ENTRY_SCRIPT = str(PACKAGING_DIR / "entry.py")

sys.path.insert(0, str(PROJECT_ROOT))

APP_NAME = "R36S Studio"

# Horodatage de construction (§5, gui/build_info.py), même principe que le
# spec macOS -- généré ici (à l'évaluation du .spec, donc à chaque
# construction) plutôt que committé : `build/` est déjà ignoré par Git.
# Heure locale de la machine de construction (celle de CI en pratique ici,
# donc UTC côté GitHub Actions -- sans conséquence, ce champ n'a jamais eu
# vocation à être comparé entre machines, seulement à distinguer deux
# constructions successives).
BUILD_TIMESTAMP_FILE = PROJECT_ROOT / "build" / "build_timestamp.txt"
BUILD_TIMESTAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
BUILD_TIMESTAMP_FILE.write_text(datetime.now().strftime("%d/%m/%Y à %H:%M"), encoding="utf-8")

# Illustrations décoratives (§5, gui/asset_paths.py) : incluses seulement
# si présentes -- leur absence ne doit jamais empêcher la construction ni
# l'affichage de l'interface (§5).
ASSETS_DIR = PROJECT_ROOT / "r36s_studio" / "gui" / "assets"
EXTRA_DATAS = [
    (str(ASSETS_DIR / name), "assets")
    for name in ("console.png", "circuit.png")
    if (ASSETS_DIR / name).exists()
]

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
