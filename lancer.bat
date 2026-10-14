@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m r36s_studio
) else (
  python -m r36s_studio
)
if errorlevel 1 pause
