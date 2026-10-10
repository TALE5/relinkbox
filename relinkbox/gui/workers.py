import logging

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


class Worker(QObject):
    """Runs fn(*args, progress=callback) on a background thread."""

    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args

    def run(self):
        try:
            result = self.fn(*self.args, progress=self.progress.emit)
        except Exception as e:
            log.exception("%s failed", getattr(self.fn, "__name__", "task"))
            self.failed.emit(str(e))
            return
        self.finished.emit(result)
