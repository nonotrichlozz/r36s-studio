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

# Catalogue local des émulateurs Android (android/emulators.py, étape 1,
# docs/android-adb.md) -- même principe que les illustrations ci-dessus :
# un fichier de données ordinaire, jamais embarqué automatiquement dans le
# PYZ par PyInstaller. Destination alignée sur `android/emulators.py::
# _data_dir`.
ANDROID_DATA_DIR = PROJECT_ROOT / "r36s_studio" / "android" / "data"
EXTRA_DATAS += [
    (str(ANDROID_DATA_DIR / name), "android/data") for name in ("emulateurs.json",) if (ANDROID_DATA_DIR / name).exists()
]

# Liste des extensions de ROM (doublons/extensions.py) -- contrairement aux
# fichiers ci-dessus, *obligatoire* : lue a l'import du module, lui-meme
# importe par __main__.py au demarrage. Son absence faisait planter le
# binaire des le double-clic (FileNotFoundError). Jamais conditionnee a
# `.exists()` : un fichier manquant doit faire echouer la construction,
# pas produire un binaire qui plante. Destination alignee sur
# `Path(__file__).parent / "data"` (sys._MEIPASS/r36s_studio/doublons/data).
DOUBLONS_DATA_FILE = PROJECT_ROOT / "r36s_studio" / "doublons" / "data" / "extensions.json"
if not DOUBLONS_DATA_FILE.exists():
    raise SystemExit(f"Fichier de donnees obligatoire introuvable : {DOUBLONS_DATA_FILE}")
EXTRA_DATAS.append((str(DOUBLONS_DATA_FILE), "r36s_studio/doublons/data"))

# Tables du tri (tri/tables.py, docs/tri-roms.md) -- lues a l'ouverture de
# l'ecran « Ranger mes jeux ». Obligatoires, meme regle que ci-dessus.
for _tri_name in ("systems.json", "firmware_folders.json"):
    _tri_file = PROJECT_ROOT / "r36s_studio" / "tri" / "data" / _tri_name
    if not _tri_file.exists():
        raise SystemExit(f"Fichier de donnees obligatoire introuvable : {_tri_file}")
    EXTRA_DATAS.append((str(_tri_file), "r36s_studio/tri/data"))

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
# Modules Qt jamais utilisés (l'app n'importe que QtCore/QtGui/QtWidgets/
# QtNetwork) mais tirés par les plugins de PySide6. Qt Virtual Keyboard en
# particulier n'existe qu'en GPL v3 ou licence commerciale, jamais en LGPL :
# incompatible avec la licence de R36S Studio (THIRD_PARTY_NOTICES.txt).
_EXCLUDED_QT = ("virtualkeyboard", "qt6quick", "qtquick", "qt6qml", "qtqml", "qt6pdf", "qtpdf", "qpdf")
a.binaries = [entry for entry in a.binaries if not any(name in entry[0].lower() for name in _EXCLUDED_QT)]
a.datas = [entry for entry in a.datas if not any(name in entry[0].lower() for name in _EXCLUDED_QT)]
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
