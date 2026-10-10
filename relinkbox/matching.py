import os
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz, process

from relinkbox.rekordbox import is_local_file_path
from relinkbox.scan import normalize_path

FUZZY_CUTOFF = 85
AMBIGUOUS_MARGIN = 2
MAX_CANDIDATES = 5
RENAME_MIN_SCORE = 60
SIZE_NOTE_THRESHOLD = 0.05
# Uncompressed audio size depends only on duration, so equal sizes say little on their own.
UNCOMPRESSED_EXTENSIONS = (".wav", ".wave", ".aif", ".aiff")


class Confidence(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class Method(str, Enum):
    SAME_NAME_SIZE = "Same name and size"
    SAME_NAME = "Same name, different size"
    RENAMED_SAME_SIZE = "Renamed, same size"
    TYPE_CHANGED = "Same name, different file type"
    SIMILAR_NAME = "Similar name"
    FOLDER_MOVED = "Folder moved"


@dataclass
class Candidate:
    path: str
    size: int
    score: float = 100.0


@dataclass
class Match:
    track: object
    method: Method
    confidence: Confidence
    candidates: list
    notes: list = field(default_factory=list)
    chosen: str = None

    def __post_init__(self):
        if self.chosen is None and len(self.candidates) == 1:
            self.chosen = self.candidates[0].path

    @property
    def ambiguous(self):
        return len(self.candidates) > 1

    @property
    def new_path(self):
        return self.chosen

    @property
    def selected_by_default(self):
        return not self.ambiguous and self.confidence in (Confidence.HIGH, Confidence.MEDIUM)


@dataclass
class MatchPlan:
    matches: list = field(default_factory=list)
    missing: list = field(default_factory=list)
    total_tracks: int = 0
    ok_tracks: int = 0
    non_file_tracks: int = 0
    files_scanned: int = 0
    offline_drives: list = field(default_factory=list)
    scan_errors: list = field(default_factory=list)

    @property
    def missing_total(self):
        return len(self.matches) + len(self.missing)


def track_filename(path):
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def parent_name(path):
    parts = path.replace("\\", "/").rsplit("/", 2)
    return parts[-2].lower() if len(parts) >= 2 else ""


def drive_of(path):
    drive = os.path.splitdrive(path)[0]
    if not drive and len(path) > 1 and path[1] == ":":
        drive = path[:2]
    return drive.upper()


def drive_connected(drive):
    return not drive or os.path.exists(drive + os.sep)


def _prefer_same_parent(track, entries):
    parent = parent_name(track.path)
    same_parent = [e for e in entries if parent_name(e.path) == parent]
    return same_parent or entries


def _size_note(track, entry):
    """Small differences come from edited tags or artwork; only flag likely re-encodes."""
    if not track.size or not entry.size:
        return None
    change = (entry.size - track.size) / track.size
    if abs(change) < SIZE_NOTE_THRESHOLD:
        return None
    direction = "larger" if change > 0 else "smaller"
    return (
        f"File is {abs(change):.0%} {direction} than when it was added to Rekordbox. It may be a "
        "different version or encode, so check the cue points."
    )


class Matcher:
    def __init__(self, index):
        self.index = index
        self._stems = [entry.stem for entry in index.files]

    def match(self, track):
        name = track_filename(track.path).lower()
        stem, ext = os.path.splitext(name)

        same_name = self.index.by_name.get(name, [])
        if same_name:
            return self._match_same_name(track, same_name)

        renamed = self._match_renamed(track, stem, ext)
        if renamed:
            return renamed

        retyped = [e for e in self.index.by_stem.get(stem, []) if e.ext != ext]
        if retyped:
            retyped = _prefer_same_parent(track, retyped)
            notes = [
                f"File type changed from {ext or '(none)'} to "
                f"{', '.join(sorted({e.ext for e in retyped}))}. Cue points and beat grid "
                "may not line up, so re-analyze the track in Rekordbox."
            ]
            return Match(
                track,
                Method.TYPE_CHANGED,
                Confidence.LOW,
                [Candidate(e.path, e.size) for e in retyped[:MAX_CANDIDATES]],
                notes,
            )

        return self._match_similar(track, stem, ext)

    def _match_same_name(self, track, entries):
        sized = [e for e in entries if track.size and e.size == track.size]
        if sized:
            chosen = _prefer_same_parent(track, sized)
            return Match(
                track,
                Method.SAME_NAME_SIZE,
                Confidence.HIGH,
                [Candidate(e.path, e.size) for e in chosen[:MAX_CANDIDATES]],
            )
        chosen = _prefer_same_parent(track, entries)
        notes = []
        if len(chosen) == 1:
            note = _size_note(track, chosen[0])
            if note:
                notes.append(note)
        return Match(
            track,
            Method.SAME_NAME,
            Confidence.MEDIUM,
            [Candidate(e.path, e.size) for e in chosen[:MAX_CANDIDATES]],
            notes,
        )

    def _match_renamed(self, track, stem, ext):
        if not track.size:
            return None
        same_size = [e for e in self.index.by_size.get(track.size, []) if e.ext == ext]
        if not same_size:
            return None
        scored = sorted(
            (Candidate(e.path, e.size, fuzz.ratio(stem, e.stem)) for e in same_size),
            key=lambda c: c.score,
            reverse=True,
        )
        if ext in UNCOMPRESSED_EXTENSIONS:
            scored = [c for c in scored if c.score >= RENAME_MIN_SCORE]
            if not scored:
                return None
        best = scored[0]
        if len(scored) > 1 and best.score - scored[1].score < 10:
            return Match(
                track,
                Method.RENAMED_SAME_SIZE,
                Confidence.LOW,
                scored[:MAX_CANDIDATES],
                ["Several files have exactly the same size. Pick the right one."],
            )
        confidence = Confidence.MEDIUM if best.score >= RENAME_MIN_SCORE else Confidence.LOW
        notes = [f"Filename changed. Names are {best.score:.0f}% similar; file size is identical."]
        return Match(track, Method.RENAMED_SAME_SIZE, confidence, [best], notes)

    def _match_similar(self, track, stem, ext):
        if not self._stems:
            return None
        results = process.extract(
            stem, self._stems, scorer=fuzz.ratio, score_cutoff=FUZZY_CUTOFF, limit=MAX_CANDIDATES
        )
        if not results:
            return None
        candidates = [
            Candidate(self.index.files[i].path, self.index.files[i].size, score)
            for _choice, score, i in results
        ]
        best = candidates[0]
        close = [c for c in candidates if best.score - c.score < AMBIGUOUS_MARGIN]
        if len(close) > 1:
            return Match(
                track,
                Method.SIMILAR_NAME,
                Confidence.LOW,
                close,
                ["Several files have almost the same name. Pick the right one."],
            )
        notes = [f"Names are {best.score:.0f}% similar."]
        confidence = Confidence.LOW
        if track.size and best.size == track.size:
            confidence = Confidence.MEDIUM
            notes.append("File size is identical.")
        if os.path.splitext(best.path)[1].lower() != ext:
            notes.append("File type is different. Re-analyze the track in Rekordbox.")
        return Match(track, Method.SIMILAR_NAME, confidence, [best], notes)


def split_tracks(tracks):
    """Return (missing, ok_count, non_file_count)."""
    missing = []
    ok = 0
    non_file = 0
    for track in tracks:
        if not is_local_file_path(track.path):
            non_file += 1
        elif os.path.exists(track.path):
            ok += 1
        else:
            missing.append(track)
    return missing, ok, non_file


def _annotate(plan, tracks):
    known_paths = {normalize_path(t.path) for t in tracks if is_local_file_path(t.path)}
    targets = Counter(normalize_path(m.new_path) for m in plan.matches if m.new_path)
    offline = set()
    for match in plan.matches:
        drive = drive_of(match.track.path)
        if drive and not drive_connected(drive):
            offline.add(drive)
            match.notes.append(
                f"Drive {drive} is not connected. If you only unplugged it, don't relink this track."
            )
        if not match.new_path:
            continue
        target = normalize_path(match.new_path)
        if target in known_paths:
            match.notes.append(
                "This file is already in your library as another track. Relinking creates a duplicate."
            )
        if targets[target] > 1:
            match.notes.append(f"Also proposed for {targets[target] - 1} other track(s).")
    for track in plan.missing:
        drive = drive_of(track.path)
        if drive and not drive_connected(drive):
            offline.add(drive)
    plan.offline_drives = sorted(offline)


def build_plan(tracks, index, progress=None):
    missing, ok, non_file = split_tracks(tracks)
    plan = MatchPlan(
        total_tracks=len(tracks),
        ok_tracks=ok,
        non_file_tracks=non_file,
        files_scanned=len(index.files),
        scan_errors=list(index.errors),
    )
    matcher = Matcher(index)
    for i, track in enumerate(missing):
        if progress:
            progress(i, len(missing))
        match = matcher.match(track)
        if match:
            plan.matches.append(match)
        else:
            plan.missing.append(track)
    _annotate(plan, tracks)
    return plan


def _strip_prefix(path, prefix):
    norm_path = path.replace("\\", "/")
    norm_prefix = prefix.replace("\\", "/").rstrip("/")
    if os.path.normcase(norm_path).startswith(os.path.normcase(norm_prefix + "/")):
        return norm_path[len(norm_prefix) + 1 :]
    return None


def build_folder_move_plan(tracks, old_prefix, new_prefix):
    missing, ok, non_file = split_tracks(tracks)
    plan = MatchPlan(total_tracks=len(tracks), ok_tracks=ok, non_file_tracks=non_file)
    for track in missing:
        rest = _strip_prefix(track.path, old_prefix)
        if rest is None:
            continue
        new_path = os.path.join(new_prefix, *rest.split("/"))
        if not os.path.isfile(new_path):
            plan.missing.append(track)
            continue
        size = os.path.getsize(new_path)
        entry_notes = []
        note = _size_note(track, Candidate(new_path, size))
        if note:
            entry_notes.append(note)
        plan.matches.append(
            Match(
                track,
                Method.FOLDER_MOVED,
                Confidence.HIGH,
                [Candidate(new_path, size)],
                entry_notes,
            )
        )
    plan.files_scanned = len(plan.matches)
    _annotate(plan, tracks)
    return plan


def suggest_moved_prefix(missing_tracks):
    """Deepest folder that holds most of the missing tracks."""
    if not missing_tracks:
        return None
    counts = Counter()
    for track in missing_tracks:
        parts = track.path.replace("\\", "/").split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            counts["/".join(parts[:depth])] += 1
    needed = len(missing_tracks) // 2 + 1
    best = None
    for folder, count in counts.items():
        if count < needed or not folder:
            continue
        depth = folder.count("/")
        if best is None or depth > best[1]:
            best = (folder, depth, count)
    if not best:
        return None
    folder = best[0]
    if folder.endswith(":"):
        folder += "/"
    return folder, best[2]
