import logging

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

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


class TaskRunner(QObject):
    """One background task at a time. Results always come back on the UI thread.

    TaskRunner itself is a QObject so progress/finished/failed are queued. A plain
    Python callback connected to a worker signal runs on the worker thread, which
    is what produced the timer errors and the freeze after a cue scan.
    """

    def __init__(self, parent, set_busy, on_progress, on_failed):
        super().__init__(parent)
        self._set_busy = set_busy
        self._on_progress = on_progress
        self._on_failed = on_failed
        self.thread = None
        self.worker = None
        self._on_done = None

    @property
    def busy(self):
        return bool(self.thread and self.thread.isRunning())

    def run(self, fn, args, on_done, busy_text):
        if self.busy:
            return False
        self._set_busy(True, busy_text)
        self._on_done = on_done
        self.thread = QThread(self)
        self.worker = Worker(fn, *args)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress, Qt.QueuedConnection)
        self.worker.finished.connect(self._finish, Qt.QueuedConnection)
        self.worker.failed.connect(self._failed, Qt.QueuedConnection)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()
        return True

    @Slot(int, str)
    def _progress(self, percent, text):
        self._on_progress(percent, text)

    @Slot(object)
    def _finish(self, result):
        self._set_busy(False)
        self.thread = None
        self.worker = None
        done = self._on_done
        self._on_done = None
        if done:
            done(result)

    @Slot(str)
    def _failed(self, message):
        self._set_busy(False)
        self.thread = None
        self.worker = None
        self._on_done = None
        self._on_failed(message)
