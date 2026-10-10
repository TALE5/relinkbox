from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

CUE_COLORS = {
    0: QColor(220, 220, 220),
    1: QColor(232, 72, 72),
    2: QColor(232, 148, 48),
    3: QColor(72, 196, 88),
    5: QColor(64, 168, 232),
    6: QColor(168, 88, 232),
    7: QColor(232, 88, 168),
    8: QColor(88, 220, 200),
    9: QColor(240, 220, 72),
}


def cue_color(kind):
    return CUE_COLORS.get(kind, QColor(200, 200, 200))


class OverviewWaveform(QWidget):
    """Full-track waveform with cue markers. Clicking jumps to that time."""

    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(88)
        self.heights = None
        self.colors = None
        self.cues = []
        self.playhead_ms = None
        self.duration_ms = 1

    def set_data(self, waveform, cues, duration_ms=None):
        if waveform is None:
            self.heights = None
            self.colors = None
            self.duration_ms = duration_ms or 1
        else:
            self.heights = waveform.heights
            self.colors = waveform.colors
            self.duration_ms = duration_ms or max(int(waveform.time(len(waveform.heights) - 1)), 1)
        self.cues = cues or []
        self.update()

    def set_playhead(self, ms):
        self.playhead_ms = ms
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self._time_at(event.position().x()))

    def _time_at(self, x):
        return max(0, min(self.duration_ms, int(x / max(self.width(), 1) * self.duration_ms)))

    def _x_at(self, ms):
        return int(ms / self.duration_ms * self.width())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(22, 24, 28))
        if self.heights is None or len(self.heights) == 0:
            painter.setPen(QColor(140, 140, 140))
            painter.drawText(self.rect(), Qt.AlignCenter, "No waveform")
            return
        w, h = self.width(), self.height()
        mid = h // 2
        n = len(self.heights)
        cols = max(w, 1)
        for x in range(cols):
            start = int(x * n / cols)
            end = max(start + 1, int((x + 1) * n / cols))
            peak = int(self.heights[start:end].max())
            bar = max(1, int(peak / 31 * (h * 0.42)))
            if self.colors is not None:
                r, g, b = (int(v) for v in self.colors[start:end].mean(axis=0))
                color = QColor(max(r, 40), max(g, 40), max(b, 40))
            else:
                color = QColor(70, 150, 200)
            painter.fillRect(x, mid - bar, 1, bar * 2, color)
        for cue in self.cues:
            painter.setPen(QPen(cue_color(cue.kind), 2))
            painter.drawLine(self._x_at(cue.in_ms), 2, self._x_at(cue.in_ms), h - 2)
        if self.playhead_ms is not None:
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawLine(self._x_at(self.playhead_ms), 0, self._x_at(self.playhead_ms), h)


class CueStrip(QWidget):
    """One cue, about a beat either side. Shows the grid, the cue now, and where it would snap."""

    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(72)
        self.waveform = None
        self.grid = None
        self.cue = None
        self.proposed_in = None
        self.hits_offset = None
        self.window_ms = 500
        self.start_ms = 0

    def set_data(self, waveform, grid, cue, proposed_in=None, hits_offset=None):
        self.waveform = waveform
        self.grid = grid
        self.cue = cue
        self.proposed_in = proposed_in
        self.hits_offset = hits_offset
        beat = grid.beat_length(cue.in_ms) if grid else 500
        self.window_ms = max(beat * 2, 200)
        self.start_ms = max(0, cue.in_ms - self.window_ms / 2)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(int(self.start_ms + event.position().x() / max(self.width(), 1) * self.window_ms))

    def _x_at(self, ms):
        return int((ms - self.start_ms) / self.window_ms * self.width())

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(22, 24, 28))
        w, h = self.width(), self.height()
        end_ms = self.start_ms + self.window_ms
        mid = int(h * 0.55)

        if self.waveform is not None:
            i0 = max(0, self.waveform.index(self.start_ms))
            i1 = min(len(self.waveform.heights), self.waveform.index(end_ms) + 1)
            if i1 > i0:
                span = i1 - i0
                for x in range(w):
                    start = i0 + int(x * span / w)
                    end = max(start + 1, i0 + int((x + 1) * span / w))
                    peak = int(self.waveform.heights[start:end].max())
                    bar = max(1, int(peak / 31 * (h * 0.38)))
                    painter.fillRect(x, mid - bar, 1, bar, QColor(80, 160, 210))

        if self.grid is not None:
            for t, beat in zip(self.grid.times, self.grid.beats):
                if t < self.start_ms or t > end_ms:
                    continue
                x = self._x_at(t)
                if beat == 1:
                    painter.setPen(QPen(QColor(240, 240, 240, 200), 2))
                else:
                    painter.setPen(QPen(QColor(160, 160, 160, 120), 1))
                painter.drawLine(x, 8, x, h - 14)

        if self.hits_offset is not None and self.grid is not None and self.cue is not None:
            hit = self.grid.times[self.grid.nearest(self.cue.in_ms)] + self.hits_offset
            if self.start_ms <= hit <= end_ms:
                painter.setPen(QPen(QColor(255, 200, 80), 1, Qt.DotLine))
                painter.drawLine(self._x_at(hit), 8, self._x_at(hit), h - 14)

        if self.cue is not None:
            color = cue_color(self.cue.kind)
            x = self._x_at(self.cue.in_ms)
            painter.setPen(QPen(color, 2))
            painter.drawLine(x, 4, x, h - 16)
            painter.setPen(color)
            painter.drawText(x + 4, 14, self.cue.label)
            if self.proposed_in is not None and abs(self.proposed_in - self.cue.in_ms) > 1:
                px = self._x_at(self.proposed_in)
                painter.setPen(QPen(color, 2, Qt.DashLine))
                painter.drawLine(px, 4, px, h - 16)
                painter.drawText(px + 4, 28, f"{self.proposed_in - self.cue.in_ms:+d} ms")

        painter.setPen(QColor(150, 150, 150))
        if self.cue is not None:
            painter.drawText(6, h - 4, f"{self.cue.label} at {self.cue.in_ms / 1000:.2f}s")
