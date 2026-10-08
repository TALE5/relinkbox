@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Create a venv first. See README.md
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
python -m relinkbox
