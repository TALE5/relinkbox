<p align="left">
<img src="relinkbox_brand_assets/png/relinkbox-wordmark-transparent.png" alt="Relinkbox" height="100">

</p>

[![License: GPL-3.0](https://img.shields.io/badge/License-GPL--3.0-FF910F.svg)](LICENSE)

A Windows desktop app that puts a Rekordbox 6 or 7 library back together after the music on disk has moved. Rekordbox stores each track’s full file path in an encrypted database (`master.db`). Rename a file, move a folder, or change a drive letter, and that path is the only thing that breaks. Cue points, loops, beat grids, playlists, and history stay on the track, because they belong to the track, not to the path.

Relinkbox finds the file again, or points a whole folder at its new location, and writes the new path back. It can also fix the file name Rekordbox still shows after a rename, list music files the library has never seen, and snap cue points that all sit the same distance off the beat grid.

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

Until you choose one, Relinkbox looks for `master.db` in `%APPDATA%\Pioneer\rekordbox`. If yours lives somewhere else, use **Choose database...**. The database and the music folders you add are remembered the next time you open the app. **Open folder** jumps to the Rekordbox folder or to the backups folder next to it.

## Why the links break

Rekordbox’s own relocate feature only lets you relink tracks one by one, or search another folder for a file with exactly the same name. There is no way to say “this whole folder is now on another drive,” and no way to find a file whose name changed.

I bulk rename my music, and at one point I renamed around 10,000 tracks before realizing that this broke most of my links in Rekordbox. The only alternative was relinking them one at a time.

## What you can do

All four jobs on the main window only look until you confirm. A yellow banner appears while Rekordbox is running. Saving is refused until it is fully closed.

### Scan for missing tracks

Looks through the music folders you added and proposes a file for every track whose path no longer exists. Tracks that already point at a real file are left alone. Streaming and cloud entries (SoundCloud, Beatport, and anything else stored as a link rather than a drive path) are skipped.

A review window then lists:

- **Proposed matches**, with the old path, the new file, how it was found, a confidence level, and any warning. High and medium confidence matches are ticked. Low confidence matches are left unticked. When several files fit about equally well, the row says “pick a file” and you choose from the list. **Select recommended**, **Select all**, and **Select none** are there if you want to change the ticks in one go.
- **Still missing**, the tracks no rule could place.

From that window you can export the full report or just the missing tracks as CSV (UTF-8, so Excel keeps accented names). Confirming asks once more, and tells you if any of the ticked rows are low confidence. A backup is made, the changes are written, and Relinkbox re-opens the database to check that each new path is actually there.

### A whole folder or drive letter changed

Use this when you already know the move, for example `E:\Music` is now `F:\Music`. Relinkbox reads the missing tracks and suggests the deepest folder that holds most of them. You set the old location (as Rekordbox stored it) and the new one. Every missing track under that old folder keeps its subfolders and filename, and the new path is only offered when that file is really there. The same review window opens before anything is saved.

### Find music files Rekordbox doesn't have

Walks the same music folders and lists audio files with no library entry. Overlapping folders are counted once. These formats are included: MP3, FLAC, WAV, AIFF, M4A, AAC, MP4, ALAC, and OGG.

You can then:

- save an `.m3u8` playlist and import it in Rekordbox with **File > Import > Import Playlist**
- save a plain `.txt` list of paths
- copy the files into another folder, either all together or with their subfolders kept

Existing files at the destination are left in place. Relinkbox does not add anything to the library itself.

### Rekordbox is showing the wrong file name

Rekordbox keeps its own file-name field, separate from the name of the file on disk. After a rename, the track can still display the old name even though the path is correct. This lists every local track where those two differ, shows the name in the library beside the name on disk, and updates the library name after you confirm. The file stays where it is.

### Cue Manager

Opens in its own window. It reads the local analysis files Rekordbox already uses on this PC (the beat grid and the waveform) and compares every cue to the nearest beat. USB exports are never touched, and the analysis files themselves are only read. Cue changes are written only to the database.

The scan gives each track one of these verdicts:

| Verdict | What it means |
| --- | --- |
| On grid | Every cue is within 2 ms of a beat |
| Cues off grid | Several cues share one offset, and the drums line up with the grid. The known MP3 encoder delay counts too, even with no waveform. Ticked for snapping. |
| Grid looks off | The drums line up with the cues, so the grid may be the thing that's wrong |
| Check manually | Too few cues agree, the offset drifts, or the shift is too large to trust |
| No beat grid | There is no grid to compare against |

You can filter by verdict, search, and sort the list. Select a track to open it in the player: a whole-track strip, a zoomed waveform (Rekordbox’s 3-band waveform when a `.2EX` file exists), hot-cue pads A–H, memory cues, cover art when the file has it, and a volume control. Scroll to zoom, shift-drag to pan, drag to scrub, or click a cue to play from that point. The player can be collapsed.

If the picture is unclear, **The cues are right** or **The grid is right** overrides the verdict before you snap. **Snap selected** moves the matching cues onto the beat, and moves a loop’s end by the same amount. A backup is made first. VBR MP3 cues that store a byte position are left alone. Cue Manager does not rewrite the beat grid.

The rules behind a snap:

1. Measure how far each cue sits from the nearest beat.
2. Look for a shared offset of at least 3 cues, within 3 ms of each other, that does not drift along the track.
3. Name the cause when it can. Re-encoding FLAC to MP3 often leaves cues early by 2257 samples (51 ms at 44.1 kHz, 47 ms at 48 kHz). That known offset is accepted at any BPM.
4. Check the waveform to see whether the drum hits line up with the grid or with the cues.
5. Leave cues that do not share the offset alone. Those were probably placed off the grid on purpose.

A shift with no known cause is only offered automatically when it is under 80 ms and under a quarter of a beat at that track’s tempo. Larger or mixed offsets stay in **Check manually**.

## What a save writes

A relink updates the same records Rekordbox’s own relocate updates:

- the track path
- the original path, when it still matched the old one
- the file name Rekordbox displays
- the file type, when the extension changed (MP3, M4A/AAC, FLAC, WAV, AIFF)
- the file size
- the path stored inside the track’s local analysis files

An analysis file is left unchanged, with a warning, when it contains a section Relinkbox cannot rewrite. Saving would otherwise drop that section. If the database write fails, the change is rolled back and nothing from that save is kept.

Cue snaps write the cue’s time (and the loop end, when there is one) in the cue table and in the matching hot-cue bank. Display-name fixes write only the name field.

## What it leaves alone

- Tracks whose file is still where Rekordbox says it is
- Streaming and cloud tracks
- Files already in the library, when you are only looking for untracked music
- Analysis files on USB exports
- The beat grid, waveform, tags, playlists, and play history
- Cue points that do not share the offset being snapped, including VBR MP3 cues stored as a byte position

## How it keeps your library safe

- **You see every change first.** Each match shows how it was found, a confidence level, and notes.
- **It won't guess.** When several files could be the same track, for example two copies or a v1 and v2, you pick the right one.
- **It warns you** when a drive is not connected (maybe you only unplugged it), when the file type changed (re-analyze the track), when a file is much larger or smaller than before (check the cue points), when a file is already in your library as another track, and when the same file is proposed for more than one track.
- **A backup before every change.** Each save creates a timestamped folder in `Relinkbox backups` next to `master.db`. It holds the database (and its `-wal` / `-shm` / `-journal` files when they exist), `masterPlaylists6.xml`, the analysis files that were about to be changed, and a CSV of every change (`changes.csv` for paths and names, `cue_changes.csv` for cue snaps).
- **Restore a backup** puts that folder back. Your current library is backed up again first, so a restore can be undone. The list also includes older Relinkbox backup files and Rekordbox’s own `master.backup*.db` files. Those restore the database only. You can browse to a `.db` file if it is not in the list.
- **Rekordbox must be closed.** Relinkbox checks and refuses to save while Rekordbox is running.
- **It checks its work.** After saving, it re-opens the database and confirms every change is there.
- **Everything is logged** in `%LOCALAPPDATA%\Relinkbox\logs`. Use **Open log folder** in the app. The main window also keeps the last result: counts, skipped tracks, warnings, and each old path beside the new one.

## How matching works

For each missing track, Relinkbox tries these rules in order and stops at the first one that finds a file. The folder-move action above does not use this search. It rewrites the path directly.

| Rule | What it means | Confidence |
| --- | --- | --- |
| Same name and size | Same filename, and the same size Rekordbox remembers | High |
| Same name, different size | Same filename, but the file changed size | Medium |
| Renamed, same size | Different filename, but exactly the same size | High if the names are at least 95% similar, Medium from 60%, otherwise Low |
| Same name, different file type | For example `.mp3` became `.flac` | Low |
| Similar name | Names at least 85% similar | Medium at 95% or more with the same file type (High if the size also matches), otherwise Low |

A few rules apply on top of that:

- **Several candidates means you choose.** If two or more files fit about equally well, the track is marked "pick a file" instead of guessing. Up to five candidates are shown. A file in a folder with the same name as the old one wins a tie.
- **Changed numbers stay Low.** If a number in the old name is missing from the new one ("v1" became "v2", "Part 1" became "Part 2"), it could be a different version, so it is never ticked automatically.
- **WAV and AIFF need similar names.** Uncompressed files of the same length have the same size, so for those, an identical size only counts if the names are at least 60% similar.
- **Why size and not track length?** File size comes free with the folder scan and is exact to the byte. Track length would mean opening every file, and Rekordbox only stores it to the second, so it can't tell tracks apart as well. Size has one catch: Rekordbox doesn't update it when you edit tags or artwork, so small differences are expected. When the size differs by 5% or more, the file may be a different encode or version, and Relinkbox tells you to check the cue points.

Folders that can't be read are skipped and listed in the log.

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
- [Inter Display](https://github.com/rsms/inter) (SIL Open Font License 1.1) — the interface typeface. Regular and Bold are in `fonts/`, and the license is [OFL.txt](OFL.txt)

In the zip version the Qt libraries are separate files in the `Relinkbox` folder, so you can replace them with your own build. This project is not affiliated with AlphaTheta or Pioneer DJ. Rekordbox is their trademark.
