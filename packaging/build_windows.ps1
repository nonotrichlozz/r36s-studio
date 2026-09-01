# Construction locale ou CI Windows de R36S Studio (paragraphes 6/7 du brief).
# Voir packaging/README.md pour la procedure complete.

$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    Write-Host "Aucun .venv trouve -- creation."
    python -m venv .venv
}

. .\.venv\Scripts\Activate.ps1

pip install --upgrade pip -q
pip install -r requirements.txt -r requirements-dev.txt -q
pip install --upgrade pyinstaller -q

pyinstaller --noconfirm packaging/r36s_studio_windows.spec

Write-Host ""
Write-Host "Construite : dist/R36S Studio/R36S Studio.exe"
