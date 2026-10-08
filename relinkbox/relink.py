from collections import defaultdict
from difflib import SequenceMatcher
import os

from pyrekordbox import Rekordbox6Database

AUDIO_EXTENSIONS = (".mp3", ".flac", ".wav", ".aiff", ".m4a")
PATH_ATTRS = ("Location", "DevicePath", "FolderPath", "FilePath")


def normalize_path(path):
    return os.path.normpath(path.lower())


def get_similarity_ratio(str1, str2):
    return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()


def get_music_files(library_path):
    music_files = defaultdict(list)
    total_files = 0
    for root, _dirs, files in os.walk(library_path):
        for file in files:
            if file.lower().endswith(AUDIO_EXTENSIONS):
                total_files += 1
                full_path = os.path.join(root, file)
                first_letter = file[0].lower() if file else ""
                music_files[first_letter].append(
                    {
                        "name": file.lower(),
                        "path": full_path,
                        "norm_path": normalize_path(full_path),
                    }
                )
    return music_files, total_files


def find_best_match(target_filename, target_path, music_files, threshold=0.95):
    if not target_filename:
        return None

    clean_name = target_filename.lower()
    first_letter = clean_name[0] if clean_name else ""
    candidates = music_files.get(first_letter, [])
    if not candidates:
        return None

    norm_target_path = normalize_path(target_path)
    for candidate in candidates:
        if candidate["norm_path"] == norm_target_path:
            return candidate["path"]

    best_match = None
    best_ratio = 0
    target_name_clean = os.path.splitext(clean_name)[0]

    for candidate in candidates:
        candidate_name = os.path.splitext(candidate["name"])[0]
        ratio = get_similarity_ratio(target_name_clean, candidate_name)
        if ratio > best_ratio:
            len_diff = abs(len(target_name_clean) - len(candidate_name))
            if len_diff <= 5 and ratio >= threshold:
                best_ratio = ratio
                best_match = candidate["path"]

    return best_match if best_ratio >= threshold else None


def _track_path(track):
    for attr in PATH_ATTRS:
        path_value = getattr(track, attr, None)
        if path_value and isinstance(path_value, str):
            return path_value, attr
    return None, None


def relink_tracks(db_path, music_folder, progress_callback=None):
    if progress_callback:
        progress_callback(0, 100)
        progress_callback(1, 100)

    try:
        db = Rekordbox6Database(db_path)
        if progress_callback:
            progress_callback(5, 100)

        tracks = list(db.get_content())
        total_tracks = len(tracks)
        if progress_callback:
            progress_callback(10, 100)

        music_files, total_music_files = get_music_files(music_folder)
        if progress_callback:
            progress_callback(20, 100)

        updated = 0
        progress_step = 70 / max(total_tracks, 1)

        for i, track in enumerate(tracks):
            if progress_callback:
                progress_callback(20 + int(i * progress_step), 100)

            try:
                current_path, _ = _track_path(track)
                if not current_path:
                    continue

                filename = os.path.basename(current_path)
                new_path = find_best_match(filename, current_path, music_files)
                if not new_path or new_path == current_path:
                    continue

                updated_attr = None
                for attr in PATH_ATTRS:
                    if getattr(track, attr, None) == current_path:
                        setattr(track, attr, new_path.replace("\\", "/"))
                        updated_attr = attr
                        break

                if not updated_attr:
                    continue

                new_filename = os.path.basename(new_path)
                if getattr(track, "FileName", None) != new_filename:
                    track.FileName = new_filename

                updated += 1
                try:
                    db.session.flush()
                except Exception as commit_error:
                    print(f"Warning: Could not flush changes: {commit_error}")
                    continue
            except Exception as e:
                print(f"Error processing track: {e}")
                continue

        if progress_callback:
            progress_callback(90, 100)

        try:
            db.session.commit()
        except Exception as commit_error:
            print(f"Warning: Final commit had issues: {commit_error}")

        if progress_callback:
            progress_callback(100, 100)

        return {
            "total_tracks": total_tracks,
            "total_music_files": total_music_files,
            "updated_tracks": updated,
        }
    except Exception as e:
        print(f"Database error: {e}")
        return {
            "error": str(e),
            "total_tracks": 0,
            "total_music_files": 0,
            "updated_tracks": 0,
        }


def find_untracked_files(db_path, music_folder, progress_callback=None):
    if progress_callback:
        progress_callback(0, 100)
        progress_callback(1, 100)

    try:
        db = Rekordbox6Database(db_path)
        if progress_callback:
            progress_callback(5, 100)

        tracks = list(db.get_content())
        if progress_callback:
            progress_callback(10, 100)

        db_paths = set()
        db_paths_normalized = set()
        for track in tracks:
            current_path, _ = _track_path(track)
            if current_path:
                db_paths.add(current_path)
                db_paths_normalized.add(normalize_path(current_path))

        if progress_callback:
            progress_callback(30, 100)

        all_music_files = []
        for root, _dirs, files in os.walk(music_folder):
            for file in files:
                if file.lower().endswith(AUDIO_EXTENSIONS):
                    all_music_files.append(os.path.join(root, file))

        if progress_callback:
            progress_callback(60, 100)

        untracked_files = []
        progress_step = 30 / max(len(all_music_files), 1)
        for i, file_path in enumerate(all_music_files):
            if progress_callback:
                progress_callback(60 + int(i * progress_step), 100)

            unix_path = file_path.replace("\\", "/")
            win_path = file_path.replace("/", "\\")
            if (
                unix_path not in db_paths
                and win_path not in db_paths
                and normalize_path(file_path) not in db_paths_normalized
            ):
                untracked_files.append(file_path)

        if progress_callback:
            progress_callback(100, 100)

        return untracked_files
    except Exception as e:
        print(f"Error finding untracked files: {e}")
        return []


def update_display_filenames(db_path, progress_callback=None):
    if progress_callback:
        progress_callback(0, 100)
        progress_callback(1, 100)

    try:
        db = Rekordbox6Database(db_path)
        if progress_callback:
            progress_callback(5, 100)

        tracks = list(db.get_content())
        total_tracks = len(tracks)
        if progress_callback:
            progress_callback(10, 100)

        updated = 0
        progress_step = 80 / max(total_tracks, 1)

        for i, track in enumerate(tracks):
            if progress_callback:
                progress_callback(10 + int(i * progress_step), 100)

            try:
                current_path, _ = _track_path(track)
                if not current_path:
                    continue

                actual_filename = os.path.basename(current_path)
                if getattr(track, "FileName", None) != actual_filename:
                    track.FileName = actual_filename
                    updated += 1
                    try:
                        db.session.flush()
                    except Exception as commit_error:
                        print(f"Warning: Could not flush changes: {commit_error}")
                        continue
            except Exception as e:
                print(f"Error processing track display name: {e}")
                continue

        if progress_callback:
            progress_callback(90, 100)

        try:
            db.session.commit()
        except Exception as commit_error:
            print(f"Warning: Final commit had issues: {commit_error}")

        if progress_callback:
            progress_callback(100, 100)

        return {"total_tracks": total_tracks, "updated_filenames": updated}
    except Exception as e:
        print(f"Database error: {e}")
        return {"error": str(e), "total_tracks": 0, "updated_filenames": 0}
