import bisect
from collections import namedtuple

import numpy as np
from PySide6.QtCore import QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import QWidget

# Memory cues use Color 1-8. Hot cues use ColorTableIndex 0x01-0x3E (Pioneer table).
MEMORY_COLORS = {
    1: QColor(222, 68, 207),
    2: QColor(226, 40, 40),
    3: QColor(255, 140, 0),
    4: QColor(240, 220, 32),
    5: QColor(50, 196, 80),
    6: QColor(0, 200, 220),
    7: QColor(48, 90, 255),
    8: QColor(160, 64, 220),
}

# ColorTableIndex 1-62. Source: rekordcrate ExtendedCue hot_cue_color_index.
HOT_CUE_PALETTE = [
    (0, 0, 0),
    (0x30, 0x5A, 0xFF), (0x50, 0x73, 0xFF), (0x50, 0x8C, 0xFF), (0x50, 0xA0, 0xFF),
    (0x50, 0xB4, 0xFF), (0x50, 0xB0, 0xF2), (0x50, 0xAE, 0xE8), (0x45, 0xAC, 0xDB),
    (0x00, 0xE0, 0xFF), (0x19, 0xDA, 0xF0), (0x32, 0xD2, 0xE6), (0x21, 0xB4, 0xB9),
    (0x20, 0xAA, 0xA0), (0x1F, 0xA3, 0x92), (0x19, 0xA0, 0x8C), (0x14, 0xA5, 0x84),
    (0x14, 0xAA, 0x7D), (0x10, 0xB1, 0x76), (0x30, 0xD2, 0x6E), (0x37, 0xDE, 0x5A),
    (0x3C, 0xEB, 0x50), (0x28, 0xE2, 0x14), (0x7D, 0xC1, 0x3D), (0x8C, 0xC8, 0x32),
    (0x9B, 0xD7, 0x23), (0xA5, 0xE1, 0x16), (0xA5, 0xDC, 0x0A), (0xAA, 0xD2, 0x08),
    (0xB4, 0xC8, 0x05), (0xB4, 0xBE, 0x04), (0xBA, 0xB4, 0x04), (0xC3, 0xAF, 0x04),
    (0xE1, 0xAA, 0x00), (0xFF, 0xA0, 0x00), (0xFF, 0x96, 0x00), (0xFF, 0x8C, 0x00),
    (0xFF, 0x75, 0x00), (0xE0, 0x64, 0x1B), (0xE0, 0x46, 0x1E), (0xE0, 0x30, 0x1E),
    (0xE0, 0x28, 0x23), (0xE6, 0x28, 0x28), (0xFF, 0x37, 0x6F), (0xFF, 0x2D, 0x6F),
    (0xFF, 0x12, 0x7B), (0xF5, 0x1E, 0x8C), (0xEB, 0x2D, 0xA0), (0xE6, 0x37, 0xB4),
    (0xDE, 0x44, 0xCF), (0xDE, 0x44, 0x8D), (0xE6, 0x30, 0xB4), (0xE6, 0x19, 0xDC),
    (0xE6, 0x00, 0xFF), (0xDC, 0x00, 0xFF), (0xCC, 0x00, 0xFF), (0xB4, 0x32, 0xFF),
    (0xB9, 0x3C, 0xFF), (0xC5, 0x42, 0xFF), (0xAA, 0x5A, 0xFF), (0xAA, 0x72, 0xFF),
    (0x82, 0x72, 0xFF), (0x64, 0x73, 0xFF),
]

KIND_COLORS = {
    0: QColor(220, 220, 220),
    1: QColor(255, 55, 111),
    2: QColor(255, 140, 0),
    3: QColor(125, 193, 61),
    5: QColor(80, 180, 255),
    6: QColor(180, 60, 255),
    7: QColor(222, 68, 207),
    8: QColor(0, 224, 255),
    9: QColor(240, 220, 32),
}

BG = QColor(0, 0, 0)
SURFACE = QColor("#121214")
LOW = QColor(26, 82, 196)
MID = QColor(214, 140, 36)
HIGH = QColor(248, 244, 232)
BAKE_HEIGHT = 128
OVERVIEW_WIDTH = 2400
BADGE = 16

BakedWave = namedtuple("BakedWave", "image duration_ms")


def cue_color(cue):
    if getattr(cue, "kind", 0) == 0:
        memory = getattr(cue, "color", -1)
        if 1 <= memory <= 8:
            return MEMORY_COLORS[memory]
    idx = getattr(cue, "color_index", 0) or 0
    if 1 <= idx < len(HOT_CUE_PALETTE):
        return QColor(*HOT_CUE_PALETTE[idx])
    return KIND_COLORS.get(getattr(cue, "kind", 0), QColor(200, 200, 200))


def _resample(data, width):
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim == 1:
        arr = np.column_stack([arr, arr * 0.65, arr * 0.35])
    n = len(arr)
    if n == 0 or width < 1:
        return np.zeros((max(width, 1), 3), dtype=np.float32)
    scale = max(31.0, float(arr.max()) if arr.size else 31.0)
    arr = arr / scale
    if n == width:
        return np.clip(arr, 0, 1)
    if n < width:
        x = np.linspace(0, n - 1, width)
        src = np.arange(n)
        return np.clip(np.stack([np.interp(x, src, arr[:, c]) for c in range(arr.shape[1])], axis=1), 0, 1)
    idx = np.linspace(0, n, width + 1).astype(np.int64)
    idx[-1] = n
    sums = np.concatenate([np.zeros((1, arr.shape[1]), dtype=np.float32), np.cumsum(arr, axis=0)])
    counts = np.maximum(idx[1:] - idx[:-1], 1).astype(np.float32)[:, None]
    return np.clip((sums[idx[1:]] - sums[idx[:-1]]) / counts, 0, 1)


def bake_waveform(data, duration_ms, width, height=BAKE_HEIGHT, onesided=False, background=None):
    """Paint a 3-band picture once. The widget only pastes this afterwards."""
    if data is None or len(data) == 0 or duration_ms <= 0:
        return None
    env = _resample(data, width)
    image = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    image.fill(BG if background is None else background)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)

    def envelope(values, color, base, amp):
        path = QPainterPath()
        path.moveTo(0, base)
        for x, value in enumerate(values):
            path.lineTo(x, base - value * amp)
        if onesided:
            path.lineTo(len(values) - 1, base)
        else:
            for x in range(len(values) - 1, -1, -1):
                path.lineTo(x, base + values[x] * amp)
        path.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawPath(path)

    if onesided:
        base = height - 2
        amp = height * 0.90
        envelope(env[:, 0], LOW, base, amp)
        envelope(env[:, 1], MID, base, amp)
        envelope(env[:, 2] * 0.55, HIGH, base, amp)
        painter.setPen(QPen(QColor(230, 230, 230), 1))
        painter.drawLine(0, int(base), width - 1, int(base))
    else:
        base = height / 2
        amp = height * 0.46
        envelope(env[:, 0], LOW, base, amp)
        envelope(env[:, 1], MID, base, amp)
        envelope(env[:, 2] * 0.55, HIGH, base, amp)
        painter.setPen(QPen(QColor(230, 230, 230), 1))
        painter.drawLine(0, int(base), width - 1, int(base))
    painter.end()
    return BakedWave(image, int(duration_ms))


def bake_track(waveform, duration_ms):
    """Whole-track overview from PWV6, drawn as a top-half strip."""
    if waveform is None or duration_ms <= 0:
        return None
    overview_src = waveform.overview if waveform.overview is not None else waveform.bands
    if overview_src is None:
        overview_src = waveform.heights
    return bake_waveform(
        overview_src, duration_ms, OVERVIEW_WIDTH, height=80, onesided=True, background=SURFACE
    )


def bake_window(waveform, start_ms, view_ms, width, height, background=None):
    """Sharp picture of one time window, at the pixel size of the widget."""
    if waveform is None or view_ms <= 0 or width < 8 or height < 8:
        return None
    data = waveform.bands if waveform.bands is not None else waveform.heights
    if data is None or len(data) == 0:
        return None
    i0 = max(0, waveform.index(start_ms))
    i1 = min(len(data), max(i0 + 1, waveform.index(start_ms + view_ms) + 1))
    return bake_waveform(data[i0:i1], view_ms, width, height, background=background)


def _blit(painter, baked, start_ms, view_ms, target):
    if baked is None or baked.duration_ms <= 0:
        return False
    width = baked.image.width()
    x0 = width * start_ms / baked.duration_ms
    span = max(width * view_ms / baked.duration_ms, 1)
    painter.drawImage(QRectF(target), baked.image, QRectF(x0, 0, span, baked.image.height()))
    return True


def cue_letter(cue):
    if getattr(cue, "kind", 0) == 0:
        return "M"
    label = getattr(cue, "label", "")
    return label[:1] if label else "?"


def _draw_badge(painter, x, color, text, y=3, size=BADGE):
    box = QRect(x - size // 2, y, size, size)
    painter.fillRect(box, color)
    painter.setPen(QColor(20, 20, 20) if color.lightness() > 150 else QColor("#e6e6ea"))
    font = QFont(painter.font())
    font.setBold(True)
    font.setPixelSize(9 if size < 15 else 11)
    painter.setFont(font)
    painter.drawText(box, Qt.AlignCenter, text)


class TrackNavigator(QWidget):
    """Whole-track strip. The box is the zoomed view; drag moves the playhead."""

    clicked = Signal(int)
    scrubbed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setMouseTracking(True)
        self.overview = None
        self.cues = []
        self.duration_ms = 1
        self.start_ms = 0
        self.view_ms = 1
        self.playhead_ms = None
        self._dragging = False

    def set_data(self, overview, cues, duration_ms):
        self.overview = overview
        self.cues = cues or []
        self.duration_ms = duration_ms or 1
        self.start_ms = 0
        self.view_ms = self.duration_ms
        self.playhead_ms = None
        self.update()

    def set_view(self, start_ms, view_ms):
        self.start_ms = start_ms
        self.view_ms = view_ms
        self.update()

    def set_playhead(self, ms):
        self.playhead_ms = ms
        self.update()

    def _x_at(self, ms):
        return int(ms / max(self.duration_ms, 1) * self.width())

    def _time_at(self, x):
        x = max(0.0, min(float(x), float(self.width())))
        return int(x / max(self.width(), 1) * self.duration_ms)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.duration_ms > 1:
            self._dragging = True
            self.grabMouse()
            ms = self._time_at(event.position().x())
            self.playhead_ms = ms
            self.update()
            self.clicked.emit(ms)

    def mouseMoveEvent(self, event):
        if self._dragging and self.duration_ms > 1:
            ms = self._time_at(event.position().x())
            self.playhead_ms = ms
            self.update()
            self.scrubbed.emit(ms)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self.releaseMouse()
        self._dragging = False

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), SURFACE)
        w, h = self.width(), self.height()
        if self.overview is not None:
            src = self.overview.image
            painter.drawImage(QRectF(0, 0, w, h), src, QRectF(src.rect()))
        painter.setPen(QPen(QColor(230, 230, 230), 1))
        painter.drawLine(0, h - 1, w, h - 1)
        x0 = self._x_at(self.start_ms)
        x1 = self._x_at(self.start_ms + self.view_ms)
        painter.fillRect(x0, 0, max(x1 - x0, 3), h, QColor(255, 255, 255, 40))
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        painter.drawRect(x0, 0, max(x1 - x0, 3), h - 1)
        for cue in self.cues:
            _draw_badge(painter, self._x_at(cue.in_ms), cue_color(cue), cue_letter(cue), y=1, size=12)
        if self.playhead_ms is not None:
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawLine(self._x_at(self.playhead_ms), 0, self._x_at(self.playhead_ms), h)


_GRID_BEAT_PX = 22
_GRID_MIN_PX = 12


def _grid_stride(beats, spacing_px):
    """How many grid steps to skip so lines stay readable at this zoom.

    A line every beat is right when one beat is already wide. Otherwise draw
    bars, then every 2, 4, 8 bars, until neighboring lines are far enough apart
    that they no longer cover the waveform.
    """
    origin = 0
    for i, beat in enumerate(beats[:500]):
        if beat == 1:
            origin = i
            break
    gaps = []
    previous = None
    for i, beat in enumerate(beats[:500]):
        if beat != 1:
            continue
        if previous is not None:
            gaps.append(i - previous)
            if len(gaps) >= 40:
                break
        previous = i
    bar = 1
    if gaps:
        gaps.sort()
        bar = max(1, gaps[len(gaps) // 2])
    if spacing_px >= _GRID_BEAT_PX:
        return 1, origin
    if spacing_px <= 0:
        return bar * 64, origin
    groups = 1
    while spacing_px * bar * groups < _GRID_MIN_PX and groups < 64:
        groups *= 2
    return bar * groups, origin


class OverviewWaveform(QWidget):
    """Detail waveform. Wheel zooms, drag scrubs, shift-drag pans."""

    clicked = Signal(int)
    view_changed = Signal(int, int)
    scrubbed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(168)
        self.setMouseTracking(True)
        self.waveform = None
        self.grid = None
        self.cues = []
        self.proposed = {}
        self.playhead_ms = None
        self.duration_ms = 1
        self.zoom = 1.0
        self.start_ms = 0
        self._drag_x = None
        self._drag_start = 0
        self._press_x = None
        self._press_ms = None
        self._dragged = False
        self._scrubbing = False
        self._strip = None
        self._strip_meta = None
        self._live = False
        self._last_view_emit = None
        self._last_scrub_ms = None
        self._zoom_hold = False
        self._bake_timer = QTimer(self)
        self._bake_timer.setSingleShot(True)
        self._bake_timer.timeout.connect(self._apply_pending_bake)

    def set_data(self, waveform, cues, duration_ms=None, overview=None, proposed=None, grid=None):
        self.waveform = waveform
        self.grid = grid
        self.proposed = proposed or {}
        if duration_ms:
            self.duration_ms = duration_ms
        elif waveform is not None and len(waveform.heights):
            self.duration_ms = max(int(waveform.time(len(waveform.heights) - 1)), 1)
        else:
            self.duration_ms = 1
        self.cues = cues or []
        self.zoom = 1.0
        self.start_ms = 0
        self._strip = None
        self._strip_meta = None
        self._last_view_emit = None
        self._zoom_hold = False
        self.update()
        self._emit_view()

    def set_live(self, live):
        self._live = live

    def set_playhead(self, ms, follow=False):
        self.playhead_ms = ms
        if follow and ms is not None and self._drag_x is None and self.zoom > 1.01:
            new_start = self._clamp_start(ms - self._view_ms() / 2)
            if abs(new_start - self.start_ms) >= 1:
                self.start_ms = new_start
                self._emit_view()
        self.update()

    def center_on(self, ms):
        self.start_ms = self._clamp_start(ms - self._view_ms() / 2)
        self.update()
        self._emit_view()

    def _view_ms(self):
        return self.duration_ms / self.zoom

    def _clamp_start(self, start):
        return max(0, min(start, max(0, self.duration_ms - self._view_ms())))

    def _time_at(self, x):
        return int(self.start_ms + x / max(self.width(), 1) * self._view_ms())

    def _x_at(self, ms):
        return int((ms - self.start_ms) / self._view_ms() * self.width())

    def _emit_view(self, throttle=False):
        start, view = int(self.start_ms), int(self._view_ms())
        if throttle and self._last_view_emit is not None:
            last_start, last_view = self._last_view_emit
            if view == last_view and abs(start - last_start) < max(view * 0.04, 40):
                return
        self._last_view_emit = (start, view)
        self.view_changed.emit(start, view)

    def zoom_step(self, factor):
        """Zoom around the middle of the view. Same limits as the scroll wheel."""
        if self.duration_ms <= 1 or factor <= 0:
            return
        x = self.width() / 2
        focus = self._time_at(x)
        self.zoom = max(1.0, min(64.0, self.zoom * factor))
        self.start_ms = self._clamp_start(focus - (x / max(self.width(), 1)) * self._view_ms())
        self._zoom_hold = True
        self._emit_view()
        self.update()
        self._bake_timer.start(16)

    def wheelEvent(self, event):
        if self.duration_ms <= 1:
            return
        dy = event.angleDelta().y()
        if dy == 0:
            return
        x = event.position().x()
        focus = self._time_at(x)
        self.zoom = max(1.0, min(64.0, self.zoom * (1.25 ** (dy / 120))))
        self.start_ms = self._clamp_start(focus - (x / max(self.width(), 1)) * self._view_ms())
        self._zoom_hold = True
        self._emit_view()
        self.update()
        self._bake_timer.start(16)

    def _apply_pending_bake(self):
        self._zoom_hold = False
        self._strip = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() not in (Qt.LeftButton, Qt.MiddleButton):
            return
        self._press_x = event.position().x()
        self._press_ms = self._time_at(self._press_x)
        self._dragged = False
        self._scrubbing = False
        if event.button() == Qt.MiddleButton or event.modifiers() & Qt.ShiftModifier:
            self._drag_x = self._press_x
            self._drag_start = self.start_ms
            return
        if event.button() == Qt.LeftButton and self.duration_ms > 1:
            self._scrubbing = True
            self.grabMouse()
            self.playhead_ms = self._press_ms
            self.update()
            self.clicked.emit(int(self._press_ms))

    def mouseMoveEvent(self, event):
        if self._press_x is not None and abs(event.position().x() - self._press_x) > 4:
            self._dragged = True
        if self._drag_x is not None:
            dx = event.position().x() - self._drag_x
            self.start_ms = self._clamp_start(self._drag_start - dx / max(self.width(), 1) * self._view_ms())
            if self._live:
                ms = int(self.start_ms + self._view_ms() / 2)
                self.playhead_ms = ms
                if self._last_scrub_ms is None or abs(ms - self._last_scrub_ms) > 40:
                    self._last_scrub_ms = ms
                    self.scrubbed.emit(ms)
            self.update()
            self._emit_view(throttle=True)
            return
        if self._scrubbing:
            ms = int(self._time_at(event.position().x()))
            self.playhead_ms = ms
            self.update()
            if self._last_scrub_ms is None or abs(ms - self._last_scrub_ms) > 30:
                self._last_scrub_ms = ms
                self.scrubbed.emit(ms)

    def mouseReleaseEvent(self, event):
        if self._scrubbing:
            self.releaseMouse()
            ms = int(self._time_at(event.position().x()))
            self.playhead_ms = ms
            self.update()
            self.scrubbed.emit(ms)
        elif event.button() == Qt.LeftButton and not self._dragged and self._press_ms is not None:
            self.clicked.emit(self._press_ms)
        self._drag_x = None
        self._press_x = None
        self._press_ms = None
        self._dragged = False
        self._scrubbing = False
        self._last_scrub_ms = None
        self._emit_view()

    def _ensure_strip(self):
        w, h = max(self.width(), 1), max(self.height(), 1)
        view = self._view_ms()
        if view <= 0 or h < 8:
            return None
        px_per_ms = w / view
        if self._zoom_hold and self._strip is not None:
            return self._strip
        if self._strip is not None and self._strip_meta is not None:
            cover_start, cover_ms, cover_w, cover_h = self._strip_meta
            same_scale = cover_h == h and abs(cover_w / cover_ms - px_per_ms) < px_per_ms * 0.03
            covered = self.start_ms >= cover_start and self.start_ms + view <= cover_start + cover_ms + 1
            if same_scale and covered:
                return self._strip
        pad = view * 2 if self.zoom > 1.01 else 0
        bake_start = max(0, self.start_ms - pad)
        bake_end = min(self.duration_ms, self.start_ms + view + pad)
        bake_ms = max(bake_end - bake_start, view)
        bake_w = max(w, int(round(px_per_ms * bake_ms)))
        baked = bake_window(self.waveform, bake_start, bake_ms, bake_w, h, background=SURFACE)
        self._strip = QPixmap.fromImage(baked.image) if baked else None
        self._strip_meta = (bake_start, bake_ms, bake_w, h)
        return self._strip

    def _paint_grid(self, painter, h):
        grid = self.grid
        if grid is None or len(grid) == 0:
            return
        view = self._view_ms()
        if view <= 0:
            return
        w = max(self.width(), 1)
        spacing = w * grid.beat_length(self.start_ms + view / 2) / view
        times = grid.times
        beats = grid.beats
        step, origin = _grid_stride(beats, spacing)
        i0 = bisect.bisect_left(times, self.start_ms)
        i1 = bisect.bisect_right(times, self.start_ms + view)
        if step <= 1:
            for i in range(i0, i1):
                x = self._x_at(times[i])
                if beats[i] == 1:
                    painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
                else:
                    painter.setPen(QPen(QColor(255, 255, 255, 55), 1))
                painter.drawLine(x, 0, x, h)
            return
        if i0 <= origin:
            i = origin
        else:
            i = origin + ((i0 - origin + step - 1) // step) * step
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
        while i < i1:
            x = self._x_at(times[i])
            painter.drawLine(x, 0, x, h)
            i += step

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), SURFACE)
        strip = self._ensure_strip()
        w, h = self.width(), self.height()
        if strip is None or self._strip_meta is None:
            painter.setPen(QColor(140, 140, 140))
            painter.drawText(self.rect(), Qt.AlignCenter, "No waveform")
            return
        cover_start, cover_ms, cover_w, cover_h = self._strip_meta
        x0 = (self.start_ms - cover_start) / cover_ms * cover_w
        span = max(self._view_ms() / cover_ms * cover_w, 1)
        painter.drawPixmap(QRectF(self.rect()), strip, QRectF(x0, 0, span, cover_h))
        self._paint_grid(painter, h)
        for cue in self.cues:
            color = cue_color(cue)
            x = self._x_at(cue.in_ms)
            if 0 <= x <= w:
                painter.setPen(QPen(color, 2))
                painter.drawLine(x, BADGE + 4, x, h - 2)
                _draw_badge(painter, x, color, cue_letter(cue))
            snap = self.proposed.get(cue.id)
            if snap:
                new_in = snap[0] if isinstance(snap, (tuple, list)) else snap
                if new_in is not None and abs(new_in - cue.in_ms) > 1:
                    sx = self._x_at(new_in)
                    if 0 <= sx <= w:
                        painter.setPen(QPen(color, 1, Qt.DashLine))
                        painter.drawLine(sx, BADGE + 4, sx, h - 2)
        if self.playhead_ms is not None:
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawLine(self._x_at(self.playhead_ms), 0, self._x_at(self.playhead_ms), h)


class CueOffsetRow(QWidget):
    """One zoomed cell per hot cue: colored line is the cue, white line is the nearest beat."""

    _ORDER = {1: 0, 2: 1, 3: 2, 5: 3, 6: 4, 7: 5, 8: 6, 9: 7}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(90)
        self.waveform = None
        self.grid = None
        self.cues = []
        self.active_kind = None
        self._cache = {}

    def set_data(self, waveform, grid, cues):
        hot = [cue for cue in (cues or []) if getattr(cue, "kind", 0) != 0]
        hot.sort(key=lambda cue: self._ORDER.get(cue.kind, 99))
        self.waveform = waveform
        self.grid = grid
        self.cues = hot
        self.active_kind = None
        self._cache = {}
        self.setVisible(bool(hot))
        self.update()

    def set_active(self, kind):
        self.active_kind = kind
        self.update()

    def _nearest(self, cue):
        if self.grid is None or len(self.grid) == 0:
            return cue.in_ms
        return int(self.grid.times[self.grid.nearest(cue.in_ms)])

    def _span(self, delta, beat, cell_w):
        if abs(delta) <= 2:
            return max(beat * 0.9, 180)
        span = abs(delta) * max(cell_w, 48) / 34
        return max(span, abs(delta) + 60, 90)

    def _baked(self, cue, start, span, width, height):
        key = (cue.id, int(start), int(span), width, height)
        if key in self._cache:
            return self._cache[key]
        baked = bake_window(self.waveform, int(start), max(int(span), 1), max(width, 8), max(height, 8))
        pix = QPixmap.fromImage(baked.image) if baked else None
        self._cache[key] = pix
        return pix

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), SURFACE)
        if not self.cues:
            return
        n = len(self.cues)
        gap = 4
        cell_w = max((self.width() - gap * (n - 1)) / n, 1)
        for i, cue in enumerate(self.cues):
            x = int(round(i * (cell_w + gap)))
            if i == n - 1:
                w = max(self.width() - x, 1)
            else:
                w = max(int(round(cell_w)), 1)
            self._paint_cell(painter, cue, x, w, self.height())

    def _paint_cell(self, painter, cue, x, w, h):
        bar = 20
        radius = 5
        nearest = self._nearest(cue)
        delta = cue.in_ms - nearest
        beat = self.grid.beat_length(cue.in_ms) if self.grid is not None and len(self.grid) else 500
        span = self._span(delta, beat, w)
        start = max(0, (cue.in_ms + nearest) / 2 - span / 2)
        wave_h = max(h - bar, 8)
        cell = QRectF(x, 0, w, h).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(cell, radius, radius)
        painter.setClipPath(clip)
        painter.fillRect(QRect(x, 0, w, bar), SURFACE)
        target = QRect(x, bar, w, wave_h)
        pix = self._baked(cue, start, span, w, wave_h)
        if pix is not None:
            painter.drawPixmap(target, pix)
        else:
            painter.fillRect(target, BG)
        end = start + span
        if self.grid is not None:
            for t, beat_pos in zip(self.grid.times, self.grid.beats):
                if t < start or t > end or abs(t - nearest) <= 1:
                    continue
                px = int(x + (t - start) / span * w)
                if beat_pos == 1:
                    painter.setPen(QPen(QColor(255, 255, 255, 150), 1))
                else:
                    painter.setPen(QPen(QColor(180, 180, 180, 80), 1))
                painter.drawLine(px, bar, px, h)
        color = cue_color(cue)
        cue_x = int(x + (cue.in_ms - start) / span * w)
        painter.setPen(QPen(color, 2))
        painter.drawLine(cue_x, bar, cue_x, h)
        if abs(delta) > 2:
            beat_x = int(x + (nearest - start) / span * w)
            painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
            painter.drawLine(beat_x, bar, beat_x, h)
        text = "on grid" if abs(delta) <= 2 else f"{delta:+.0f} ms"
        font = QFont(painter.font())
        font.setBold(True)
        font.setPixelSize(11)
        painter.setFont(font)
        box = 16
        gx = x + 6
        gy = max((bar - box) // 2, 0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRect(gx, gy, box, box)
        letter_ink = QColor(20, 20, 20) if color.lightness() > 150 else QColor("#e6e6ea")
        painter.setPen(letter_ink)
        painter.drawText(QRect(gx, gy, box, box), Qt.AlignCenter, cue_letter(cue))
        available = max(w - (gx - x) - box - 10, 0)
        shown = painter.fontMetrics().elidedText(text, Qt.ElideRight, available)
        painter.setPen(QColor("#c4c4ca"))
        painter.drawText(QRect(gx + box + 5, 0, available, bar), Qt.AlignVCenter | Qt.AlignLeft, shown)
        painter.restore()
        edge = QColor("#6a6a72") if cue.kind == self.active_kind else QColor("#3a3a40")
        painter.setPen(QPen(edge, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(cell, radius, radius)


class CueStrip(QWidget):
    """One cue, a few beats either side. Solid = now, dashed = after snap, thick white = downbeat."""

    clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.baked = None
        self.grid = None
        self.cue = None
        self.proposed_in = None
        self.hits_offset = None
        self.window_ms = 500
        self.start_ms = 0

    def set_data(self, baked, grid, cue, proposed_in=None, hits_offset=None):
        self.baked = baked
        self.grid = grid
        self.cue = cue
        self.proposed_in = proposed_in
        self.hits_offset = hits_offset
        beat = grid.beat_length(cue.in_ms) if grid else 500
        self.window_ms = max(beat * 4, 400)
        self.start_ms = max(0, cue.in_ms - self.window_ms / 2)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(int(self.start_ms + event.position().x() / max(self.width(), 1) * self.window_ms))

    def _x_at(self, ms):
        return int((ms - self.start_ms) / self.window_ms * self.width())

    def _marker(self, painter, ms, color, dashed, label, y_label):
        x = self._x_at(ms)
        pen = QPen(color, 2, Qt.DashLine if dashed else Qt.SolidLine)
        painter.setPen(pen)
        painter.drawLine(x, 18, x, self.height() - 18)
        if dashed:
            tip = QPolygon([QPoint(x, 8), QPoint(x - 5, 2), QPoint(x + 5, 2)])
        else:
            tip = QPolygon([QPoint(x, 8), QPoint(x - 5, 16), QPoint(x + 5, 16)])
        painter.setBrush(color if not dashed else Qt.NoBrush)
        painter.drawPolygon(tip)
        painter.drawText(x + 6, y_label, label)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), BG)
        _blit(painter, self.baked, self.start_ms, self.window_ms, self.rect())
        w, h = self.width(), self.height()
        end_ms = self.start_ms + self.window_ms

        if self.grid is not None:
            for t, beat in zip(self.grid.times, self.grid.beats):
                if t < self.start_ms or t > end_ms:
                    continue
                x = self._x_at(t)
                if beat == 1:
                    painter.setPen(QPen(QColor(250, 250, 250), 2))
                else:
                    painter.setPen(QPen(QColor(170, 170, 170, 140), 1))
                painter.drawLine(x, 16, x, h - 16)

        if self.cue is not None:
            color = cue_color(self.cue)
            self._marker(painter, self.cue.in_ms, color, False, f"{self.cue.label} now", 14)
            if self.proposed_in is not None and abs(self.proposed_in - self.cue.in_ms) > 1:
                moved = self.proposed_in - self.cue.in_ms
                self._marker(painter, self.proposed_in, color, True, f"snap {moved:+d} ms", 28)
            painter.setPen(QColor(160, 160, 160))
            painter.drawText(6, h - 6, f"{self.cue.in_ms / 1000:.2f}s    solid = now, dashed = after snap, thick line = downbeat")
