import logging
import os
from dataclasses import dataclass, field

from relinkbox.backup import create_backup, share_dir
from relinkbox.matching import build_folder_move_plan, build_plan, split_tracks
from relinkbox.rekordbox import (
    close_database,
    ensure_rekordbox_closed,
    file_type_for,
    is_local_file_path,
    load_tracks,
    lost_tag_types,
    open_database,
    read_anlz_files,
)
from relinkbox.reports import changes_csv_text
from relinkbox.scan import iter_audio_files, normalize_path, scan_folders

log = logging.getLogger(__name__)


def _report(progress, percent, text):
    if progress:
        progress(int(percent), text)


def _read_tracks(db_path, progress):
    _report(progress, 2, "Opening the Rekordbox database...")
    db = open_database(db_path)
    try:
        _report(progress, 5, "Reading tracks...")
        return load_tracks(db)
    finally:
        close_database(db)


def scan_library(db_path, folders, progress=None):
    tracks = _read_tracks(db_path, progress)
    _report(progress, 10, "Scanning music folders...")
    index = scan_folders(folders)
    _report(progress, 40, f"Matching missing tracks against {len(index.files):,} files...")

    def match_progress(i, total):
        _report(progress, 40 + 58 * i / max(total, 1), f"Matching missing tracks ({i:,} of {total:,})...")

    plan = build_plan(tracks, index, match_progress)
    _report(progress, 100, "Done")
    log.info(
        "Scan: %d tracks, %d missing, %d matched, %d still missing, %d files scanned",
        plan.total_tracks,
        plan.missing_total,
        len(plan.matches),
        len(plan.missing),
        plan.files_scanned,
    )
    return plan


def missing_tracks(db_path, progress=None):
    tracks = _read_tracks(db_path, progress)
    missing, _ok, _non_file = split_tracks(tracks)
    _report(progress, 100, "Done")
    return missing


def scan_folder_move(db_path, old_prefix, new_prefix, progress=None):
    tracks = _read_tracks(db_path, progress)
    _report(progress, 50, "Checking moved files...")
    plan = build_folder_move_plan(tracks, old_prefix, new_prefix)
    _report(progress, 100, "Done")
    log.info("Folder move %s -> %s: %d matched, %d not found", old_prefix, new_prefix, len(plan.matches), len(plan.missing))
    return plan


@dataclass
class Change:
    track: object
    new_path: str
    method: str = ""
    old_path: str = ""


@dataclass
class ApplyResult:
    applied: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    backup: object = None


def _verify(db_path, expected):
    """Re-open the database and confirm each change was saved. expected: {id: (column, value)}."""
    problems = []
    db = open_database(db_path)
    try:
        for track_id, (column, value) in expected.items():
            content = db.get_content(ID=track_id)
            if content is None or getattr(content, column) != value:
                problems.append(f"Track {track_id}: {column} was not saved as expected.")
    finally:
        close_database(db)
    return problems


def apply_relinks(db_path, changes, progress=None):
    ensure_rekordbox_closed()
    _report(progress, 2, "Backing up the database...")
    backup = create_backup(db_path, f"Before relinking {len(changes)} track(s)")
    result = ApplyResult(backup=backup)
    share = share_dir(db_path)
    pending_anlz = []

    db = open_database(db_path)
    try:
        for i, change in enumerate(changes):
            _report(progress, 10 + 70 * i / max(len(changes), 1), f"Relinking ({i:,} of {len(changes):,})...")
            content = db.get_content(ID=change.track.id)
            if content is None:
                result.skipped.append((change.track, "Track is no longer in the library."))
                continue
            if content.FolderPath != change.track.path:
                result.skipped.append((change.track, "Track path changed since the scan."))
                continue
            if not os.path.isfile(change.new_path):
                result.skipped.append((change.track, "The new file no longer exists."))
                continue

            new_path = change.new_path.replace("\\", "/")
            try:
                anlz_files = read_anlz_files(db, content.ID)
            except Exception as e:
                anlz_files = {}
                result.warnings.append(f"{change.track.label}: could not read analysis files ({e}).")
            for anlz_path, anlz in anlz_files.items():
                try:
                    lost = lost_tag_types(anlz_path, anlz)
                except OSError as e:
                    lost = [f"unreadable: {e}"]
                if lost:
                    result.warnings.append(
                        f"{change.track.label}: analysis file {os.path.basename(anlz_path)} was left unchanged "
                        f"because it has sections Relinkbox can't rewrite ({', '.join(lost)})."
                    )
                    continue
                backup.add_anlz(share, anlz_path)
                anlz.set_path(new_path)
                pending_anlz.append((change.track, anlz_path, anlz))

            old_path = content.FolderPath
            content.FolderPath = new_path
            if content.OrgFolderPath == old_path:
                content.OrgFolderPath = new_path
            new_name = new_path.rsplit("/", 1)[-1]
            if content.FileNameL != new_name:
                content.FileNameL = new_name
            if os.path.splitext(old_path)[1].lower() != os.path.splitext(new_path)[1].lower():
                file_type = file_type_for(new_path)
                if file_type is not None and content.FileType != file_type:
                    content.FileType = file_type
            content.FileSize = os.path.getsize(change.new_path)
            change.old_path = old_path
            change.new_path = new_path
            result.applied.append(change)

        _report(progress, 82, "Saving changes to the database...")
        if result.applied:
            ensure_rekordbox_closed()
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Relink failed, nothing was committed")
        raise
    finally:
        close_database(db)

    _report(progress, 88, "Updating analysis files...")
    for track, anlz_path, anlz in pending_anlz:
        try:
            anlz.save(anlz_path)
        except Exception as e:
            result.warnings.append(f"{track.label}: could not update analysis file {anlz_path} ({e}).")

    backup.write_text("changes.csv", changes_csv_text(result.applied))

    _report(progress, 94, "Verifying...")
    result.warnings.extend(
        _verify(db_path, {c.track.id: ("FolderPath", c.new_path) for c in result.applied})
    )
    for warning in result.warnings:
        log.warning(warning)
    for track, reason in result.skipped:
        log.info("Skipped %s: %s", track.path, reason)
    log.info("Relinked %d track(s); backup at %s", len(result.applied), backup.path)
    _report(progress, 100, "Done")
    return result


def plan_display_names(db_path, progress=None):
    tracks = _read_tracks(db_path, progress)
    plan = []
    for track in tracks:
        if not is_local_file_path(track.path):
            continue
        actual = track.path.replace("\\", "/").rsplit("/", 1)[-1]
        if actual and track.display_name != actual:
            plan.append(Change(track=track, new_path=actual, method="Display name"))
    _report(progress, 100, "Done")
    return plan


def apply_display_names(db_path, changes, progress=None):
    ensure_rekordbox_closed()
    _report(progress, 2, "Backing up the database...")
    backup = create_backup(db_path, f"Before fixing {len(changes)} display name(s)")
    result = ApplyResult(backup=backup)

    db = open_database(db_path)
    try:
        for i, change in enumerate(changes):
            _report(progress, 10 + 75 * i / max(len(changes), 1), "Updating display names...")
            content = db.get_content(ID=change.track.id)
            if content is None or content.FolderPath != change.track.path:
                result.skipped.append((change.track, "Track changed since the scan."))
                continue
            change.old_path = content.FileNameL or ""
            content.FileNameL = change.new_path
            result.applied.append(change)
        if result.applied:
            ensure_rekordbox_closed()
            db.commit()
    except Exception:
        db.rollback()
        log.exception("Display name update failed, nothing was committed")
        raise
    finally:
        close_database(db)

    backup.write_text("changes.csv", changes_csv_text(result.applied))
    _report(progress, 92, "Verifying...")
    result.warnings.extend(
        _verify(db_path, {c.track.id: ("FileNameL", c.new_path) for c in result.applied})
    )
    log.info("Updated %d display name(s); backup at %s", len(result.applied), backup.path)
    _report(progress, 100, "Done")
    return result


def find_untracked_files(db_path, folders, progress=None):
    tracks = _read_tracks(db_path, progress)
    known = {normalize_path(t.path) for t in tracks if is_local_file_path(t.path)}
    _report(progress, 30, "Scanning music folders...")
    untracked = []
    seen = set()
    for folder in folders:
        for path, _size in iter_audio_files(folder):
            key = normalize_path(path)
            if key in known or key in seen:
                continue
            seen.add(key)
            untracked.append(path)
    untracked.sort(key=str.lower)
    _report(progress, 100, "Done")
    log.info("Found %d untracked file(s)", len(untracked))
    return untracked
