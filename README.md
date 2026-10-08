# Relinkbox

A small desktop app that relinks Rekordbox 6 library tracks to music files on disk after you move folders, change drives, or rename files.

Developed and tested on **Python 3.14**. Should also work on 3.10–3.13.

## What it does

- Relink tracks in `master.db` to files in a music folder
- Find music files that are not in the Rekordbox library
- Fix displayed filenames without changing paths
- Create a timestamped backup of the database before you change it

**Close Rekordbox before you run it.** The app writes to the same database Rekordbox uses. Always keep the backup it creates.

## Setup (Windows)

1. Install [Python](https://www.python.org/downloads/) (3.10+) and tick **Add python.exe to PATH**.
2. In this folder, open PowerShell and run:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -e .
```

3. Start the app:

```powershell
python -m relinkbox
```

Or double-click `RUN.bat` after the venv exists.

## Clone from GitHub

```powershell
git clone https://github.com/TALE5/relinkbox.git
cd relinkbox
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -e .
python -m relinkbox
```
