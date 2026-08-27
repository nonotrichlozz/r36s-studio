#!/bin/sh
# Construction locale macOS de R36S Studio (§6/§7, phase 7).
# Voir packaging/README.md pour la procédure complète et la vérification
# de l'accès disque une fois l'app construite.
set -eu

cd "$(dirname "$0")/.."

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
echo "Prochaine étape : packaging/README.md, section \"Vérifier l'accès disque\"."
