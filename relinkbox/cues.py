"""Find cue points that sit off the beat grid by a shared amount, and snap them back.

Local cue points live only in the djmdCue table of master.db; the cue sections of the
local analysis files are empty. The analysis files are only read here, for the beat
grid and the waveform. Only the database is ever written.
"""

import logging
import math
import os
import statistics
from dataclasses import dataclass, field

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


class Verdict:
    ON_GRID = "On grid"
    CUES_WRONG = "Cues off grid"
    GRID_WRONG = "Grid looks off"
    UNCLEAR = "Check manually"
    NO_GRID = "No beat grid"


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

    @property
    def label(self):
        if self.kind == 0:
            return "Memory"
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
    verdict: str = Verdict.ON_GRID
    reason: str = ""
    offset: float = None  # shared cue-to-beat distance in ms, negative = cues early
    cause: str = ""
    hits_offset: float = None  # waveform hits relative to the grid, ms
    offsets: dict = field(default_factory=dict)  # cue id -> distance to nearest beat
    proposed: dict = field(default_factory=dict)  # cue id -> (new_in_ms, new_out_ms)
    dat_path: str = None
    ext_path: str = None

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
        DjmdCue.Comment, DjmdCue.InMpegAbs, DjmdCue.InMpegFrame,
    )
    for cue_id, content_id, kind, in_ms, out_ms, comment, mpeg_abs, mpeg_frame in query:
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
        from pyrekordbox.db6.tables import DjmdContent

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
                cues=sorted(cues_by_track[str(content.ID)], key=lambda c: c.in_ms),
            )
            dat, ext = anlz_paths(share, content.AnalysisDataPath)
            report.dat_path = str(dat) if dat else None
            report.ext_path = str(ext) if ext else None
            try:
                grid = read_beat_grid(dat) if dat else None
            except Exception as e:
                log.warning("Could not read the beat grid of %s: %s", report.path, e)
                grid = None

            def hits(grid=grid, ext=ext, path=report.path):
                if not ext:
                    return None
                try:
                    return onset_offset(grid, read_waveform(ext))
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
