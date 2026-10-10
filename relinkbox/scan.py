import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = (
    ".mp3",
    ".flac",
    ".wav",
    ".wave",
    ".aif",
    ".aiff",
    ".m4a",
    ".aac",
    ".mp4",
    ".alac",
    ".ogg",
)


def is_audio_file(name):
    return name.lower().endswith(AUDIO_EXTENSIONS)


def normalize_path(path):
    return os.path.normcase(os.path.normpath(path))


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int

    @property
    def name(self):
        return os.path.basename(self.path).lower()

    @property
    def stem(self):
        return os.path.splitext(self.name)[0]

    @property
    def ext(self):
        return os.path.splitext(self.name)[1]


@dataclass
class MusicIndex:
    files: list = field(default_factory=list)
    by_name: dict = field(default_factory=lambda: defaultdict(list))
    by_stem: dict = field(default_factory=lambda: defaultdict(list))
    by_size: dict = field(default_factory=lambda: defaultdict(list))
    errors: list = field(default_factory=list)

    def add(self, entry):
        self.files.append(entry)
        self.by_name[entry.name].append(entry)
        self.by_stem[entry.stem].append(entry)
        if entry.size:
            self.by_size[entry.size].append(entry)


def iter_audio_files(folder, errors=None):
    stack = [folder]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file() and is_audio_file(entry.name):
                            yield entry.path, entry.stat().st_size
                    except OSError as e:
                        log.warning("Could not read %s: %s", entry.path, e)
                        if errors is not None:
                            errors.append(f"{entry.path}: {e}")
        except OSError as e:
            log.warning("Could not open folder %s: %s", current, e)
            if errors is not None:
                errors.append(f"{current}: {e}")


def scan_folders(folders):
    index = MusicIndex()
    seen = set()
    for folder in folders:
        for path, size in iter_audio_files(folder, index.errors):
            key = normalize_path(path)
            if key in seen:
                continue
            seen.add(key)
            index.add(FileEntry(path=path, size=size))
    return index
