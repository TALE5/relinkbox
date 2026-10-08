from PySide6.QtCore import QObject, Signal

from relinkbox.relink import (
    find_untracked_files,
    relink_tracks,
    update_display_filenames,
)


class RelinkWorker(QObject):
    finished = Signal(dict)
    progress = Signal(int, int)

    def __init__(self, db_path, music_folder):
        super().__init__()
        self.db_path = db_path
        self.music_folder = music_folder

    def run(self):
        stats = relink_tracks(self.db_path, self.music_folder, self.progress.emit)
        self.finished.emit(stats)


class UntrackedFilesWorker(QObject):
    finished = Signal(list)
    progress = Signal(int, int)

    def __init__(self, db_path, music_folder):
        super().__init__()
        self.db_path = db_path
        self.music_folder = music_folder

    def run(self):
        files = find_untracked_files(self.db_path, self.music_folder, self.progress.emit)
        self.finished.emit(files)


class UpdateDisplayFilenamesWorker(QObject):
    finished = Signal(dict)
    progress = Signal(int, int)

    def __init__(self, db_path):
        super().__init__()
        self.db_path = db_path

    def run(self):
        stats = update_display_filenames(self.db_path, self.progress.emit)
        self.finished.emit(stats)
