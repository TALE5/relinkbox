# Cue Manager test branch

This is `cue-grid-and-hot-cues`. It is the current app, plus a Cue Manager that can move a beat grid, edit hot cues, and remove a track from the library. It is here so people can try it. It is not finished, and it is not the download on the releases page.

Rekordbox has to be closed before **Apply**. That save makes one backup first, in `Relinkbox backups` next to `master.db`. **Restore a backup** on the main window puts it back. Try it on a library you can stand to restore.

There is no exe for this branch. From a checkout:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -e .
python -m relinkbox
```

## What you can try

Edits stay on screen until **Apply**. A track with unsaved work has an orange dot. **Reset** throws all of that away. Closing the window with edits still open asks you to save or discard them.

- **Snap to grid** moves the ticked cues onto the beats. **Snap to cues** moves the beat grid so the beats land on the cues. Both only stage the change, so you can look at it first.
- On the open track, **−10 / −1 / +1 / +10** nudge the grid. Hold one and it starts repeating after 250 ms. **Match cues** previews the shared offset. **Reset** beside those buttons puts that track's grid back.
- An empty hot-cue pad sets that letter on the nearest beat. Right-click a pad to delete it. **Match grid** snaps that track's hot cues onto the nearest beats.
- **The cues are right** and **The grid is right** stick across a new scan. Click the same button again to undo the choice.
- Ctrl+Z undoes the last staged edit. Ctrl+Y redoes it. The same buttons sit to the left of **Snap to grid** and are greyed out when there is nothing to do.
- Right-click one track for **Snap to grid**, **Snap to cues**, or **Delete**. Those apply to that track only. Double-click a row to tick or untick it.
- **Delete** takes the track off the list immediately. **Apply** removes it from Rekordbox. The audio file stays on disk.

## Known issues

These are the ones already found. They are left as-is on purpose.

1. **The playhead can stick while the audio keeps going.** Middle-dragging the waveform of a playing track, especially past the start or end of a zoomed view, has frozen the line until you pause and press play. Play then jumps back to where the line froze and drops whatever played in between. Scrubbing has been the flakiest part of this window.

2. **Nudging the grid earlier throws beats away.** Any beat that would land before 0:00 is removed. Those beats are not added at the other end, and the 1–2–3–4 positions on the beats that remain are not renumbered. A large nudge backward can leave the downbeat on the wrong beat of the bar. A nudge that would push a beat past the end of the time field is refused.

3. **A grid write can fail after the cues are already saved.** Apply writes the database first, then the `.DAT`. If the grid file cannot be updated, the cue changes from that save are already in the library and the grid is not. The backup from the start of that Apply is the way back. Only the local analysis `.DAT` is rewritten. USB exports are not touched. Re-analyzing the track in Rekordbox replaces a nudged grid.

4. **A new hot cue always lands on a beat.** There is no way to drop one off the grid. Memory cues cannot be added or deleted here. Loops move when you snap, but you cannot create one. VBR MP3 cues that store a byte position are left alone, and the save says so.

5. **Removing a track was checked against one real delete.** That was Rrose — Purge, which was not in a playlist. Apply removes the library row, its cues, playlist, history, tag, sampler, and related-track links, the mixer row, the analysis files (`.DAT`, `.EXT`, `.2EX`), and the artwork. The album goes too if that was its only track. The hot-cue bank list blob is not rewritten. A track that lives in more places than that one did may not match what Rekordbox itself removes. Restore the backup if the library looks wrong afterward.

6. **Manual verdicts live in Relinkbox's settings on this PC**, not in the Rekordbox database. Marking **The grid is right** while you are filtered to "Grid looks off" drops that track out of the list, and the player keeps showing it. That split was left alone.

7. **Snap and Match on the same track, before Apply, has been wrong once.** Setting a cue on a beat and then snapping the grid used to drag that new cue off the beat. Snapping cues onto the grid and then pressing **Match cues** used to jump the grid back to where the cues used to sit. Both were adjusted. Worth a look if you do both before saving.

8. **The player row is still cramped.** The grid buttons share a row with the hot-cue pads. On a narrower window they were sitting on top of the pads, with only +10 visible. They now shift aside when the row is tight. It was not signed off. Hot-cue letters are all black, including on dark pads, so some of them are hard to read.

9. **Ticking every row under All tracks used to lock the window.** The list was being recounted once per row. That recount is once per change now. A full library can still feel heavy.

10. **Double-click used to miss unless the pointer moved between clicks.** A still double-click now toggles the checkbox. If it misses, use the box.
