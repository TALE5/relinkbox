# *Build is currently broken, working on a fix*

# Relinkbox

A small desktop app that relinks Rekordbox 6 library tracks to music files on disk after you move folders, change drives, or rename files.

I made this with almost zero coding experience after deciding manually relinking songs one by one by the thousands wasn't on the table.
Pioneer has yet to develop a solution with actual functionality, so i spent under a day creating a better solution and have since experimented a bit.
This build is skinned down with the core functionality intact*.

## Download

Pick one from the [latest release](https://github.com/TALE5/relinkbox/releases/latest). You do not need Python or a terminal.

- **Relinkbox.exe** — one file. Download it and double-click it. The first start takes a few seconds longer while Windows unpacks it.
- **Relinkbox.zip** — unzip it, open the `Relinkbox` folder, and double-click `Relinkbox.exe`. Starts faster. Leave that exe in the folder.

What you need either way:

- 64-bit Windows 10 or 11
- Rekordbox closed before you run Relinkbox

The app writes to the same database Rekordbox uses. It makes a timestamped backup of the .db *first* in the same folder. Keep that backup.

## What it does

- Easily track and Relink tracks in `master.db` to files in a music folder using fuzzy matching
- Find music files that are not in the Rekordbox library
- Fix displayed filenames without changing paths
- Create a timestamped backup of the database before you change it

## How it works

- The tool uses fuzzy matching to relink tracks (in bulk) that Rekordbox cannot.
- Variables are set, and i aim to make them adjustable by the user.
- Length needs to be a 100% match.

## Why would you need it?

- Rekordbox's database stores its links to your local files in an encrypted .db
- The link is path based, meaning the file name is the only identifier.
- If the file name is changed what so ever, the path will be broken and thus the link disappears.
- Rekordbox's own relocation feature only allows you to either manually link files one by one, or change/search in another location (which requires file names to be identical to the .db path entry)

## "Why would you even need this?"

- I bulk rename my music, and at one point i renamed around 10 000 tracks only to realize that this would break most links i had in Rekordbox.
- The only available alternative was to relink songs 1 by 1 due to the limited nature of Rekordbox's relocator.

## Build the exe and the zip

This is only if you are making the downloadable files yourself. People who download a release can skip this.

1. Install [Python](https://www.python.org/downloads/) 3.10 or newer (developed on 3.14) and tick **Add python.exe to PATH**.
2. In this folder, open PowerShell:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -e ".[build]"
.\build_release.ps1
```

That writes `release\Relinkbox.exe` and `release\Relinkbox.zip`.

## Develop from source

Same Python setup as above, then:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -e .
python -m relinkbox
```

Or double-click `RUN.bat` after the venv exists.

## Clone from GitHub

```powershell
git clone https://github.com/TALE5/relinkbox.git
cd relinkbox
```

Then follow **Develop from source**, or **Build the exe and the zip** if you want the packages.
