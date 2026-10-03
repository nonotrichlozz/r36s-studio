#!/bin/sh
# Construction locale macOS de R36S Studio (§6/§7, phase 7).
# Voir packaging/README.md pour la procédure complète et la vérification
# de l'accès disque une fois l'app construite.
#
# Cibles :
#   packaging/build_macos.sh          construit seulement dist/R36S Studio.app
#   packaging/build_macos.sh dist     construit puis produit en plus
#                                      dist/R36S-Studio-macos.zip, prêt à
#                                      distribuer (app + LISEZ-MOI.txt) --
#                                      réutilisée telle quelle par la CI
#                                      (.github/workflows/build.yml), pour
#                                      qu'il n'existe qu'un seul endroit qui
#                                      décide de ce que contient l'archive.
#   packaging/build_macos.sh dmg      idem, mais produit
#                                      dist/R36S-Studio-macOS.dmg (Release,
#                                      .github/workflows/release.yml).
set -eu

cd "$(dirname "$0")/.."

TARGET="${1:-app}"

if [ ! -d .venv ]; then
    echo "Aucun .venv trouvé -- création (voir packaging/README.md)." >&2
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate

pip install --upgrade pip -q
pip install -r requirements.txt -r requirements-dev.txt -q
pip install --upgrade pyinstaller -q

pyinstaller --noconfirm packaging/r36s_studio.spec

echo
echo "Construite : dist/R36S Studio.app"

if [ "$TARGET" != "dist" ] && [ "$TARGET" != "dmg" ]; then
    echo "Prochaine étape : packaging/README.md, section \"Vérifier l'accès disque\"."
    exit 0
fi

# Dossier de mise en scène temporaire plutôt qu'un `zip -r`/`ditto` direct
# sur `dist/` : `dist/` peut contenir d'autres artefacts (build/, une
# ancienne archive...) qui n'ont rien à faire dans le paquet distribué --
# seuls l'app, LISEZ-MOI.txt, LICENSE et THIRD_PARTY_NOTICES.txt y entrent,
# explicitement copiés un par un.
# `ditto`, pas `zip -r` : seul lui préserve correctement la structure et
# les attributs étendus d'un vrai bundle .app macOS.
STAGING_ROOT="$(mktemp -d)"
STAGING_DIR="$STAGING_ROOT/R36S-Studio-macos"
mkdir -p "$STAGING_DIR"
ditto "dist/R36S Studio.app" "$STAGING_DIR/R36S Studio.app"
cp packaging/LISEZ-MOI.txt "$STAGING_DIR/LISEZ-MOI.txt"
cp LICENSE "$STAGING_DIR/LICENSE.txt"
cp THIRD_PARTY_NOTICES.txt "$STAGING_DIR/THIRD_PARTY_NOTICES.txt"

if [ "$TARGET" = "dmg" ]; then
    # Raccourci Applications : glisser-déposer l'app dessus pour l'installer.
    ln -s /Applications "$STAGING_DIR/Applications"
    rm -f "dist/R36S-Studio-macOS.dmg"
    hdiutil create -volname "R36S Studio" -srcfolder "$STAGING_DIR" -ov -format UDZO "dist/R36S-Studio-macOS.dmg"
    rm -rf "$STAGING_ROOT"
    echo "Image prête à distribuer : dist/R36S-Studio-macOS.dmg"
    exit 0
fi

rm -f "dist/R36S-Studio-macos.zip"
ditto -c -k --sequesterRsrc --keepParent "$STAGING_DIR" "dist/R36S-Studio-macos.zip"
rm -rf "$STAGING_ROOT"

echo "Archive prête à distribuer : dist/R36S-Studio-macos.zip"
echo "Prochaine étape : packaging/README.md, section \"Vérifier l'accès disque\"."
