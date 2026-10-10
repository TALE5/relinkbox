# Relinkbox

A small desktop app that relinks Rekordbox 6 and 7 library tracks to music files on disk after you move folders, change drives, or rename files. Your cue points, beat grids, and playlists stay attached to the tracks.

I made this with almost zero coding experience after deciding that manually relinking songs one by one, by the thousands, wasn't on the table. Pioneer has yet to build a solution that actually works for this, so I spent under a day making a better one and have kept improving it since.

> **Heads-up:** Relinkbox was built with a lot of help from AI coding tools. It has tests, makes a backup before every change, and has been tried on a real 14,000-track library, but it is a hobby project and comes with no warranty. Keep your backups.

## Download

Pick one from the [latest release](https://github.com/TALE5/relinkbox/releases/latest). You do not need Python or a terminal.

- **Relinkbox.exe** — one file. Download it and double-click it. The first start takes a few seconds longer while Windows unpacks it.
- **Relinkbox.zip** — unzip it, open the `Relinkbox` folder, and double-click `Relinkbox.exe`. Starts faster. Leave that exe in the folder.

What you need either way:

- 64-bit Windows 10 or 11
- Rekordbox 6 or 7 (tested with 7.2)
- Rekordbox closed before you save changes. Scanning works while it is open.

## Why would you need it?

- Rekordbox links each track to your music file by its full path, stored in an encrypted database (`master.db`).
- The path is the only link. Rename a file, move a folder, or change a drive letter, and the link breaks.
- Rekordbox's own relocate feature only lets you relink tracks one by one, or search another folder for files with exactly the same name.

I bulk rename my music, and at one point I renamed around 10,000 tracks before realizing that this broke most of my links in Rekordbox. The only alternative was relinking them one at a time.

## What it does

- **Find and relink missing tracks.** Only tracks whose file no longer exists are touched. Relinkbox searches your music folders for each one (see [How matching works](#how-matching-works)).
- **A folder or drive moved.** When `E:\Music` became `F:\Music`, or a whole folder moved, this relinks exactly by keeping each track's subfolders and filename.
- **Find files not in Rekordbox.** Save them as an `.m3u8` playlist you can import into Rekordbox, save a plain list, or copy them somewhere.
- **Fix display names.** Makes the File Name column match the actual file without changing paths.
- **Check cue points.** Finds tracks whose cues sit off the beat grid by the same amount, shows them on the waveform, and can snap them back. A backup is made first.

## How it keeps your library safe

- **You see every change first.** Nothing is written until you review the list and click Relink. Each match shows how it was found, a confidence level, and notes. High and medium confidence matches are ticked for you; low confidence ones are not.
- **It won't guess.** When several files could be the same track, for example two copies or a v1 and v2, you pick the right one.
- **It warns you** when a drive is not connected (maybe you only unplugged it), when the file type changed (re-analyze the track), when a file is much larger or smaller than before (check the cue points), and when a file is already in your library as another track.
- **A backup before every change.** Each save creates a folder in `Relinkbox backups` next to `master.db`. It holds the database, `masterPlaylists6.xml`, the analysis files that were changed, and a `changes.csv` listing every old and new path. Use **Restore a backup** to go back; your current library is backed up again before restoring.
- **Rekordbox must be closed.** Relinkbox checks and refuses to save while Rekordbox is running.
- **It checks its work.** After saving, it re-opens the database and confirms every change is there.
- **Everything is logged** in `%LOCALAPPDATA%\Relinkbox\logs`. Use **Open log folder** in the app.

Relinkbox updates the same things Rekordbox's own relocate does: the track path, the file name, and the path stored in the track's analysis files.

## How matching works

For each missing track, Relinkbox tries these rules in order and stops at the first one that finds a file:

| Rule | What it means | Confidence |
| --- | --- | --- |
| Same name and size | Same filename, and the same size Rekordbox remembers | High |
| Same name, different size | Same filename, but the file changed size | Medium |
| Renamed, same size | Different filename, but exactly the same size | High if the names are at least 95% similar, Medium from 60%, otherwise Low |
| Same name, different file type | For example `.mp3` became `.flac` | Low |
| Similar name | Names at least 85% similar | Medium at 95% or more with the same file type (High if the size also matches), otherwise Low |

A few rules apply on top of that:

- **Several candidates means you choose.** If two or more files fit about equally well, the track is marked "pick a file" instead of guessing. A file in a folder with the same name as the old one wins a tie.
- **Changed numbers stay Low.** If a number in the old name is missing from the new one ("v1" became "v2", "Part 1" became "Part 2"), it could be a different version, so it is never ticked automatically.
- **WAV and AIFF need similar names.** Uncompressed files of the same length have the same size, so for those, an identical size only counts if the names are at least 60% similar.
- **Why size and not track length?** File size comes free with the folder scan and is exact to the byte. Track length would mean opening every file, and Rekordbox only stores it to the second, so it can't tell tracks apart as well. Size has one catch: Rekordbox doesn't update it when you edit tags or artwork, so small differences are expected. When the size differs by 5% or more, the file may be a different encode or version, and Relinkbox tells you to check the cue points.

Folders that can't be read are skipped and logged. Streaming tracks (SoundCloud, Beatport and so on) are left alone.

## Cue points

**Check cue points...** opens a separate window. It only reads the local analysis files Rekordbox already uses on this PC (the beat grid and waveform). USB exports are not touched. Cue changes are written only to the database.

For each track with cues it:

1. Measures how far each cue sits from the nearest beat.
2. Looks for a **shared offset** of at least 3 cues, within 3 ms of each other, that does not drift along the track.
3. Names the cause when it can. Re-encoding FLAC to MP3 often leaves cues early by 2257 samples (51 ms at 44.1 kHz, 47 ms at 48 kHz). That known offset is accepted at any BPM.
4. Checks the waveform to see whether the drum hits line up with the grid or with the cues.
5. Leaves cues that do not share the offset alone (those were probably placed off the grid on purpose).

Tracks marked **Cues off grid** are ticked for you. You can play the track, click the waveform, and press a cue button. If the picture is unclear, mark **The cues are right** or **The grid is right** before snapping. **Snap selected** moves the matching cues onto the beat (and the loop end by the same amount), after a backup. VBR MP3 cues that store a byte offset are left alone.

A shift with no known cause is only offered automatically when it is under 80 ms and under a quarter of a beat at that track's tempo. Larger or mixed offsets stay in **Check manually**.

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

## License

Relinkbox is free software under the [GNU General Public License v3.0 or later](LICENSE). You can use, study, change, and share it. If you share a changed version, you share its source under the same license.

## Third-party software

Relinkbox is built on these projects, and the downloadable exe and zip include them:

- [pyrekordbox](https://github.com/dylanljones/pyrekordbox) (MIT) — reads and writes the Rekordbox database and analysis files
- [PySide6 / Qt for Python](https://www.qt.io/qt-for-python) (LGPL-3.0) — the user interface. Source: [code.qt.io](https://code.qt.io/cgit/pyside/pyside-setup.git/)
- [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) (MIT) — fast filename similarity
- [SQLAlchemy](https://www.sqlalchemy.org/) (MIT) and [sqlcipher3-wheels](https://github.com/laggykiller/sqlcipher3) (zlib) — database access
- Their own dependencies, such as NumPy and psutil (BSD)

In the zip version the Qt libraries are separate files in the `Relinkbox` folder, so you can replace them with your own build. This project is not affiliated with AlphaTheta or Pioneer DJ. Rekordbox is their trademark.
