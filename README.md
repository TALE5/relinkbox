# *Build is currently broken, working on a fix*

# Relinkbox

A small desktop app that relinks Rekordbox 6 and 7 library tracks to music files on disk after you move folders, change drives, or rename files. Your cue points, beat grids, and playlists stay attached to the tracks.

I made this with almost zero coding experience after deciding manually relinking songs one by one by the thousands wasn't on the table.
Pioneer has yet to develop a solution with actual functionality, so i spent under a day creating a better solution and have since experimented a bit.
This build is skinned down with the core functionality intact*.

## Download

Pick one from the [latest release](https://github.com/TALE5/relinkbox/releases/latest). You do not need Python or a terminal.

- **Relinkbox.exe** — one file. Download it and double-click it. The first start takes a few seconds longer while Windows unpacks it.
- **Relinkbox.zip** — unzip it, open the `Relinkbox` folder, and double-click `Relinkbox.exe`. Starts faster. Leave that exe in the folder.

What you need either way:

- 64-bit Windows 10 or 11
- Rekordbox 6 or 7 (tested with 7.2)
- Rekordbox closed before you save changes. Scanning works while it is open.

## What it does

- **Find and relink missing tracks.** Only tracks whose file no longer exists are touched. Relinkbox searches your music folders and matches by name and file size first, then renamed files with the same size, then a changed file type, then similar names.
- **A folder or drive moved.** When `E:\Music` became `F:\Music`, or a whole folder moved, this relinks exactly by keeping each track's subfolders and filename.
- **Find files not in Rekordbox.** Save them as an `.m3u8` playlist you can import into Rekordbox, save a plain list, or copy them somewhere.
- **Fix display names.** Makes the File Name column match the actual file without changing paths.

## How it keeps your library safe

- **You see every change first.** Nothing is written until you review the list and click Relink. Each match shows how it was found, a confidence level, and notes. High and medium confidence matches are ticked for you; low confidence ones are not.
- **It won't guess.** When several files could be the same track, for example two copies or a v1 and v2, you pick the right one.
- **It warns you** when a drive is not connected (maybe you only unplugged it), when the file type changed (re-analyze the track), when a file is much larger or smaller than before (check the cue points), and when a file is already in your library as another track.
- **A backup before every change.** Each save creates a folder in `Relinkbox backups` next to `master.db`. It holds the database, `masterPlaylists6.xml`, the analysis files that were changed, and a `changes.csv` listing every old and new path. Use **Restore a backup** to go back; your current library is backed up again before restoring.
- **Rekordbox must be closed.** Relinkbox checks and refuses to save while Rekordbox is running.
- **It checks its work.** After saving, it re-opens the database and confirms every change is there.
- **Everything is logged** in `%LOCALAPPDATA%\Relinkbox\logs`. Use **Open log folder** in the app.

Relinkbox updates the same things Rekordbox's own relocate does: the track path, the file name, and the path stored in the track's analysis files.

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

Run the tests:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
```

## Clone from GitHub

```powershell
git clone https://github.com/TALE5/relinkbox.git
cd relinkbox
```

Then follow **Develop from source**, or **Build the exe and the zip** if you want the packages.
