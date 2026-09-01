#!/bin/sh
# Construction locale ou CI Linux de R36S Studio (§6/§7).
# Voir packaging/README.md pour la procédure complète.
set -eu

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    echo "Aucun .venv trouvé -- création." >&2
    python3 -m venv .venv
fi

# shellcheck disable=SC1091
. .venv/bin/activate

pip install --upgrade pip -q
pip install -r requirements.txt -r requirements-dev.txt -q
pip install --upgrade pyinstaller -q

pyinstaller --noconfirm packaging/r36s_studio_linux.spec

echo
echo "Construite : dist/R36S Studio/R36S Studio"
