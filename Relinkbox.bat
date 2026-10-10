@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
    echo The virtual environment is missing. See the README, under Develop from source.
    pause
    exit /b 1
)
start "" "venv\Scripts\pythonw.exe" -m relinkbox
