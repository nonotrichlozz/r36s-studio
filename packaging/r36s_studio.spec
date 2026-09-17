# -*- mode: python ; coding: utf-8 -*-
"""Spec PyInstaller pour la construction locale macOS (§6/§7, phase 7).

Produit une vraie `.app` avec un `Info.plist` correct (identifiant de
bundle stable, nom, version) : c'est cette identité de bundle qui permet à
macOS de proposer l'app dans Réglages Système -> Confidentialité et
sécurité -> Accès complet au disque, contrairement à un interpréteur
`python3` nu relancé par `osascript` (§3 -- le blocage TCC sur
`/dev/rdiskN` documenté depuis la phase 4). Construction :

    packaging/build_macos.sh

Voir `packaging/README.md` pour la procédure complète, y compris comment
vérifier si ce blocage disparaît une fois l'app autorisée.

CI GitHub Actions volontairement absente pour l'instant : ce point doit
être vérifié sur du vrai matériel avant d'automatiser quoi que ce soit
(§7, feuille de route)."""

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
from r36s_studio import __version__ as APP_VERSION  # noqa: E402

APP_NAME = "R36S Studio"

# Identifiant de bundle stable : c'est lui, pas le nom affiché, que macOS
# retient pour l'autorisation Accès complet au disque. Le changer plus
# tard oblige à réautoriser l'app -- à personnaliser avant une vraie
# diffusion (§6), mais garder une valeur fixe d'ici là.
BUNDLE_IDENTIFIER = "com.r36sstudio.desktop"
BUNDLE_VERSION = APP_VERSION

# Horodatage de construction (§5, gui/build_info.py) : sans repère visible
# dans l'interface, impossible de savoir si le binaire testé contient les
# derniers correctifs -- vécu directement en développement (plusieurs
# reconstructions locales de suite, indiscernables une fois lancées).
# Heure locale de la machine de construction, pas UTC : cette machine est
# aussi celle sur laquelle le binaire est testé juste après -- l'UTC
# n'apporterait qu'une conversion mentale à chaque vérification, sans
# gain (aucune diffusion multi-fuseaux à ce stade, §7). Généré ici (à
# l'évaluation du .spec, donc à chaque construction) plutôt que committé :
# `build/` est déjà ignoré par Git (voir .gitignore).
BUILD_TIMESTAMP_FILE = PROJECT_ROOT / "build" / "build_timestamp.txt"
BUILD_TIMESTAMP_FILE.parent.mkdir(parents=True, exist_ok=True)
BUILD_TIMESTAMP_FILE.write_text(datetime.now().strftime("%d/%m/%Y à %H:%M"))

# Illustrations décoratives (§5, gui/asset_paths.py) : incluses seulement
# si présentes -- leur absence ne doit jamais empêcher la construction ni
# l'affichage de l'interface (§5). `"assets"` comme destination doit
# correspondre à ce qu'`asset_paths.assets_dir()` attend de trouver sous
# `sys._MEIPASS` une fois l'app empaquetée.
ASSETS_DIR = PROJECT_ROOT / "r36s_studio" / "gui" / "assets"
EXTRA_DATAS = [
    (str(ASSETS_DIR / name), "assets")
    for name in ("console.png", "circuit.png")
    if (ASSETS_DIR / name).exists()
]

# `keyring` (consoles_diverses/settings_store.py) choisit son backend par
# introspection au moment de l'exécution -- PyInstaller ne le détecte pas
# automatiquement, il faut le déclarer explicitement (voir CLAUDE.md
# racine, § durcissement consoles_diverses, point 5). `macOS` est le
# backend natif (Trousseau) ; `chainer`/`fail` sont les deux backends
# génériques que `keyring` charge toujours en repli, quel que soit l'OS.
KEYRING_HIDDEN_IMPORTS = [
    "keyring.backends.macOS",
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

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=None,  # pas d'icône pour l'instant (§6 : à ajouter avant diffusion)
    bundle_identifier=BUNDLE_IDENTIFIER,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_IDENTIFIER,
        "CFBundleVersion": BUNDLE_VERSION,
        "CFBundleShortVersionString": BUNDLE_VERSION,
        "CFBundlePackageType": "APPL",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
        # Accès disque amovible : l'app lit/écrit des cartes SD explicitement
        # choisies par l'utilisateur (règle §2), jamais en arrière-plan.
        "NSRemovableVolumesUsageDescription": (
            "R36S Studio a besoin d'accéder à la carte SD que tu choisis "
            "pour la sauvegarder, la préparer ou y copier des jeux."
        ),
    },
)
