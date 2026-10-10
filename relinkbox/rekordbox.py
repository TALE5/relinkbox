import os
from dataclasses import dataclass

from pyrekordbox import Rekordbox6Database
from pyrekordbox.utils import get_rekordbox_pid

from relinkbox.analysis import iter_sections


class RekordboxRunningError(RuntimeError):
    def __init__(self):
        super().__init__("Rekordbox is running. Close it before making changes to the library.")


@dataclass(frozen=True)
class TrackInfo:
    id: str
    path: str
    display_name: str
    size: int
    title: str
    artist: str

    @property
    def label(self):
        if self.artist and self.title:
            return f"{self.artist} - {self.title}"
        return self.title or self.display_name or os.path.basename(self.path)


def is_rekordbox_running():
    try:
        return bool(get_rekordbox_pid())
    except Exception:
        return False


def ensure_rekordbox_closed():
    if is_rekordbox_running():
        raise RekordboxRunningError()


def default_database_candidates():
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    return [
        os.path.join(appdata, "Pioneer", "rekordbox", "master.db"),
        os.path.expanduser("~/Library/Application Support/Pioneer/rekordbox/master.db"),
    ]


def find_default_database():
    for path in default_database_candidates():
        if os.path.exists(path):
            return path
    return None


def open_database(db_path):
    return Rekordbox6Database(db_path)


def close_database(db):
    """Close the session and release pooled connections so the files are not left locked."""
    try:
        db.close()
    finally:
        db.engine.dispose()


def read_anlz_files(db, content_id):
    try:
        return db.read_anlz_files(content_id)
    except FileNotFoundError:
        return {}


def raw_tag_types(path):
    """Four-character codes of every section in an analysis file, read straight from the bytes."""
    with open(path, "rb") as fh:
        data = fh.read()
    return [code for code, _start, _len_header, _len_tag in iter_sections(data)]


def lost_tag_types(path, anlz):
    """Section types pyrekordbox did not parse, so saving the file would drop them."""
    remaining = list(anlz.tag_types)
    lost = []
    for tag_type in raw_tag_types(path):
        if tag_type in remaining:
            remaining.remove(tag_type)
        else:
            lost.append(tag_type)
    return lost


# Rekordbox's djmdContent.FileType codes.
FILE_TYPES = {".mp3": 1, ".m4a": 4, ".aac": 4, ".flac": 5, ".wav": 11, ".aif": 12, ".aiff": 12}


def file_type_for(path):
    return FILE_TYPES.get(os.path.splitext(path)[1].lower())


def is_local_file_path(path):
    """Streaming and cloud tracks store URIs instead of file paths; skip those."""
    if not path:
        return False
    return os.path.isabs(path) or (len(path) > 2 and path[1] == ":")


def track_info(content):
    artist = ""
    try:
        artist = content.ArtistName or ""
    except Exception:
        pass
    return TrackInfo(
        id=str(content.ID),
        path=content.FolderPath or "",
        display_name=content.FileNameL or "",
        size=int(content.FileSize or 0),
        title=content.Title or "",
        artist=artist,
    )


def load_tracks(db):
    query = db.get_content()
    try:
        from sqlalchemy.orm import joinedload
        from pyrekordbox.db6.tables import DjmdContent

        query = query.options(joinedload(DjmdContent.Artist))
    except Exception:
        pass
    return [track_info(content) for content in query]
