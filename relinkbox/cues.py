"""Find cue points that sit off the beat grid by a shared amount, and line the two up.

Local cue points live only in the djmdCue table of master.db; the cue sections of the
local analysis files are empty. Snapping cues writes that table. Moving the beat grid
writes the beat times in the local .DAT file. The waveform is only ever read.
"""

import logging
import math
import os
import statistics
import uuid
from pathlib import Path
from dataclasses import dataclass, field, replace

from relinkbox.analysis import anlz_paths, onset_offset, read_beat_grid, read_waveform
from relinkbox.backup import create_backup, share_dir
from relinkbox.rekordbox import close_database, ensure_rekordbox_closed, open_database

log = logging.getLogger(__name__)

ON_GRID_MS = 2
SHARED_TOLERANCE_MS = 3
MIN_SHARED_CUES = 3
DRIFT_TOLERANCE_MS = 3
MAX_UNKNOWN_SHIFT_MS = 80
MP3_OFFSET_SAMPLES = 2257  # encoder delay plus one MP3 frame
CAUSE_TOLERANCE_MS = 1.5
WAVEFORM_AGREE_MS = 10
MIN_GRID_BEATS = 8

# djmdCue.Kind: 0 is a memory cue, hot cues skip 4.
HOT_CUE_LETTERS = {1: "A", 2: "B", 3: "C", 5: "D", 6: "E", 7: "F", 8: "G", 9: "H"}
# ColorTableIndex values that match the pad colours drawn in the player.
HOT_CUE_COLOR_INDEX = {1: 43, 2: 36, 3: 23, 5: 5, 6: 57, 7: 49, 8: 9, 9: 33}


class Verdict:
    ON_GRID = "On grid"
    CUES_WRONG = "Cues off grid"
    GRID_WRONG = "Grid looks off"
    UNCLEAR = "Check manually"
    NO_GRID = "No beat grid"


MANUAL_VERDICTS = (Verdict.CUES_WRONG, Verdict.GRID_WRONG)


def frames(ms):
    """Rekordbox frames are 1/150 s."""
    return math.floor(ms * 150 / 1000)


@dataclass
class CueInfo:
    id: str
    kind: int
    in_ms: int
    out_ms: int = -1
    comment: str = ""
    mpeg: bool = False
    color: int = -1  # memory cue Color 1-8, or -1
    color_index: int = 0  # hot cue ColorTableIndex
    copies: int = 1

    @property
    def label(self):
        if self.kind == 0:
            return "Memory" if self.copies == 1 else f"Memory ×{self.copies}"
        return HOT_CUE_LETTERS.get(self.kind, f"Hot cue {self.kind}")

    @property
    def is_loop(self):
        return self.out_ms is not None and self.out_ms > 0


@dataclass
class TrackCueReport:
    track_id: str
    title: str
    artist: str
    path: str
    sample_rate: int
    cues: list
    bit_rate: int = 0
    length_sec: int = 0
    genre: str = ""
    verdict: str = Verdict.ON_GRID
    reason: str = ""
    offset: float = None  # shared cue-to-beat distance in ms, negative = cues early
    cause: str = ""
    hits_offset: float = None  # waveform hits relative to the grid, ms
    offsets: dict = field(default_factory=dict)  # cue id -> distance to nearest beat
    proposed: dict = field(default_factory=dict)  # cue id -> (new_in_ms, new_out_ms)
    dat_path: str = None
    ext_path: str = None
    twoex_path: str = None

    @property
    def label(self):
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or os.path.basename(self.path)

    @property
    def file_type(self):
        return os.path.splitext(self.path)[1].lower().lstrip(".")

    @property
    def can_snap(self):
        return bool(self.proposed)

    @property
    def selected_by_default(self):
        return self.verdict == Verdict.CUES_WRONG and bool(self.proposed)


def display_cues(cues):
    """One row per hot cue, and one memory cue per timestamp (Rekordbox often stores copies)."""
    shown = []
    memory = {}
    for cue in cues:
        if cue.kind == 0:
            existing = memory.get(cue.in_ms)
            if existing:
                existing.copies += 1
                continue
            memory[cue.in_ms] = cue
            cue.copies = 1
        shown.append(cue)
    return shown


def mp3_offset_ms(sample_rate):
    return -MP3_OFFSET_SAMPLES / sample_rate * 1000 if sample_rate else None


def analyse(report, grid, hits_offset_fn):
    """Fill in verdict, offset, cause and proposed moves for one track.

    hits_offset_fn() returns where the waveform's hits sit relative to the grid (ms), or None.
    It is only called when the cues share an offset, because reading the waveform is slow.
    """
    if grid is None or len(grid) < MIN_GRID_BEATS:
        report.verdict, report.reason = Verdict.NO_GRID, "The track has no beat grid to compare against."
        return report

    for cue in report.cues:
        report.offsets[cue.id] = cue.in_ms - grid.times[grid.nearest(cue.in_ms)]
    off = [c for c in report.cues if abs(report.offsets[c.id]) > ON_GRID_MS]
    if not off:
        report.verdict, report.reason = Verdict.ON_GRID, ""
        return report

    median = statistics.median(report.offsets[c.id] for c in off)
    shared = [c for c in off if abs(report.offsets[c.id] - median) <= SHARED_TOLERANCE_MS and not c.mpeg]
    report.offset = round(median, 1)
    left_alone = len(off) - len(shared)

    if len(shared) < MIN_SHARED_CUES or len({c.in_ms for c in shared}) < 2:
        report.verdict = Verdict.UNCLEAR
        report.reason = "Too few cues share an offset to tell a shift from cues placed off the grid on purpose."
        return report

    ordered = sorted(shared, key=lambda c: c.in_ms)
    third = max(1, len(ordered) // 3)
    early = statistics.median(report.offsets[c.id] for c in ordered[:third])
    late = statistics.median(report.offsets[c.id] for c in ordered[-third:])
    if abs(late - early) > DRIFT_TOLERANCE_MS:
        report.verdict = Verdict.UNCLEAR
        report.reason = f"The offset changes from {early:+.0f} ms to {late:+.0f} ms across the track, so the BPM may differ."
        return report

    expected = mp3_offset_ms(report.sample_rate)
    if report.file_type == "mp3" and expected and abs(median - expected) <= CAUSE_TOLERANCE_MS:
        report.cause = "MP3 encoder offset"

    for cue in shared:
        target = grid.times[grid.nearest(cue.in_ms)]
        new_in = int(round(target))
        moved = new_in - cue.in_ms
        report.proposed[cue.id] = (new_in, cue.out_ms + moved if cue.is_loop else cue.out_ms)

    notes = []
    if left_alone:
        notes.append(f"{left_alone} other off-grid cue(s) are left alone.")

    if not report.cause:
        beat = grid.beat_length(statistics.median(c.in_ms for c in shared))
        limit = min(MAX_UNKNOWN_SHIFT_MS, beat / 4)
        if abs(median) > limit:
            report.verdict = Verdict.UNCLEAR
            report.reason = " ".join(
                [f"A shift of {abs(median):.0f} ms is too large to be sure (limit {limit:.0f} ms at this tempo)."] + notes
            )
            return report

    hits = hits_offset_fn()
    report.hits_offset = None if hits is None else round(hits, 1)
    direction = "early" if median < 0 else "late"
    summary = f"{len(shared)} cue(s) are {abs(median):.0f} ms {direction}."
    if hits is None:
        if report.cause:
            report.verdict = Verdict.CUES_WRONG
            report.reason = " ".join([summary, "No waveform to confirm, but the offset matches the MP3 encoder delay."] + notes)
        else:
            report.verdict = Verdict.UNCLEAR
            report.reason = " ".join([summary, "No waveform to confirm which one is right."] + notes)
    elif abs(hits) <= WAVEFORM_AGREE_MS:
        report.verdict = Verdict.CUES_WRONG
        report.reason = " ".join([summary, "The audio lines up with the grid."] + notes)
    elif abs(hits - median) <= WAVEFORM_AGREE_MS:
        report.verdict = Verdict.GRID_WRONG
        report.reason = " ".join([summary, "The audio lines up with the cues, so the grid may be off."] + notes)
    else:
        report.verdict = Verdict.UNCLEAR
        report.reason = " ".join([summary, "Neither the grid nor the cues line up clearly with the audio."] + notes)
    return report


def _report(progress, percent, text):
    if progress:
        progress(int(percent), text)


def _cue_rows(db):
    from pyrekordbox.db6.tables import DjmdCue

    rows = {}
    query = db.session.query(
        DjmdCue.ID, DjmdCue.ContentID, DjmdCue.Kind, DjmdCue.InMsec, DjmdCue.OutMsec,
        DjmdCue.Comment, DjmdCue.InMpegAbs, DjmdCue.InMpegFrame, DjmdCue.Color, DjmdCue.ColorTableIndex,
    )
    for cue_id, content_id, kind, in_ms, out_ms, comment, mpeg_abs, mpeg_frame, color, color_index in query:
        if in_ms is None or content_id is None:
            continue
        rows.setdefault(str(content_id), []).append(
            CueInfo(
                id=str(cue_id),
                kind=kind or 0,
                in_ms=in_ms,
                out_ms=out_ms if out_ms is not None else -1,
                comment=comment or "",
                mpeg=bool(mpeg_abs or mpeg_frame),
                color=-1 if color is None else color,
                color_index=color_index or 0,
            )
        )
    return rows


def scan_cues(db_path, progress=None):
    """Read-only: one report per track that has cue points."""
    _report(progress, 2, "Opening the Rekordbox database...")
    share = share_dir(db_path)
    db = open_database(db_path)
    try:
        _report(progress, 5, "Reading cue points...")
        cues_by_track = _cue_rows(db)
        from pyrekordbox.db6.tables import DjmdContent, DjmdGenre

        try:
            genre_names = {str(row.ID): row.Name or "" for row in db.session.query(DjmdGenre).all()}
        except Exception:
            genre_names = {}
        contents = db.session.query(DjmdContent).filter(DjmdContent.ID.in_(list(cues_by_track))).all()
        reports = []
        total = len(contents)
        for i, content in enumerate(contents):
            if i % 50 == 0:
                _report(progress, 8 + 90 * i / max(total, 1), f"Checking cue points ({i:,} of {total:,})...")
            try:
                artist = content.ArtistName or ""
            except Exception:
                artist = ""
            report = TrackCueReport(
                track_id=str(content.ID),
                title=content.Title or "",
                artist=artist,
                path=content.FolderPath or "",
                sample_rate=content.SampleRate or 0,
                bit_rate=int(content.BitRate or 0),
                length_sec=int(content.Length or 0),
                genre=genre_names.get(str(content.GenreID), "") if content.GenreID else "",
                cues=sorted(cues_by_track[str(content.ID)], key=lambda c: c.in_ms),
            )
            dat, ext, twoex = anlz_paths(share, content.AnalysisDataPath)
            report.dat_path = str(dat) if dat else None
            report.ext_path = str(ext) if ext else None
            report.twoex_path = str(twoex) if twoex else None
            try:
                grid = read_beat_grid(dat) if dat else None
            except Exception as e:
                log.warning("Could not read the beat grid of %s: %s", report.path, e)
                grid = None

            def hits(grid=grid, ext=ext, twoex=twoex, path=report.path):
                if not ext and not twoex:
                    return None
                try:
                    return onset_offset(grid, read_waveform(ext, twoex))
                except Exception as e:
                    log.warning("Could not read the waveform of %s: %s", path, e)
                    return None

            reports.append(analyse(report, grid, hits))
    finally:
        close_database(db)
    _report(progress, 100, "Done")
    counts = {}
    for r in reports:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    log.info("Cue scan: %d tracks with cues, %s", len(reports), counts)
    return reports


@dataclass
class SnapResult:
    applied: list = field(default_factory=list)  # reports that were changed
    moved_cues: int = 0
    skipped: list = field(default_factory=list)  # (report, reason)
    warnings: list = field(default_factory=list)
    backup: object = None


def apply_snaps(db_path, reports, progress=None):
    """Move the proposed cues of each report onto the grid. Backs up the database first."""
    from pyrekordbox.db6.tables import DjmdCue, DjmdSongHotCueBanklist

    ensure_rekordbox_closed()
    _report(progress, 2, "Backing up the database...")
    backup = create_backup(db_path, f"Before snapping cues on {len(reports)} track(s)")
    result = SnapResult(backup=backup)
    expected = {}

    db = open_database(db_path)
    try:
        for i, report in enumerate(reports):
            _report(progress, 10 + 75 * i / max(len(reports), 1), f"Snapping cues ({i:,} of {len(reports):,})...")
            originals = {c.id: c for c in report.cues}
            moved = 0
            for cue_id, (new_in, new_out) in report.proposed.items():
                row = db.session.query(DjmdCue).filter(DjmdCue.ID == cue_id).one_or_none()
                original = originals[cue_id]
                if row is None or row.InMsec != original.in_ms or str(row.ContentID) != report.track_id:
                    result.warnings.append(f"{report.label}: cue {original.label} changed since the scan, left alone.")
                    continue
                if row.InMpegAbs or row.InMpegFrame:
                    result.warnings.append(f"{report.label}: cue {original.label} is in a VBR MP3, left alone.")
                    continue
                row.InMsec = new_in
                row.InFrame = frames(new_in)
                if original.is_loop:
                    row.OutMsec = new_out
                    row.OutFrame = frames(new_out)
                bank_rows = db.session.query(DjmdSongHotCueBanklist).filter(
                    DjmdSongHotCueBanklist.CueID == cue_id
                ).all()
                for bank in bank_rows:
                    if bank.InMsec == original.in_ms:
                        bank.InMsec = new_in
                        bank.InFrame = frames(new_in)
                        if original.is_loop and bank.OutMsec == original.out_ms:
                            bank.OutMsec = new_out
                            bank.OutFrame = frames(new_out)
                expected[cue_id] = new_in
                moved += 1
            if moved:
                result.applied.append(report)
                result.moved_cues += moved
            else:
                result.skipped.append((report, "No cues could be moved."))

        _report(progress, 88, "Saving changes to the database...")
        if expected:
            ensure_rekordbox_closed()
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Snapping cues failed, nothing was committed")
        raise
    finally:
        close_database(db)

    _report(progress, 94, "Verifying...")
    db = open_database(db_path)
    try:
        for cue_id, new_in in expected.items():
            row = db.session.query(DjmdCue).filter(DjmdCue.ID == cue_id).one_or_none()
            if row is None or row.InMsec != new_in:
                result.warnings.append(f"Cue {cue_id} was not saved as expected.")
    finally:
        close_database(db)

    lines = ["track_id,cue_id,old_in_ms,new_in_ms"]
    for report in result.applied:
        old = {c.id: c.in_ms for c in report.cues}
        lines += [f"{report.track_id},{cid},{old[cid]},{new}" for cid, (new, _o) in report.proposed.items() if cid in expected]
    backup.write_text("cue_changes.csv", "\n".join(lines) + "\n")
    log.info("Snapped %d cue(s) on %d track(s); backup at %s", result.moved_cues, len(result.applied), backup.path)
    _report(progress, 100, "Done")
    return result


def grid_delta_matching_cues(report, cues):
    """Shift that puts the original beat grid on these cues.

    The beats come from the scan. Once the cues have been moved onto those
    beats, the shift is zero, so matching the grid does not jump back to
    where the cues used to sit.
    """
    by_id = {str(cue.id): cue for cue in cues or []}
    samples = []
    for cue_id, (beat_in, _out) in (report.proposed or {}).items():
        cue = by_id.get(str(cue_id))
        if cue is None:
            continue
        samples.append(int(cue.in_ms) - int(beat_in))
    if samples:
        return int(round(statistics.median(samples)))
    if report.offset is None:
        return None
    return int(round(report.offset))


def snap_action(report, verdict):
    """Which snap applies under the verdict on screen.

    'grid' moves the cues onto the beat. 'cues' moves the beat onto the cues.
    """
    if verdict == Verdict.GRID_WRONG and report.offset is not None and report.dat_path:
        return "cues"
    if report.proposed and verdict != Verdict.GRID_WRONG:
        return "grid"
    return None


def ticked_by_default(report, verdict):
    action = snap_action(report, verdict)
    if action == "cues":
        return True
    return action == "grid" and verdict == Verdict.CUES_WRONG


def kept_overrides(overrides, reports):
    """Manual verdicts that still belong to a track in this scan."""
    present = {str(report.track_id) for report in reports}
    kept = {}
    for track_id, verdict in (overrides or {}).items():
        if str(track_id) in present and verdict in MANUAL_VERDICTS:
            kept[str(track_id)] = verdict
    return kept


def _cue_info(row):
    if row.InMsec is None or row.ContentID is None:
        return None
    return CueInfo(
        id=str(row.ID),
        kind=row.Kind or 0,
        in_ms=row.InMsec,
        out_ms=row.OutMsec if row.OutMsec is not None else -1,
        comment=row.Comment or "",
        mpeg=bool(row.InMpegAbs or row.InMpegFrame),
        color=-1 if row.Color is None else row.Color,
        color_index=row.ColorTableIndex or 0,
    )


def _analyse_report(report):
    try:
        grid = read_beat_grid(report.dat_path) if report.dat_path else None
    except Exception as e:
        log.warning("Could not read the beat grid of %s: %s", report.path, e)
        grid = None

    def hits(grid=grid, ext=report.ext_path, twoex=report.twoex_path, path=report.path):
        if not ext and not twoex:
            return None
        try:
            return onset_offset(grid, read_waveform(ext, twoex))
        except Exception as e:
            log.warning("Could not read the waveform of %s: %s", path, e)
            return None

    return analyse(report, grid, hits)


def try_reload_tracks(db_path, track_ids, progress=None):
    """reload_tracks, or an empty list when the re-read fails. The edit itself already landed."""
    try:
        return reload_tracks(db_path, track_ids, progress=progress)
    except Exception as e:
        log.warning("Could not re-read tracks: %s", e)
        return []


def reload_tracks(db_path, track_ids, progress=None):
    """Re-read cues and the beat grid for tracks that were just edited."""
    ids = [str(track_id) for track_id in track_ids]
    if not ids:
        return []
    share = share_dir(db_path)
    db = open_database(db_path)
    try:
        from pyrekordbox.db6.tables import DjmdContent, DjmdCue, DjmdGenre

        try:
            genre_names = {str(row.ID): row.Name or "" for row in db.session.query(DjmdGenre).all()}
        except Exception:
            genre_names = {}
        contents = db.session.query(DjmdContent).filter(DjmdContent.ID.in_(ids)).all()
        cue_rows = db.session.query(DjmdCue).filter(DjmdCue.ContentID.in_(ids)).all()
    finally:
        close_database(db)

    by_content = {}
    for row in cue_rows:
        info = _cue_info(row)
        if info:
            by_content.setdefault(str(row.ContentID), []).append(info)
    reports = []
    total = len(contents)
    for i, content in enumerate(contents):
        _report(progress, 100 * i / max(total, 1), "Reading the track...")
        try:
            artist = content.ArtistName or ""
        except Exception:
            artist = ""
        cues = sorted(by_content.get(str(content.ID), []), key=lambda cue: cue.in_ms)
        report = TrackCueReport(
            track_id=str(content.ID),
            title=content.Title or "",
            artist=artist,
            path=content.FolderPath or "",
            sample_rate=content.SampleRate or 0,
            bit_rate=int(content.BitRate or 0),
            length_sec=int(content.Length or 0),
            genre=genre_names.get(str(content.GenreID), "") if content.GenreID else "",
            cues=cues,
        )
        dat, ext, twoex = anlz_paths(share, content.AnalysisDataPath)
        report.dat_path = str(dat) if dat else None
        report.ext_path = str(ext) if ext else None
        report.twoex_path = str(twoex) if twoex else None
        reports.append(_analyse_report(report))
    return reports


@dataclass
class GridShiftResult:
    applied: list = field(default_factory=list)
    refreshed: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    backup: object = None


def apply_grid_shifts(db_path, reports, progress=None):
    """Move each track's beat grid by its shared cue offset. Backs up first."""
    from relinkbox.analysis import GridShiftError, shift_beat_grid

    ensure_rekordbox_closed()
    _report(progress, 2, "Backing up...")
    backup = create_backup(db_path, f"Before moving the beat grid on {len(reports)} track(s)")
    result = GridShiftResult(backup=backup)
    share = share_dir(db_path)
    lines = ["track_id,delta_ms"]
    for i, report in enumerate(reports):
        _report(progress, 10 + 70 * i / max(len(reports), 1), f"Moving beat grids ({i:,} of {len(reports):,})...")
        if report.offset is None or not report.dat_path:
            result.skipped.append((report, "No shared offset to move the grid by."))
            continue
        delta = int(round(report.offset))
        if delta == 0:
            result.skipped.append((report, "The grid already lines up with the cues."))
            continue
        try:
            backup.add_anlz(share, report.dat_path)
            shift_beat_grid(report.dat_path, delta)
        except (OSError, GridShiftError) as e:
            result.warnings.append(f"{report.label}: {e}")
            result.skipped.append((report, str(e)))
            continue
        result.applied.append(report)
        lines.append(f"{report.track_id},{delta}")
    backup.write_text("grid_changes.csv", "\n".join(lines) + "\n")
    if result.applied:
        _report(progress, 88, "Reading the tracks again...")
        try:
            result.refreshed = reload_tracks(db_path, [report.track_id for report in result.applied])
        except Exception as e:
            log.warning("Could not re-read tracks after moving the grid: %s", e)
            result.warnings.append(f"The grid was moved, but the list could not be refreshed ({e}).")
    log.info("Moved the beat grid on %d track(s); backup at %s", len(result.applied), backup.path)
    _report(progress, 100, "Done")
    return result


@dataclass
class EditResult:
    backup: object
    summary: str
    report: object = None
    warnings: list = field(default_factory=list)


def nudge_grid(db_path, track_id, dat_path, delta_ms, label="", progress=None):
    """Shift one track's beat grid by a chosen number of milliseconds."""
    from relinkbox.analysis import shift_beat_grid

    delta = int(round(delta_ms))
    if not dat_path:
        raise ValueError("This track has no beat grid file.")
    if delta == 0:
        raise ValueError("The grid has not been moved.")
    ensure_rekordbox_closed()
    _report(progress, 5, "Backing up...")
    name = label or track_id
    backup = create_backup(db_path, f"Before nudging the beat grid of {name}")
    backup.add_anlz(share_dir(db_path), dat_path)
    _report(progress, 40, "Moving the beat grid...")
    shift_beat_grid(dat_path, delta)
    backup.write_text("grid_changes.csv", f"track_id,delta_ms\n{track_id},{delta}\n")
    _report(progress, 75, "Reading the track again...")
    try:
        refreshed = reload_tracks(db_path, [track_id])
    except Exception as e:
        log.warning("Could not re-read %s after nudging the grid: %s", name, e)
        refreshed = []
    report = refreshed[0] if refreshed else None
    log.info("Nudged the beat grid of %s by %+d ms; backup at %s", name, delta, backup.path)
    _report(progress, 100, "Done")
    return EditResult(
        backup=backup,
        report=report,
        summary=f"Moved the beat grid by {delta:+d} ms.",
    )


def _hot_cue_rows(db, track_id, kind):
    from pyrekordbox.db6.tables import DjmdCue

    return (
        db.session.query(DjmdCue)
        .filter(DjmdCue.ContentID == str(track_id), DjmdCue.Kind == kind)
        .all()
    )


def _bank_ids(db, content):
    from pyrekordbox.db6.tables import DjmdHotCueBanklist, DjmdSongHotCueBanklist

    linked = (
        db.session.query(DjmdSongHotCueBanklist.HotCueBanklistID)
        .filter(DjmdSongHotCueBanklist.ContentID == str(content.ID))
        .distinct()
        .all()
    )
    ids = [row[0] for row in linked if row[0]]
    if ids:
        return ids
    roots = [row for row in db.session.query(DjmdHotCueBanklist).all() if not row.ParentID]
    if len(roots) == 1:
        return [roots[0].ID]
    return []


def _mirror_hot_cue(db, content, cue):
    from pyrekordbox.db6.tables import DjmdHotCueBanklist, DjmdSongHotCueBanklist

    for bank_id in _bank_ids(db, content):
        bank = db.session.query(DjmdHotCueBanklist).filter(DjmdHotCueBanklist.ID == str(bank_id)).one_or_none()
        already = (
            db.session.query(DjmdSongHotCueBanklist)
            .filter(
                DjmdSongHotCueBanklist.HotCueBanklistID == str(bank_id),
                DjmdSongHotCueBanklist.CueID == str(cue.ID),
            )
            .count()
        )
        if already:
            continue
        track_no = (
            db.session.query(DjmdSongHotCueBanklist)
            .filter(
                DjmdSongHotCueBanklist.HotCueBanklistID == str(bank_id),
                DjmdSongHotCueBanklist.ContentID == str(content.ID),
            )
            .count()
        )
        row = DjmdSongHotCueBanklist.create(
            ID=str(db.generate_unused_id(DjmdSongHotCueBanklist)),
            UUID=str(uuid.uuid4()),
            HotCueBanklistID=str(bank_id),
            HotCueBanklistUUID=None if bank is None else bank.UUID,
            ContentID=str(content.ID),
            TrackNo=track_no + 1,
            CueID=str(cue.ID),
            InMsec=cue.InMsec,
            InFrame=cue.InFrame,
            InMpegFrame=0,
            InMpegAbs=0,
            OutMsec=cue.OutMsec if cue.OutMsec is not None else -1,
            OutFrame=cue.OutFrame or 0,
            OutMpegFrame=0,
            OutMpegAbs=0,
            Color=-1 if cue.Color is None else cue.Color,
            ColorTableIndex=cue.ColorTableIndex or 0,
            ActiveLoop=0,
            Comment=cue.Comment or "",
            BeatLoopSize=0,
            CueMicrosec=0,
        )
        db.add(row)
        db.flush()


def _move_cue_time(db, row, in_ms):
    from pyrekordbox.db6.tables import DjmdSongHotCueBanklist

    length = None
    if row.OutMsec is not None and row.OutMsec > 0:
        length = row.OutMsec - (row.InMsec or 0)
    row.InMsec = in_ms
    row.InFrame = frames(in_ms)
    if length is not None:
        row.OutMsec = in_ms + length
        row.OutFrame = frames(row.OutMsec)
    for bank in db.session.query(DjmdSongHotCueBanklist).filter(DjmdSongHotCueBanklist.CueID == str(row.ID)).all():
        bank.InMsec = row.InMsec
        bank.InFrame = row.InFrame
        if length is not None and bank.OutMsec is not None and bank.OutMsec > 0:
            bank.OutMsec = row.OutMsec
            bank.OutFrame = row.OutFrame


def _edit_result(db_path, track_id, backup, summary):
    try:
        refreshed = reload_tracks(db_path, [track_id])
    except Exception as e:
        log.warning("Could not re-read track %s after editing a cue: %s", track_id, e)
        refreshed = []
    return EditResult(backup=backup, report=refreshed[0] if refreshed else None, summary=summary)


def draft_cues(cues, deleted=(), moved=None, added=()):
    """Cues after unsaved edits. moved maps a cue id to (in_ms, out_ms)."""
    gone = {str(cue_id) for cue_id in deleted}
    moved = {str(cue_id): times for cue_id, times in (moved or {}).items()}
    result = []
    for cue in cues:
        if str(cue.id) in gone:
            continue
        change = moved.get(str(cue.id))
        if change:
            new_in, new_out = change
            result.append(replace(cue, in_ms=int(new_in), out_ms=int(new_out)))
        else:
            result.append(cue)
    result.extend(added or [])
    result.sort(key=lambda cue: (cue.in_ms, cue.kind, str(cue.id)))
    return result


@dataclass
class TrackEdit:
    track_id: str
    label: str = ""
    dat_path: str = None
    grid_delta: int = 0
    moves: dict = field(default_factory=dict)  # cue id -> in_ms
    deletes: list = field(default_factory=list)
    adds: list = field(default_factory=list)  # (kind, in_ms)
    remove: bool = False

    def pending(self):
        return bool(self.remove or self.grid_delta or self.moves or self.deletes or self.adds)


@dataclass
class SessionResult:
    backup: object = None
    saved_ids: list = field(default_factory=list)
    removed_ids: list = field(default_factory=list)
    shifted_ids: list = field(default_factory=list)
    refreshed: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    summary: str = ""


def _insert_hot_cue(db, content, kind, in_ms):
    from pyrekordbox.db6.tables import DjmdCue

    cue = DjmdCue.create(
        ID=str(db.generate_unused_id(DjmdCue)),
        UUID=str(uuid.uuid4()),
        ContentID=str(content.ID),
        ContentUUID=content.UUID,
        Kind=kind,
        InMsec=in_ms,
        InFrame=frames(in_ms),
        InMpegFrame=0,
        InMpegAbs=0,
        OutMsec=-1,
        OutFrame=0,
        OutMpegFrame=0,
        OutMpegAbs=0,
        Color=-1,
        ColorTableIndex=HOT_CUE_COLOR_INDEX.get(kind, 43),
        ActiveLoop=0,
        Comment="",
        BeatLoopSize=0,
        CueMicrosec=0,
    )
    db.add(cue)
    db.flush()
    _mirror_hot_cue(db, content, cue)
    return cue


def _delete_cue_row(db, row):
    from pyrekordbox.db6.tables import DjmdSongHotCueBanklist

    if (row.Kind or 0) == 0:
        raise ValueError("Memory cues are left alone.")
    for bank in db.session.query(DjmdSongHotCueBanklist).filter(DjmdSongHotCueBanklist.CueID == str(row.ID)).all():
        db.delete(bank)
    db.delete(row)


def _apply_cue_edit(db, edit, warnings):
    from pyrekordbox.db6.tables import DjmdContent, DjmdCue

    content = db.session.query(DjmdContent).filter(DjmdContent.ID == str(edit.track_id)).one_or_none()
    if content is None:
        warnings.append(f"{edit.label or edit.track_id}: the track is no longer in the library.")
        return False
    for cue_id in edit.deletes:
        row = (
            db.session.query(DjmdCue)
            .filter(DjmdCue.ID == str(cue_id), DjmdCue.ContentID == str(content.ID))
            .one_or_none()
        )
        if row is None:
            warnings.append(f"{edit.label}: a hot cue was already gone.")
            continue
        try:
            _delete_cue_row(db, row)
        except ValueError as e:
            warnings.append(f"{edit.label}: {e}")
    for cue_id, new_in in edit.moves.items():
        row = (
            db.session.query(DjmdCue)
            .filter(DjmdCue.ID == str(cue_id), DjmdCue.ContentID == str(content.ID))
            .one_or_none()
        )
        if row is None:
            warnings.append(f"{edit.label}: a cue disappeared before it could be moved.")
            continue
        if row.InMpegAbs or row.InMpegFrame:
            warnings.append(f"{edit.label}: a VBR MP3 cue was left alone.")
            continue
        _move_cue_time(db, row, int(new_in))
    for kind, in_ms in edit.adds:
        if kind not in HOT_CUE_LETTERS:
            continue
        existing = _hot_cue_rows(db, content.ID, kind)
        if any(row.InMpegAbs or row.InMpegFrame for row in existing):
            warnings.append(f"{edit.label}: hot cue {HOT_CUE_LETTERS[kind]} is a VBR MP3 cue and was left alone.")
            continue
        if existing:
            for row in existing:
                _move_cue_time(db, row, int(in_ms))
        else:
            _insert_hot_cue(db, content, kind, int(in_ms))
    return True


# Rows Rekordbox drops with a track. The audio file itself is not one of them.
_TRACK_CHILDREN = (
    "DjmdSongHotCueBanklist",
    "DjmdCue",
    "DjmdSongPlaylist",
    "DjmdSongHistory",
    "DjmdSongMyTag",
    "DjmdSongSampler",
    "DjmdSongRelatedTracks",
    "DjmdSongTagList",
    "DjmdMixerParam",
    "DjmdActiveCensor",
    "ContentCue",
    "ContentFile",
    "ContentActiveCensor",
)


def _share_files(db, track_id, share):
    """Analysis and artwork paths Rekordbox stores for this track."""
    from pyrekordbox.db6.tables import ContentFile, DjmdContent

    found = []
    content = db.session.query(DjmdContent).filter(DjmdContent.ID == str(track_id)).one_or_none()
    for row in db.session.query(ContentFile).filter(ContentFile.ContentID == str(track_id)).all():
        if row.rb_local_path:
            found.append(row.rb_local_path)
    if content is not None:
        for stored in (content.AnalysisDataPath, content.ImagePath):
            if not stored:
                continue
            path = Path(share) / str(stored).strip("\\/")
            if path.is_file():
                found.append(str(path))
            if stored == content.AnalysisDataPath:
                for suffix in (".EXT", ".2EX"):
                    sibling = path.with_suffix(suffix)
                    if sibling.is_file():
                        found.append(str(sibling))
    unique = []
    seen = set()
    for path in found:
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _delete_library_track(db, track_id):
    """Remove one track and the library rows that belong to it. Leaves the audio file."""
    import pyrekordbox.db6.tables as tables
    from pyrekordbox.db6.tables import DjmdAlbum, DjmdContent

    content = db.session.query(DjmdContent).filter(DjmdContent.ID == str(track_id)).one_or_none()
    if content is None:
        return False
    album_id = content.AlbumID
    for name in _TRACK_CHILDREN:
        model = getattr(tables, name)
        for row in db.session.query(model).filter(model.ContentID == str(content.ID)).all():
            db.delete(row)
    db.delete(content)
    db.flush()
    if album_id and db.session.query(DjmdContent).filter(DjmdContent.AlbumID == str(album_id)).count() == 0:
        album = db.session.query(DjmdAlbum).filter(DjmdAlbum.ID == str(album_id)).one_or_none()
        if album is not None:
            db.delete(album)
    return True


def _remove_share_files(share, paths):
    """Delete analysis and artwork files under the Rekordbox share folder."""
    root = Path(share).resolve()
    parents = []
    for raw in paths:
        file = Path(raw)
        if not file.is_file():
            continue
        try:
            file.resolve().relative_to(root)
        except ValueError:
            continue
        file.unlink()
        parents.append(file.parent)
    for folder in parents:
        try:
            folder.resolve().relative_to(root)
        except ValueError:
            continue
        try:
            folder.rmdir()
        except OSError:
            pass


def apply_edits(db_path, edits, progress=None):
    """Write every staged cue, grid, and removal. One backup covers the whole save."""
    from relinkbox.analysis import GridShiftError, shift_beat_grid

    edits = [edit for edit in edits if edit.pending()]
    if not edits:
        raise ValueError("Nothing to save.")
    ensure_rekordbox_closed()
    _report(progress, 4, "Backing up...")
    backup = create_backup(db_path, f"Before saving cue changes on {len(edits)} track(s)")
    share = share_dir(db_path)
    for edit in edits:
        if edit.grid_delta and edit.dat_path and not edit.remove:
            backup.add_anlz(share, edit.dat_path)
    result = SessionResult(backup=backup)
    warnings = result.warnings
    share_files = {}
    committed = False
    db = open_database(db_path)
    try:
        for edit in edits:
            if not edit.remove:
                continue
            files = _share_files(db, edit.track_id, share)
            share_files[str(edit.track_id)] = files
            for path in files:
                backup.add_anlz(share, path)
        for i, edit in enumerate(edits):
            if edit.remove:
                _report(progress, 15 + 40 * i / max(len(edits), 1), f"Removing tracks ({i + 1:,} of {len(edits):,})...")
                if not _delete_library_track(db, edit.track_id):
                    warnings.append(f"{edit.label or edit.track_id}: the track is no longer in the library.")
                continue
            if not (edit.moves or edit.deletes or edit.adds):
                continue
            _report(progress, 15 + 40 * i / max(len(edits), 1), f"Saving cues ({i + 1:,} of {len(edits):,})...")
            _apply_cue_edit(db, edit, warnings)
        if any(edit.remove or edit.moves or edit.deletes or edit.adds for edit in edits):
            _report(progress, 60, "Saving...")
            ensure_rekordbox_closed()
            db.commit()
            committed = True
    except Exception:
        db.rollback()
        log.exception("Saving cue changes failed, nothing was committed")
        raise
    finally:
        close_database(db)

    if committed:
        for track_id, paths in share_files.items():
            try:
                _remove_share_files(share, paths)
            except OSError as e:
                warnings.append(f"{track_id}: {e}")
    for i, edit in enumerate(edits):
        if edit.remove or not edit.grid_delta or not edit.dat_path:
            continue
        _report(progress, 70 + 15 * i / max(len(edits), 1), "Moving beat grids...")
        try:
            shift_beat_grid(edit.dat_path, edit.grid_delta)
            result.shifted_ids.append(str(edit.track_id))
        except (OSError, GridShiftError) as e:
            warnings.append(f"{edit.label or edit.track_id}: {e}")
    result.saved_ids = [str(edit.track_id) for edit in edits]
    result.removed_ids = [str(edit.track_id) for edit in edits if edit.remove]
    reload_ids = [track_id for track_id in result.saved_ids if track_id not in result.removed_ids]
    _report(progress, 90, "Reading the tracks again...")
    try:
        if reload_ids:
            result.refreshed = reload_tracks(db_path, reload_ids)
    except Exception as e:
        log.warning("Could not re-read tracks after saving: %s", e)
        warnings.append(f"The changes were saved, but the list could not be refreshed ({e}).")
    if result.removed_ids and len(result.saved_ids) == len(result.removed_ids):
        result.summary = f"Removed {len(result.removed_ids):,} track(s) from the library."
    elif result.removed_ids:
        result.summary = (
            f"Saved changes on {len(result.saved_ids):,} track(s) "
            f"and removed {len(result.removed_ids):,} from the library."
        )
    else:
        result.summary = f"Saved changes on {len(result.saved_ids):,} track(s)."
    log.info("%s backup at %s", result.summary, backup.path)
    _report(progress, 100, "Done")
    return result


def set_hot_cue(db_path, track_id, kind, in_ms, label="", progress=None):
    """Create a hot cue, or move the one already on that pad, to in_ms."""
    from pyrekordbox.db6.tables import DjmdContent

    if kind not in HOT_CUE_LETTERS:
        raise ValueError("That is not a hot cue.")
    in_ms = max(0, int(in_ms))
    letter = HOT_CUE_LETTERS[kind]
    ensure_rekordbox_closed()
    _report(progress, 5, "Backing up...")
    backup = create_backup(db_path, f"Before setting hot cue {letter} on {label or track_id}")
    db = open_database(db_path)
    try:
        content = db.session.query(DjmdContent).filter(DjmdContent.ID == str(track_id)).one_or_none()
        if content is None:
            raise ValueError("That track is no longer in the library.")
        rows = _hot_cue_rows(db, content.ID, kind)
        if any(row.InMpegAbs or row.InMpegFrame for row in rows):
            raise ValueError(f"Hot cue {letter} is stored as a VBR MP3 position and was left alone.")
        if rows:
            for row in rows:
                _move_cue_time(db, row, in_ms)
            summary = f"Moved hot cue {letter}."
        else:
            _insert_hot_cue(db, content, kind, in_ms)
            summary = f"Set hot cue {letter}."
        _report(progress, 70, "Saving...")
        ensure_rekordbox_closed()
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Setting a hot cue failed, nothing was committed")
        raise
    finally:
        close_database(db)
    _report(progress, 85, "Reading the track again...")
    result = _edit_result(db_path, track_id, backup, summary)
    log.info("%s backup at %s", summary, backup.path)
    _report(progress, 100, "Done")
    return result


def delete_hot_cue(db_path, track_id, cue_id, label="", progress=None):
    """Remove one hot cue. Memory cues are refused."""
    from pyrekordbox.db6.tables import DjmdCue, DjmdSongHotCueBanklist

    ensure_rekordbox_closed()
    _report(progress, 5, "Backing up...")
    backup = create_backup(db_path, f"Before deleting a hot cue on {label or track_id}")
    db = open_database(db_path)
    try:
        row = (
            db.session.query(DjmdCue)
            .filter(DjmdCue.ID == str(cue_id), DjmdCue.ContentID == str(track_id))
            .one_or_none()
        )
        if row is None:
            raise ValueError("That hot cue is no longer there.")
        if (row.Kind or 0) == 0:
            raise ValueError("Memory cues are left alone.")
        letter = HOT_CUE_LETTERS.get(row.Kind, "hot cue")
        for bank in db.session.query(DjmdSongHotCueBanklist).filter(DjmdSongHotCueBanklist.CueID == str(row.ID)).all():
            db.delete(bank)
        db.delete(row)
        _report(progress, 70, "Saving...")
        ensure_rekordbox_closed()
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Deleting a hot cue failed, nothing was committed")
        raise
    finally:
        close_database(db)
    summary = f"Deleted hot cue {letter}."
    _report(progress, 85, "Reading the track again...")
    result = _edit_result(db_path, track_id, backup, summary)
    log.info("%s backup at %s", summary, backup.path)
    _report(progress, 100, "Done")
    return result
