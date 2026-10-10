import os
import time
from collections import OrderedDict

from PySide6.QtCore import QEvent, QItemSelectionModel, QPoint, QPointF, QRectF, QSettings, QSize, QTimer, QUrl, Qt
from PySide6.QtGui import (
    QColor,
    QCursor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
)
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from relinkbox.analysis import read_beat_grid, read_waveform
from relinkbox.brand import apply_window_icon
from relinkbox.gui.fonts import ui_font as _ui_font
from relinkbox.cues import Verdict, apply_snaps, display_cues, scan_cues
from relinkbox.gui.waveform import CueOffsetRow, OverviewWaveform, TrackNavigator, bake_track, cue_color
from relinkbox.gui.workers import TaskRunner
from relinkbox.logs import log_dir
from relinkbox.rekordbox import is_rekordbox_running

COLUMNS = ("", "Track", "Length", "Type", "Cues", "Offset", "Cause", "Verdict")
COL_CHECK, COL_TRACK, COL_LENGTH, COL_TYPE, COL_CUES, COL_OFFSET, COL_CAUSE, COL_VERDICT = range(8)
SNAP_ROLE = Qt.UserRole + 1
ACCENT = "#FF910F"
INK = "#c4c4ca"
_PAD_W, _PAD_H = 53, 36
_EMPTY_PAD = (
    "QPushButton {"
    " background: #2a2a30; color: #8a8a92; font-weight: 700;"
    " border: 2px solid transparent; border-radius: 3px;"
    "}"
    "QPushButton:disabled { background: #2a2a30; color: #8a8a92; }"
)
FILTERS = (
    ("All tracks", None),
    ("Cues off grid", Verdict.CUES_WRONG),
    ("Grid looks off", Verdict.GRID_WRONG),
    ("Check manually", Verdict.UNCLEAR),
    ("On grid", Verdict.ON_GRID),
)
VERDICT_DOTS = {
    Verdict.ON_GRID: "#3dcc6e",
    Verdict.CUES_WRONG: "#ff5c5c",
    Verdict.GRID_WRONG: "#e2b340",
    Verdict.UNCLEAR: "#ff9a2e",
    Verdict.NO_GRID: "#8a8a90",
}
_THEME = """
QWidget#cueRoot { background: #121214; color: #c4c4ca; }
QLabel#summaryLabel { color: #b0b0b6; }
QLabel#titleLabel { color: #9a9aa0; }
QLabel#titleLabel[active="1"] { color: #FF910F; }
QLabel#genreLabel { color: #a3a3a8; }
QLabel#metaLabel, QLabel#reasonLabel, QLabel#waveLabel, QLabel#mutedLabel { color: #8e8e94; }
QLabel#statusLabel { color: #9a9aa2; background: transparent; }
QWidget#statusBar { background: transparent; border-top: 1px solid #2a2a2e; }
QPushButton#playerToggle { background: transparent; border: none; padding: 0; }
QLabel#rekordboxBanner {
    background: #4a3810; color: #ffe7b0; padding: 6px 10px; border-radius: 4px;
}
QLabel#clockLabel { color: #e2e2e6; background: transparent; }
QWidget#waveChrome { background-color: #121214; border-radius: 4px; }
QPushButton#scanButton {
    background: #FF910F; color: #1c1208; border: none; border-radius: 6px;
    padding: 0 14px; font-weight: 700;
}
QPushButton#scanButton:hover { background: #ff9f3a; }
QPushButton#scanButton:pressed { background: #e6830d; }
QPushButton#scanButton:disabled { background: #6a4e28; color: #f0d8b8; }
QPushButton#snapButton, QPushButton#choiceButton {
    background: #2a2a2e; color: #c4c4ca; border: 1px solid #3c3c42; border-radius: 6px; padding: 0 12px;
}
QPushButton#snapButton:hover, QPushButton#choiceButton:hover { background: #34343a; }
QPushButton#snapButton:disabled, QPushButton#choiceButton:disabled {
    background: #1c1c20; color: #8e8e96; border-color: #333338;
}
QPushButton#playButton {
    background: #FF910F; color: #1c1208; border: none; border-radius: 6px;
    padding: 0 14px; font-weight: 600;
}
QPushButton#playButton:hover { background: #ff9f3a; }
QPushButton#playButton:pressed { background: #e6830d; }
QPushButton#playButton:disabled { background: #6a4e28; color: #f0d8b8; }
QPushButton#zoomButton {
    background: #2c2c30; color: #e4e4e8; border: none; border-radius: 4px;
    font-weight: 700; padding: 0;
}
QPushButton#zoomButton:hover { background: #3e3e44; }
QPushButton#zoomButton:disabled { color: #5c5c62; background: #232326; }
QLineEdit, QComboBox {
    background: #1c1c20; color: #c4c4ca; border: 1px solid #34343a;
    border-radius: 6px; padding: 4px 10px; min-height: 22px;
}
QComboBox { padding-right: 26px; }
QLineEdit:focus, QComboBox:focus { border-color: #FF910F; }
QComboBox::drop-down {
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 22px; border: none;
}
QComboBox::down-arrow { image: url("__ARROW__"); width: 10px; height: 6px; }
QComboBox QAbstractItemView {
    background: #1c1c20; color: #c4c4ca; border: 1px solid #3a3a40;
    selection-background-color: #3a332c; outline: 0;
}
QTableWidget {
    background: #1c1c20; alternate-background-color: #242428; color: #c4c4ca;
    border: none; gridline-color: transparent; outline: 0;
    selection-background-color: #3a332c; selection-color: #c4c4ca;
}
QTableWidget::item { padding: 0 8px; border-bottom: 1px solid #2a2a2e; color: #c4c4ca; }
QTableWidget::item:selected { background: #3a332c; color: #c4c4ca; }
QHeaderView::section {
    background: #2c2c34; color: #c4c4ca; border: none;
    border-bottom: 1px solid #3a3a42; padding: 0 8px; font-weight: 700;
}
QWidget#cueRow { border-top: 1px solid #2a2a2e; background: transparent; }
QHeaderView::section:hover { background: #34343c; color: #c4c4ca; }
QTableWidget::indicator {
    width: 14px; height: 14px; border: 1px solid #5c5c64; border-radius: 3px; background: #1c1c20;
}
QTableWidget::indicator:checked { image: url("__CHECK__"); background: transparent; border: none; }
QSlider::groove:horizontal { height: 6px; background: #3a3a40; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #FF910F; border-radius: 3px; }
QSlider::handle:horizontal {
    background: #f2f2f2; border: none; width: 16px; height: 16px; margin: -5px 0; border-radius: 8px;
}
QProgressBar {
    background: #1c1c20; border: none; border-radius: 3px; max-height: 6px; color: transparent;
}
QProgressBar::chunk { background: #FF910F; border-radius: 3px; }
QScrollBar:vertical { background: #1c1c20; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3a3a40; border-radius: 4px; min-height: 24px; }
QScrollBar:horizontal { background: #1c1c20; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #3a3a40; border-radius: 4px; min-width: 24px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def _dark_palette():
    palette = QPalette()
    background = QColor("#121214")
    text = QColor(INK)
    palette.setColor(QPalette.ColorRole.Window, background)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor("#18181b"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#1c1c20"))
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, QColor("#2a2a2e"))
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#3a332c"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(INK))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#3a3a40"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#8a8a90"))
    return palette


def _polish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _use_ink(widget):
    palette = widget.palette()
    ink = QColor(INK)
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.HighlightedText,
    ):
        palette.setColor(role, ink)
    widget.setPalette(palette)


def _clock(ms, millis=False):
    ms = max(0, int(ms or 0))
    minutes, rem = divmod(ms, 60000)
    seconds, frac = divmod(rem, 1000)
    if millis:
        return f"{minutes:02d}:{seconds:02d}.{frac:03d}"
    return f"{minutes:02d}:{seconds:02d}"


def _checked_indicator():
    pix = QPixmap(14, 14)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(ACCENT))
    painter.drawRoundedRect(QRectF(0.5, 0.5, 13, 13), 3, 3)
    pen = QPen(QColor("#1c1208"), 1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.drawLine(QPointF(3.2, 7.2), QPointF(5.8, 10.0))
    painter.drawLine(QPointF(5.8, 10.0), QPointF(10.6, 4.2))
    painter.end()
    path = os.path.join(os.environ.get("TEMP", "."), "relinkbox-cue-check.png")
    pix.save(path, "PNG")
    return path.replace("\\", "/")


def _combo_arrow():
    pix = QPixmap(10, 6)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(QColor(INK), 1.4))
    painter.setBrush(Qt.NoBrush)
    painter.drawLine(QPointF(1, 1), QPointF(5, 5))
    painter.drawLine(QPointF(5, 5), QPointF(9, 1))
    painter.end()
    path = os.path.join(os.environ.get("TEMP", "."), "relinkbox-cue-arrow.png")
    pix.save(path, "PNG")
    return path.replace("\\", "/")


def _transport_icon(playing, enabled=True):
    pix = QPixmap(16, 16)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#161618") if enabled else QColor("#b4b4ba"))
    if playing:
        painter.drawRoundedRect(QRectF(3, 2, 3.4, 12), 1, 1)
        painter.drawRoundedRect(QRectF(9.6, 2, 3.4, 12), 1, 1)
    else:
        painter.drawPolygon(QPolygonF([QPointF(4.5, 2), QPointF(4.5, 14), QPointF(13.5, 8)]))
    painter.end()
    return QIcon(pix)


def _search_icon():
    pix = QPixmap(16, 16)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(QColor("#9a9aa2"), 1.5))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRectF(1.2, 1.2, 8.6, 8.6))
    painter.drawLine(QPointF(8.6, 8.6), QPointF(13.4, 13.4))
    painter.end()
    return QIcon(pix)


class VerdictDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        text = index.data(Qt.DisplayRole) or ""
        opt.text = ""
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        color = QColor(VERDICT_DOTS.get(text, "#8a8a90"))
        rect = opt.rect
        dot = 7
        cx = rect.left() + 8
        cy = rect.center().y() - dot / 2
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QRectF(cx, cy, dot, dot))
        painter.setPen(QColor(INK))
        painter.drawText(
            QRectF(cx + dot + 8, rect.top(), max(rect.width() - 28, 0), rect.height()),
            Qt.AlignVCenter | Qt.AlignLeft,
            text,
        )
        painter.restore()
        if index.column() < COL_VERDICT:
            _paint_column_rule(painter, opt.rect)


def _paint_column_rule(painter, rect):
    painter.fillRect(rect.right() - 1, rect.top(), 2, rect.height(), QColor(0, 0, 0, 77))


def _is_checked(value):
    """Model data returns 0 or 2, which does not compare equal to Qt.Checked."""
    if isinstance(value, Qt.CheckState):
        return value == Qt.CheckState.Checked
    return value == Qt.CheckState.Checked.value


def _paint_check(painter, rect, checked, enabled=True):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if not enabled:
        painter.setPen(QPen(QColor("#5c5c64"), 1.6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(
            QPointF(rect.left() + 2.5, rect.center().y()),
            QPointF(rect.right() - 2.5, rect.center().y()),
        )
        painter.restore()
        return
    if checked:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(ACCENT))
        painter.drawRoundedRect(QRectF(rect), 3, 3)
        pen = QPen(QColor("#1c1208"), 1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(QPointF(rect.left() + 3.2, rect.center().y()), QPointF(rect.left() + 5.8, rect.bottom() - 4))
        painter.drawLine(QPointF(rect.left() + 5.8, rect.bottom() - 4), QPointF(rect.right() - 3.2, rect.top() + 4.2))
    else:
        painter.setPen(QPen(QColor("#5c5c64"), 1))
        painter.setBrush(QColor("#1c1c20"))
        painter.drawRoundedRect(QRectF(rect).adjusted(0.5, 0.5, -0.5, -0.5), 3, 3)
    painter.restore()


class _CellDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() < COL_VERDICT:
            _paint_column_rule(painter, option.rect)


class _CheckDelegate(QStyledItemDelegate):
    """Centered checkbox with equal side padding, and a rule before the track name."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.features = opt.features & ~QStyleOptionViewItem.ViewItemFeature.HasCheckIndicator
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, widget)
        box = 14
        gutter = 2
        content = option.rect.adjusted(0, 0, -gutter, 0)
        x = content.left() + (content.width() - box) // 2
        y = content.top() + (content.height() - box) // 2
        can_snap = bool(index.data(SNAP_ROLE))
        _paint_check(
            painter,
            QRectF(x, y, box, box),
            _is_checked(index.data(Qt.CheckStateRole)) if can_snap else False,
            enabled=can_snap,
        )
        _paint_column_rule(painter, option.rect)

    def editorEvent(self, event, model, option, index):
        return False


class _BrowserHeader(QHeaderView):
    """Paints header labels in the same ink as the rows, with a faint vertical rule."""

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        hot = self.logicalIndexAt(self.mapFromGlobal(QCursor.pos())) == logicalIndex
        painter.fillRect(rect, QColor("#34343c" if hot else "#2c2c34"))
        painter.fillRect(rect.left(), rect.bottom(), rect.width(), 1, QColor("#3a3a42"))
        label = self.model().headerData(logicalIndex, Qt.Horizontal, Qt.DisplayRole) or ""
        painter.setPen(QColor(INK))
        painter.setFont(self.font())
        painter.drawText(rect.adjusted(6, 0, -6, 0), Qt.AlignCenter, str(label))
        if logicalIndex == self.sortIndicatorSection():
            ascending = self.sortIndicatorOrder() == Qt.AscendingOrder
            cx = rect.center().x() if logicalIndex == COL_CHECK else rect.right() - 10
            cy = rect.center().y()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(INK))
            if ascending:
                triangle = [QPointF(cx - 3.5, cy + 2), QPointF(cx + 3.5, cy + 2), QPointF(cx, cy - 2.5)]
            else:
                triangle = [QPointF(cx - 3.5, cy - 2), QPointF(cx + 3.5, cy - 2), QPointF(cx, cy + 2.5)]
            painter.drawPolygon(QPolygonF(triangle))
        if 0 < logicalIndex < self.count() - 1:
            rule = rect.adjusted(rect.width() - 2, 0, 0, 0)
            painter.fillRect(rule, QColor(130, 130, 138, 120))
        painter.restore()


class _BrowserTable(QTableWidget):
    """Clicks behave like a file list. A drag does not extend the highlight."""

    def __init__(self, owner):
        super().__init__(0, len(COLUMNS), owner)
        self._owner = owner
        self._press_index = None
        self._press_mods = Qt.NoModifier
        self._press_button = Qt.NoButton
        self._last_click_row = None
        self._last_click_at = 0.0
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.setDragEnabled(False)
        self.viewport().installEventFilter(self)

    def eventFilter(self, watched, event):
        try:
            viewport = self.viewport()
        except RuntimeError:
            return False
        if watched is viewport and self._take_browser_mouse(event):
            return True
        return super().eventFilter(watched, event)

    def _take_browser_mouse(self, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress and event.button() in (Qt.LeftButton, Qt.RightButton):
            self._press_index = self.indexAt(event.position().toPoint())
            self._press_mods = event.modifiers()
            self._press_button = event.button()
            self.setState(QAbstractItemView.State.NoState)
            return True
        if kind == QEvent.MouseMove and event.buttons() & (Qt.LeftButton | Qt.RightButton):
            self.setState(QAbstractItemView.State.NoState)
            return True
        if kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            self.setState(QAbstractItemView.State.NoState)
            return True
        if kind == QEvent.MouseButtonRelease and event.button() in (Qt.LeftButton, Qt.RightButton):
            release = self.indexAt(event.position().toPoint())
            press = self._press_index
            mods = self._press_mods
            button = self._press_button
            self._press_index = None
            self._press_button = Qt.NoButton
            self.setState(QAbstractItemView.State.NoState)
            same_row = press is not None and release is not None and press.row() == release.row()
            if button == Qt.RightButton and event.button() == Qt.RightButton and same_row:
                self._owner._toggle_player()
            elif button == Qt.LeftButton and event.button() == Qt.LeftButton and same_row and press.isValid():
                now = time.monotonic()
                interval = QApplication.styleHints().mouseDoubleClickInterval() / 1000
                plain = not (mods & (Qt.ControlModifier | Qt.ShiftModifier))
                if plain and self._last_click_row == press.row() and now - self._last_click_at <= interval:
                    self._last_click_row = None
                    self._owner._play_browser_row(press.row())
                else:
                    self._last_click_row = press.row() if plain else None
                    self._last_click_at = now
                    self._owner._browser_click(press.row(), press.column(), mods)
            return True
        return False

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._owner._fit_track_column()


class _PlayerToggle(QPushButton):
    """Small outline control on the player title line."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._open = False
        self.setFixedSize(36, 14)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)

    def set_open(self, open_):
        self._open = open_
        self.setToolTip("Hide player" if open_ else "Show player")
        self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        edge = QColor("#5c5c64") if self.underMouse() else QColor("#3a3a42")
        ink = QColor("#9a9aa2") if self.underMouse() else QColor("#5c5c64")
        painter.setPen(QPen(edge, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, 3, 3)
        painter.setPen(QPen(ink, 1.3))
        mid = self.width() / 2
        y = self.height() / 2
        if self._open:
            painter.drawLine(QPointF(mid - 5, y + 2), QPointF(mid, y - 2))
            painter.drawLine(QPointF(mid, y - 2), QPointF(mid + 5, y + 2))
        else:
            painter.drawLine(QPointF(mid - 5, y - 2), QPointF(mid, y + 2))
            painter.drawLine(QPointF(mid, y + 2), QPointF(mid + 5, y - 2))


class _WaveStage(QWidget):
    """Detail waveform with the clock and zoom buttons on its top-right corner."""

    def __init__(self, overview, parent=None):
        super().__init__(parent)
        self.overview = overview
        overview.setParent(self)
        self.setMinimumHeight(overview.minimumHeight())
        self.chrome = QWidget(self)
        self.chrome.setObjectName("waveChrome")
        self.chrome.setAttribute(Qt.WA_StyledBackground, True)
        self.chrome.setAutoFillBackground(True)
        chrome_palette = self.chrome.palette()
        chrome_palette.setColor(QPalette.ColorRole.Window, QColor("#121214"))
        self.chrome.setPalette(chrome_palette)
        row = QHBoxLayout(self.chrome)
        row.setContentsMargins(10, 4, 6, 4)
        row.setSpacing(6)
        self.clock = QLabel()
        self.clock.setObjectName("clockLabel")
        row.addWidget(self.clock)
        self.zoom_out = QPushButton("−")
        self.zoom_in = QPushButton("+")
        for button in (self.zoom_out, self.zoom_in):
            button.setObjectName("zoomButton")
            button.setFixedSize(22, 22)
            button.setFocusPolicy(Qt.NoFocus)
            button.setEnabled(False)
            row.addWidget(button)
        self.chrome.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_chrome()

    def place_chrome(self):
        self.overview.setGeometry(self.rect())
        self.chrome.adjustSize()
        self.chrome.move(max(0, self.width() - self.chrome.width() - 8), 6)
        self.chrome.raise_()

    def sizeHint(self):
        return QSize(640, max(self.minimumHeight(), 84))

    def minimumSizeHint(self):
        return QSize(240, self.minimumHeight())


class _ElidingLabel(QLabel):
    """One line of text that shortens with an ellipsis instead of wrapping."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self):
        return QSize(180, self.fontMetrics().height() + 2)

    def minimumSizeHint(self):
        return QSize(48, self.fontMetrics().height() + 2)

    def setText(self, text):
        self._full = text or ""
        self._apply()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply()

    def _apply(self):
        width = self.contentsRect().width()
        shown = self._full
        if width > 8:
            shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, width)
        if QLabel.text(self) != shown:
            QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")


class _ScanSummary(QWidget):
    """Scan result as two tight lines. A single sentence stays on one line."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setMinimumWidth(80)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.top = _ElidingLabel()
        self.bottom = _ElidingLabel()
        self.top.setObjectName("summaryLabel")
        self.bottom.setObjectName("summaryLabel")
        box.addWidget(self.top)
        box.addWidget(self.bottom)
        self.setText(text)

    def setText(self, text):
        text = text or ""
        cut = text.find(". ")
        if cut != -1 and cut < len(text) - 2:
            first, rest = text[: cut + 1], text[cut + 2 :]
        else:
            first, rest = text, ""
        self.top.setText(first)
        self.bottom.setText(rest)
        self.bottom.setVisible(bool(rest.strip()))


class _CoverArt(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = None
        self._radius = 8

    def clear(self):
        self._pix = None
        self.update()

    def setPixmap(self, pix):
        self._pix = pix
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)
        painter.fillRect(self.rect(), QColor("#1a1a1e"))
        if self._pix is not None and not self._pix.isNull():
            painter.drawPixmap(self.rect(), self._pix)
        painter.setClipping(False)
        painter.setPen(QPen(QColor("#2a2a2e"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, self._radius, self._radius)


class _BrowserFrame(QWidget):
    """Clips the results table to a rounded rectangle."""

    def __init__(self, table, parent=None):
        super().__init__(parent)
        self._table = table
        self._radius = 8
        table.setParent(self)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#1c1c20"))
        self.setPalette(palette)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._table.setGeometry(self.rect())
        self._apply_mask()

    def showEvent(self, event):
        super().showEvent(event)
        self._table.setGeometry(self.rect())
        self._apply_mask()

    def _apply_mask(self):
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def sizeHint(self):
        return self._table.sizeHint()

    def minimumSizeHint(self):
        return QSize(240, self.minimumHeight())


def _item(text, tooltip=None, align=None):
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    item.setForeground(QColor(INK))
    item.setToolTip(tooltip or text)
    if align is not None:
        item.setTextAlignment(align | Qt.AlignVCenter)
    return item


def _track_meta(report, duration_ms=None):
    parts = []
    if report.file_type:
        parts.append(report.file_type.upper())
    if report.bit_rate:
        parts.append(f"{report.bit_rate:,} kbps")
    if report.sample_rate:
        khz = f"{report.sample_rate / 1000:.1f}".rstrip("0").rstrip(".")
        parts.append(f"{khz} kHz")
    if duration_ms and duration_ms > 1000:
        parts.append(_clock(duration_ms))
    return "  ·  ".join(parts)


class CueManagerWindow(QMainWindow):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        apply_window_icon(self)
        self.db_path = db_path
        self.reports = []
        self.overrides = {}
        self.grid = None
        self.waveform = None
        self._audio_path = None
        self._seek_token = 0
        self._want_ms = None
        self._pending_load = False
        self._pending_play = False
        self._sort_col = COL_TRACK
        self._sort_desc = False
        self._loaded_track_id = None
        self._selection_anchor = None
        self._player_open = True
        self._track_fit = False
        self._player_dismissed = False
        self._wave_cache = OrderedDict()
        self._active_kind = None
        self._visible_cues = None
        self.settings = QSettings("Relinkbox", "Relinkbox")
        self.tasks = TaskRunner(self, self._set_busy, self._on_progress, self._failed)

        self.setWindowTitle("Cue points")
        self.setMinimumSize(1180, 800)
        self.resize(1320, 880)
        palette = _dark_palette()
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.setStyleSheet("QMainWindow { background: #121214; }")
        font = _ui_font(10)
        self.setFont(font)
        root = QWidget()
        root.setObjectName("cueRoot")
        root.setPalette(palette)
        root.setFont(font)
        root.setAutoFillBackground(True)
        root.setStyleSheet(
            _THEME.replace("__CHECK__", _checked_indicator()).replace("__ARROW__", _combo_arrow())
        )
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(8)
        self._root_layout = layout
        self.setCentralWidget(root)

        self.banner = QLabel(
            "Rekordbox is running. You can scan, but close Rekordbox before snapping any cues."
        )
        self.banner.setObjectName("rekordboxBanner")
        self.banner.setWordWrap(True)
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.setAlignment(Qt.AlignVCenter)
        self.scan_button = QPushButton("Scan library")
        self.scan_button.setObjectName("scanButton")
        self.scan_button.setFixedHeight(32)
        self.scan_button.setCursor(Qt.PointingHandCursor)
        self.scan_button.clicked.connect(self.scan)
        top.addWidget(self.scan_button)
        self.filter = QComboBox()
        self.filter.setFixedHeight(32)
        self.filter.setMinimumWidth(132)
        for label, _value in FILTERS:
            self.filter.addItem(label)
        self.filter.currentIndexChanged.connect(self._fill_table)
        top.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tracks...")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(200)
        self.search.setFixedHeight(32)
        self.search.addAction(_search_icon(), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._fill_table)
        top.addWidget(self.search)
        self.summary = _ScanSummary("Scan the library to compare cue points with each track's beat grid.")
        top.addWidget(self.summary, 1)
        self.snap_button = QPushButton("Snap selected")
        self.snap_button.setObjectName("snapButton")
        self.snap_button.setFixedHeight(32)
        self.snap_button.setEnabled(False)
        self.snap_button.clicked.connect(self.snap_selected)
        _use_ink(self.filter)
        _use_ink(self.snap_button)
        top.addWidget(self.snap_button)
        layout.addLayout(top)

        self.table = _BrowserTable(self)
        self.table.setHorizontalHeader(_BrowserHeader(Qt.Horizontal, self.table))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        table_font = _ui_font(11)
        self.table.setFont(table_font)
        _use_ink(self.table)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setFrameShape(QTableWidget.Shape.NoFrame)
        self.table.setItemDelegate(_CellDelegate(self.table))
        self.table.setItemDelegateForColumn(COL_CHECK, _CheckDelegate(self.table))
        self.table.setItemDelegateForColumn(COL_VERDICT, VerdictDelegate(self.table))
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(24)
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(COL_CHECK, QHeaderView.Fixed)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(COL_TRACK, Qt.AscendingOrder)
        header_font = _ui_font(11, bold=True)
        header.setFont(header_font)
        header.setDefaultAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        header.setFixedHeight(32)
        for index in range(len(COLUMNS)):
            self.table.horizontalHeaderItem(index).setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        header.sectionClicked.connect(self._sort_by)
        self.table.itemChanged.connect(self._update_snap_button)
        self.table.setColumnWidth(COL_CHECK, 36)
        self.table.setColumnWidth(COL_LENGTH, 76)
        self.table.setColumnWidth(COL_TYPE, 92)
        self.table.setColumnWidth(COL_CUES, 72)
        self.table.setColumnWidth(COL_OFFSET, 124)
        self.table.setColumnWidth(COL_CAUSE, 168)
        self.table.setColumnWidth(COL_VERDICT, 224)
        self.browser = _BrowserFrame(self.table)
        self.browser.setMinimumHeight(30 * 6 + 32)
        layout.addWidget(self.browser, 1)
        self._table_index = layout.count() - 1

        title_row = QHBoxLayout()
        title_row.setSpacing(12)
        title_row.setAlignment(Qt.AlignVCenter)
        self.detail_title = QLabel("Select a track to see its waveform and cues.")
        self.detail_title.setObjectName("titleLabel")
        self.detail_title.setWordWrap(True)
        title_font = _ui_font(15, bold=True)
        self.detail_title.setFont(title_font)
        self.detail_genre = QLabel()
        self.detail_genre.setObjectName("genreLabel")
        secondary = _ui_font(10)
        self.detail_genre.setFont(secondary)
        self.detail_genre.hide()
        self.detail_meta = QLabel()
        self.detail_meta.setObjectName("metaLabel")
        self.detail_meta.setFont(secondary)
        self.detail_meta.hide()
        text_block = (
            self.detail_title.fontMetrics().height()
            + self.detail_genre.fontMetrics().height()
            + self.detail_meta.fontMetrics().height()
        )
        self.cover_size = int(round(text_block * 1.5 * 1.15))
        inset = 10
        self.art = _CoverArt()
        self.art.setObjectName("coverArt")
        self.art.setFixedSize(self.cover_size, self.cover_size)
        self.art.hide()
        title_row.addWidget(self.art, 0, Qt.AlignVCenter)
        title_text = QVBoxLayout()
        title_text.setSpacing(max(4, (self.cover_size - text_block - 2 * inset) // 2))
        title_text.setContentsMargins(0, inset, 0, inset)
        title_line = QHBoxLayout()
        title_line.setContentsMargins(0, 0, 0, 0)
        title_line.setSpacing(8)
        title_line.addWidget(self.detail_title, 1)
        self._title_toggle_gap = QWidget()
        self._title_toggle_gap.setFixedSize(36, 14)
        title_line.addWidget(self._title_toggle_gap, 0, Qt.AlignVCenter)
        title_text.addLayout(title_line)
        spec = QVBoxLayout()
        spec.setSpacing(3)
        spec.setContentsMargins(0, 0, 0, 0)
        spec.addWidget(self.detail_genre)
        spec.addWidget(self.detail_meta)
        title_text.addLayout(spec)
        text_box = QWidget()
        text_box.setLayout(title_text)
        title_row.addWidget(text_box, 1, Qt.AlignVCenter)
        side = QVBoxLayout()
        side.setSpacing(4)
        side.setContentsMargins(0, 0, 0, 0)
        overrides = QHBoxLayout()
        overrides.setSpacing(8)
        overrides.setContentsMargins(0, 0, 0, 0)
        choice_font = _ui_font(10)
        choice_font.setPointSizeF(10.5)
        self.cues_right_button = QPushButton("The cues are right")
        self.cues_right_button.setObjectName("choiceButton")
        self.cues_right_button.setFont(choice_font)
        self.cues_right_button.setFixedHeight(31)
        self.cues_right_button.setToolTip("Keep the cues. The beat grid is probably wrong.")
        self.cues_right_button.clicked.connect(lambda: self._override(Verdict.GRID_WRONG))
        self.grid_right_button = QPushButton("The grid is right")
        self.grid_right_button.setObjectName("choiceButton")
        self.grid_right_button.setFont(choice_font)
        self.grid_right_button.setFixedHeight(31)
        self.grid_right_button.setToolTip("Snap the cues onto the beat grid.")
        self.grid_right_button.clicked.connect(lambda: self._override(Verdict.CUES_WRONG))
        self.cues_right_button.setEnabled(False)
        self.grid_right_button.setEnabled(False)
        overrides.addWidget(self.cues_right_button)
        overrides.addWidget(self.grid_right_button)
        side.addLayout(overrides)
        reason_width = (
            self.cues_right_button.sizeHint().width() + self.grid_right_button.sizeHint().width() + 8
        )
        self.detail_reason = QLabel()
        self.detail_reason.setObjectName("reasonLabel")
        self.detail_reason.setFont(secondary)
        self.detail_reason.setWordWrap(True)
        self.detail_reason.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.detail_reason.setFixedWidth(reason_width)
        side.addWidget(self.detail_reason)
        title_row.addLayout(side, 0)

        self._player_toggle = _PlayerToggle(root)
        self._player_toggle.setObjectName("playerToggle")
        self._player_toggle.clicked.connect(self._toggle_player)
        self._player_toggle.set_open(True)
        self._player_toggle.hide()

        self._player_panel = QWidget()
        player_layout = QVBoxLayout(self._player_panel)
        player_layout.setContentsMargins(0, 2, 0, 0)
        player_layout.setSpacing(8)
        player_layout.addLayout(title_row)

        self.navigator = TrackNavigator()
        self.navigator.setFixedHeight(44)
        self.navigator.clicked.connect(lambda ms: self.jump_to(ms, center=True))
        self.navigator.scrubbed.connect(lambda ms: self.jump_to(ms, center=True))
        self.overview = OverviewWaveform()
        self.overview.clicked.connect(self.jump_to)
        self.overview.view_changed.connect(self.navigator.set_view)
        self.overview.scrubbed.connect(self._scrub)
        self.wave_stage = _WaveStage(self.overview)
        self.wave_stage.zoom_in.clicked.connect(lambda: self.overview.zoom_step(1.25))
        self.wave_stage.zoom_out.clicked.connect(lambda: self.overview.zoom_step(1 / 1.25))
        context = QVBoxLayout()
        context.setSpacing(4)
        context.setContentsMargins(0, 2, 0, 0)
        context.addWidget(self.navigator)
        context.addWidget(self.wave_stage, 1)
        player_layout.addLayout(context, 1)

        self.offsets = CueOffsetRow()
        cue_row = QHBoxLayout()
        cue_row.setSpacing(0)
        cue_row.setContentsMargins(0, 8, 0, 0)
        cue_row.addWidget(self.offsets)
        self.cue_row = QWidget()
        self.cue_row.setObjectName("cueRow")
        self.cue_row.setAttribute(Qt.WA_StyledBackground, True)
        self.cue_row.setLayout(cue_row)
        self.cue_row.hide()
        player_layout.addWidget(self.cue_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setVisible(False)

        footer = QHBoxLayout()
        footer.setSpacing(10)
        footer.setContentsMargins(0, 2, 0, 0)
        pads = QWidget()
        pad_row = QHBoxLayout(pads)
        pad_row.setContentsMargins(0, 0, 0, 0)
        pad_row.setSpacing(3)
        self.pad_buttons = {}
        for kind, letter in ((1, "A"), (2, "B"), (3, "C"), (5, "D"), (6, "E"), (7, "F"), (8, "G"), (9, "H")):
            button = QPushButton(letter)
            button.setFixedSize(_PAD_W, _PAD_H)
            button.setEnabled(False)
            button.setAutoRepeat(False)
            button.setFocusPolicy(Qt.NoFocus)
            button.setStyleSheet(_EMPTY_PAD)
            button.pressed.connect(lambda k=kind: self._pad_pressed(k))
            button.released.connect(lambda k=kind: self._pad_released(k))
            pad_row.addWidget(button)
            self.pad_buttons[kind] = button
        footer.addWidget(pads, 0, Qt.AlignVCenter)
        footer.addStretch(1)
        vol_label = QLabel("Vol")
        vol_label.setObjectName("mutedLabel")
        vol_label.setFont(secondary)
        footer.addWidget(vol_label, 0, Qt.AlignVCenter)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(int(self.settings.value("cue_volume", 40)))
        self.volume.setFixedWidth(176)
        self.volume.setFixedHeight(24)
        self.volume.valueChanged.connect(self._set_volume)
        footer.addWidget(self.volume, 0, Qt.AlignVCenter)
        self.play_button = QPushButton("Play")
        self.play_button.setObjectName("playButton")
        self.play_button.setFixedHeight(_PAD_H)
        self.play_button.setMinimumWidth(92)
        self.play_button.setIconSize(QSize(14, 14))
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(False)
        self._sync_play_button(False)
        footer.addWidget(self.play_button, 0, Qt.AlignVCenter)
        player_layout.addLayout(footer)
        layout.addWidget(self._player_panel, 0)
        self._player_index = layout.count() - 1
        layout.addWidget(self.progress_bar)
        self.status_label = _ElidingLabel()
        self.status_label.setObjectName("statusLabel")
        self.status_label.setFont(secondary)
        status_bar = QWidget()
        status_bar.setObjectName("statusBar")
        status_bar.setAttribute(Qt.WA_StyledBackground, True)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(2, 6, 2, 0)
        status_layout.setSpacing(0)
        status_layout.addWidget(self.status_label)
        layout.addWidget(status_bar)
        self._apply_section_stretch(False)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self._set_volume(self.volume.value())
        self.playhead_timer = QTimer(self)
        self.playhead_timer.setInterval(33)
        self.playhead_timer.timeout.connect(self._tick_playhead)
        self.player.playbackStateChanged.connect(self._play_state_changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.metaDataChanged.connect(self._update_art)

        self.busy_widgets = [self.scan_button, self.filter, self.search, self.snap_button]
        self.rekordbox_timer = QTimer(self)
        self.rekordbox_timer.timeout.connect(self._check_rekordbox)
        self.rekordbox_timer.start(4000)
        self._check_rekordbox()

    def showEvent(self, event):
        QApplication.instance().installEventFilter(self)
        self._dark_titlebar()
        super().showEvent(event)
        QTimer.singleShot(0, self._place_player_toggle)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_player_toggle()

    def _dark_titlebar(self):
        if os.name != "nt":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            return

    def hideEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):
        if self.isActiveWindow() and event.type() in (QEvent.KeyPress, QEvent.ShortcutOverride):
            if event.key() == Qt.Key_Space and not event.modifiers():
                focus = QApplication.focusWidget()
                if isinstance(focus, QLineEdit):
                    return super().eventFilter(obj, event)
                if event.type() == QEvent.KeyPress and not event.isAutoRepeat():
                    self.toggle_play()
                event.accept()
                return True
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        if self.tasks.busy:
            QMessageBox.information(self, "Still working", "Please wait for the current task to finish.")
            event.ignore()
            return
        self._release_player()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        event.accept()

    def _set_busy(self, busy, text=""):
        for widget in self.busy_widgets:
            widget.setEnabled(not busy)
        self.table.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        self.progress_bar.setValue(0)
        self.status_label.setText(text)
        if not busy:
            self._update_snap_button()

    def _on_progress(self, percent, text):
        self.progress_bar.setValue(percent)
        if text:
            self.status_label.setText(text)

    def _failed(self, message):
        self.status_label.setText("Something went wrong.")
        QMessageBox.critical(
            self,
            "Something went wrong",
            f"{message}\n\nNothing was saved to your library.\n\nDetails are in the log: {log_dir()}",
        )

    def _check_rekordbox(self):
        self.banner.setVisible(is_rekordbox_running())

    def scan(self):
        self._release_player()
        self.tasks.run(scan_cues, (self.db_path,), self._show_reports, "Scanning cue points...")

    def _show_reports(self, reports):
        self.reports = reports
        self.overrides = {}
        counts = {}
        for report in reports:
            counts[report.verdict] = counts.get(report.verdict, 0) + 1
        parts = [f"{len(reports):,} tracks with cues"]
        for verdict in (Verdict.CUES_WRONG, Verdict.GRID_WRONG, Verdict.UNCLEAR, Verdict.ON_GRID):
            if counts.get(verdict):
                parts.append(f"{counts[verdict]:,} {verdict.lower()}")
        self.summary.setText(". ".join(parts) + ".")
        self._fill_table()
        self.table.clearSelection()
        self._clear_detail()
        self.status_label.setText("Scan finished. Nothing has been changed yet.")

    def _sort_by(self, column):
        if column == self._sort_col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = column
            # Checked rows are the useful end of this column, so the first click brings them up.
            self._sort_desc = column == COL_CHECK
        self.table.horizontalHeader().setSortIndicator(
            column, Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder
        )
        if self.table.rowCount():
            self._reorder_table()
        else:
            self._fill_table()

    def _sort_key(self, report, check_item=None):
        if self._sort_col == COL_CHECK:
            if not report.proposed:
                return 0
            if check_item is not None:
                return 2 if _is_checked(check_item.checkState()) else 1
            return 2 if self._should_tick(report) else 1
        if self._sort_col == COL_LENGTH:
            return report.length_sec or 0
        if self._sort_col == COL_TYPE:
            return report.file_type or ""
        if self._sort_col == COL_CUES:
            return len(report.cues)
        if self._sort_col == COL_OFFSET:
            return report.offset if report.offset is not None else float("inf")
        if self._sort_col == COL_CAUSE:
            return report.cause.lower()
        if self._sort_col == COL_VERDICT:
            return self._verdict(report)
        return report.label.lower()

    def _visible_reports(self):
        wanted = FILTERS[self.filter.currentIndex()][1]
        query = self.search.text().strip().lower()
        rows = []
        for i, report in enumerate(self.reports):
            if wanted is not None and report.verdict != wanted:
                continue
            if query and query not in report.label.lower() and query not in (report.path or "").lower():
                continue
            rows.append((i, report))
        rows.sort(key=lambda item: self._sort_key(item[1]), reverse=self._sort_desc)
        return rows

    def _reorder_table(self):
        cols = self.table.columnCount()
        selected = set()
        anchor_id = None
        for row in self._highlighted_rows():
            item = self.table.item(row, COL_CHECK)
            if item is not None:
                selected.add(item.data(Qt.UserRole))
        if self._selection_anchor is not None:
            anchor_item = self.table.item(self._selection_anchor, COL_CHECK)
            if anchor_item is not None:
                anchor_id = anchor_item.data(Qt.UserRole)
        packed = []
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            cells = [self.table.takeItem(row, col) for col in range(cols)]
            if cells[0] is None:
                continue
            index = cells[0].data(Qt.UserRole)
            packed.append((self._sort_key(self.reports[index], cells[0]), cells))
        packed.sort(key=lambda item: item[0], reverse=self._sort_desc)
        for row, (_key, cells) in enumerate(packed):
            for col, cell in enumerate(cells):
                self.table.setItem(row, col, cell)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        rows = []
        self._selection_anchor = None
        for row in range(self.table.rowCount()):
            identity = self.table.item(row, COL_CHECK).data(Qt.UserRole)
            if identity in selected:
                rows.append(row)
            if anchor_id is not None and identity == anchor_id:
                self._selection_anchor = row
        self._select_rows(rows)
        self._update_snap_button()

    def _fill_table(self):
        rows = self._visible_reports()
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for row, (index, report) in enumerate(rows):
            check = QTableWidgetItem()
            can_snap = bool(report.proposed)
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if can_snap:
                flags |= Qt.ItemIsUserCheckable
            check.setFlags(flags)
            check.setCheckState(Qt.Checked if self._should_tick(report) else Qt.Unchecked)
            check.setData(Qt.UserRole, index)
            check.setData(SNAP_ROLE, can_snap)
            if not can_snap:
                check.setToolTip("Nothing to snap on this track.")
            self.table.setItem(row, COL_CHECK, check)
            self.table.setItem(row, COL_TRACK, _item(report.label, report.path))
            length = _clock(report.length_sec * 1000) if report.length_sec else ""
            self.table.setItem(row, COL_LENGTH, _item(length, align=Qt.AlignHCenter))
            kind = _item(report.file_type or "?")
            kind.setForeground(QColor("#9a9aa2"))
            kind.setTextAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.table.setItem(row, COL_TYPE, kind)
            self.table.setItem(row, COL_CUES, _item(str(len(report.cues)), align=Qt.AlignHCenter))
            offset = f"{report.offset:+.0f} ms" if report.offset is not None else ""
            self.table.setItem(row, COL_OFFSET, _item(offset, align=Qt.AlignHCenter))
            self.table.setItem(row, COL_CAUSE, _item(report.cause))
            self.table.setItem(row, COL_VERDICT, _item(self._verdict(report), report.reason))
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._update_snap_button()
        if not rows:
            self._clear_detail()

    def _verdict(self, report):
        return self.overrides.get(report.track_id, report.verdict)

    def _should_tick(self, report):
        return self._verdict(report) == Verdict.CUES_WRONG and bool(report.proposed)

    def _selected_report(self):
        if self._loaded_track_id is None:
            return None
        for report in self.reports:
            if report.track_id == self._loaded_track_id:
                return report
        return None

    def _show_loaded(self, report):
        path = report.path if report.path and os.path.isfile(report.path) else None
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        same_audio = bool(playing and path and self._current_source() == path.replace("\\", "/"))
        if not playing:
            self._release_player()
        self.detail_title.setText(report.label)
        self._set_title_active(True)
        genre = (report.genre or "").strip()
        self.detail_genre.setText(genre)
        self.detail_genre.setVisible(bool(genre))
        extra = " You marked the grid as right." if self.overrides.get(report.track_id) == Verdict.CUES_WRONG else ""
        extra = " You marked the cues as right." if self.overrides.get(report.track_id) == Verdict.GRID_WRONG else extra
        self._set_reason((report.reason or "Cues sit on the beat grid.") + extra)
        has_choice = bool(report.proposed)
        self.cues_right_button.setEnabled(has_choice)
        self.grid_right_button.setEnabled(has_choice)

        visuals = self._visuals_for(report)
        self.grid = visuals["grid"]
        self.waveform = visuals["waveform"]
        visible = display_cues(report.cues)
        self.overview.set_data(
            self.waveform,
            visible,
            visuals["duration"],
            proposed=report.proposed,
            grid=self.grid,
        )
        self.navigator.set_data(visuals["overview"], visible, visuals["duration"])
        self.offsets.set_data(self.waveform, self.grid, visible)
        self._sync_cue_row()
        self._apply_section_stretch(True)
        if same_audio:
            heard = self.player.position()
            self.overview.set_playhead(heard)
            self.navigator.set_playhead(heard)
            self._sync_clock(heard)
        else:
            self._want_ms = None
            self._pending_load = False
            self._pending_play = False
            self.overview.set_playhead(None)
            self.navigator.set_playhead(None)
            self._sync_clock(0)
            self.overview.set_live(False)
        meta = _track_meta(report, visuals["duration"])
        self.detail_meta.setText(meta)
        self.detail_meta.setVisible(bool(meta))
        can_zoom = visuals["duration"] > 1
        self.wave_stage.zoom_in.setEnabled(can_zoom)
        self.wave_stage.zoom_out.setEnabled(can_zoom)
        self._rebuild_cue_buttons(visible)
        self._audio_path = path
        self.play_button.setEnabled(bool(self._audio_path))
        self._sync_play_button(playing)
        if not playing:
            self._preload_audio()
        elif not same_audio:
            self.art.clear()
        self.art.show()

    def _visuals_for(self, report):
        cached = self._wave_cache.get(report.track_id)
        if cached is not None:
            self._wave_cache.move_to_end(report.track_id)
            return cached
        grid = None
        waveform = None
        if report.dat_path:
            try:
                grid = read_beat_grid(report.dat_path)
            except Exception:
                grid = None
        if report.ext_path or report.twoex_path:
            try:
                waveform = read_waveform(report.ext_path, report.twoex_path)
            except Exception:
                waveform = None
        if grid and grid.times:
            duration = int(grid.times[-1])
        elif waveform is not None and len(waveform.heights):
            duration = max(int(waveform.time(len(waveform.heights) - 1)), 1)
        else:
            duration = 1
        pack = {
            "grid": grid,
            "waveform": waveform,
            "overview": bake_track(waveform, duration),
            "duration": duration,
        }
        self._wave_cache[report.track_id] = pack
        while len(self._wave_cache) > 12:
            self._wave_cache.popitem(last=False)
        return pack

    def _clear_detail(self):
        self._loaded_track_id = None
        self._release_player()
        self._audio_path = None
        self.detail_title.setText("Select a track to see its waveform and cues.")
        self._set_title_active(False)
        self.detail_genre.clear()
        self.detail_genre.hide()
        self.detail_meta.clear()
        self.detail_meta.hide()
        self._set_reason("")
        self.art.clear()
        self.art.hide()
        self.cues_right_button.setEnabled(False)
        self.grid_right_button.setEnabled(False)
        self.overview.set_data(None, [])
        self.navigator.set_data(None, [], 1)
        self.offsets.set_data(None, None, [])
        self._sync_cue_row()
        self._apply_section_stretch(False)
        self._rebuild_cue_buttons(None)
        self.wave_stage.zoom_in.setEnabled(False)
        self.wave_stage.zoom_out.setEnabled(False)
        self.wave_stage.chrome.hide()
        self.play_button.setEnabled(False)
        self._sync_play_button(False)
        QTimer.singleShot(0, self._place_player_toggle)

    def _fit_track_column(self):
        """Give leftover width to Track. Other columns keep the width the user dragged."""
        table = getattr(self, "table", None)
        if table is None or self._track_fit:
            return
        header = table.horizontalHeader()
        width = table.viewport().width()
        if width < 80 or header.count() <= COL_TRACK:
            return
        others = sum(header.sectionSize(index) for index in range(header.count()) if index != COL_TRACK)
        size = max(160, width - others)
        if abs(header.sectionSize(COL_TRACK) - size) < 2:
            return
        self._track_fit = True
        header.resizeSection(COL_TRACK, size)
        self._track_fit = False

    def _apply_section_stretch(self, has_track):
        height = 168 if has_track else 88
        self.overview.setMinimumHeight(height)
        self.wave_stage.setMinimumHeight(height)
        if not self._player_open:
            self._root_layout.setStretch(self._table_index, 1)
            self._root_layout.setStretch(self._player_index, 0)
            return
        self._root_layout.setStretch(self._table_index, 4 if has_track else 1)
        self._root_layout.setStretch(self._player_index, 3 if has_track else 0)

    def _set_player_open(self, open_):
        self._player_open = open_
        self._player_panel.setVisible(open_)
        self._player_toggle.set_open(open_)
        self._player_toggle.show()
        self._apply_section_stretch(self._loaded_track_id is not None)
        QTimer.singleShot(0, self._place_player_toggle)

    def _place_player_toggle(self):
        button = getattr(self, "_player_toggle", None)
        browser = getattr(self, "browser", None)
        root = self.centralWidget()
        if button is None or browser is None or root is None:
            return
        if self._player_open and self._player_panel.isVisible() and self._title_toggle_gap.isVisible():
            pos = self._title_toggle_gap.mapTo(root, QPoint(0, 0))
            if self._title_toggle_gap.width() > 1 and pos.y() > 0:
                button.move(pos)
                button.show()
                button.raise_()
                return
        if browser.height() < 20:
            return
        origin = browser.mapTo(root, QPoint(0, 0))
        x = origin.x() + max(0, (browser.width() - button.width()) // 2)
        y = origin.y() + browser.height() - button.height() // 2
        button.move(x, y)
        button.show()
        button.raise_()

    def _toggle_player(self):
        if self._player_open:
            self._player_dismissed = True
            self._set_player_open(False)
            return
        self._set_player_open(True)

    def _highlighted_rows(self):
        return sorted({item.row() for item in self.table.selectedItems()})

    def _select_rows(self, rows):
        model = self.table.selectionModel()
        model.clearSelection()
        if not rows:
            return
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row in rows:
            model.select(self.table.model().index(row, 0), flags)

    def _browser_click(self, row, column, modifiers):
        ctrl = bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers & Qt.ShiftModifier)
        if column == COL_CHECK and not ctrl and not shift:
            if self._row_can_snap(row):
                self._toggle_highlighted_checks(row)
            else:
                self._plain_click_row(row)
            return
        if ctrl:
            self._ctrl_click_row(row)
            return
        if shift:
            self._shift_click_row(row)
            return
        self._plain_click_row(row)

    def _plain_click_row(self, row):
        self._selection_anchor = row
        self._select_rows([row])
        self._load_row(row)

    def _play_browser_row(self, row):
        self._plain_click_row(row)
        if self._audio_path:
            self.play_from(0)

    def _shift_click_row(self, row):
        anchor = row if self._selection_anchor is None else self._selection_anchor
        start, end = sorted((anchor, row))
        self._select_rows(list(range(start, end + 1)))

    def _ctrl_click_row(self, row):
        highlighted = self._highlighted_rows()
        item = self.table.item(row, COL_CHECK)
        if item is None:
            return
        if row in highlighted:
            highlighted.remove(row)
            self._select_rows(highlighted)
            return
        highlighted.append(row)
        self._select_rows(highlighted)

    def _toggle_highlighted_checks(self, row):
        highlighted = self._highlighted_rows()
        if row not in highlighted:
            self._plain_click_row(row)
            highlighted = [row]
        item = self.table.item(row, COL_CHECK)
        if item is None:
            return
        checking = item.checkState() != Qt.Checked
        state = Qt.Checked if checking else Qt.Unchecked
        for each in highlighted:
            if not self._row_can_snap(each):
                continue
            cell = self.table.item(each, COL_CHECK)
            if cell is not None:
                cell.setCheckState(state)
        self.table.viewport().update()

    def _load_row(self, row):
        item = self.table.item(row, COL_CHECK)
        if item is None:
            return
        report = self.reports[item.data(Qt.UserRole)]
        self._loaded_track_id = report.track_id
        self._show_loaded(report)
        if self._player_open or not self._player_dismissed:
            self._set_player_open(True)

    def _sync_cue_row(self):
        self.cue_row.setVisible(bool(self.offsets.cues))

    def _set_reason(self, text):
        self.detail_reason.setText(text or "")
        if not text:
            self.detail_reason.setMinimumHeight(0)
            return
        width = self.detail_reason.maximumWidth()
        if width < 40:
            width = self.detail_reason.sizeHint().width()
        self.detail_reason.setMinimumHeight(self.detail_reason.heightForWidth(width))

    def _set_title_active(self, active):
        self.detail_title.setProperty("active", "1" if active else "0")
        _polish(self.detail_title)

    def _sync_clock(self, ms=None):
        duration = self.overview.duration_ms
        if duration <= 1:
            self.wave_stage.chrome.hide()
            return
        if ms is None:
            ms = 0 if self.overview.playhead_ms is None else self.overview.playhead_ms
        self.wave_stage.clock.setText(f"{_clock(ms, True)}  /  {_clock(duration, True)}")
        if self.wave_stage.chrome.isVisible():
            return
        self.wave_stage.chrome.show()
        self.wave_stage.place_chrome()

    def _style_pad(self, button, cue, active=False):
        color = cue_color(cue)
        luma = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        fg = "#111" if luma > 150 else "#e4e4e8"
        border = "#f4f4f5" if active else "transparent"
        button.setStyleSheet(
            "QPushButton {"
            f" background: {color.name()}; color: {fg}; font-weight: 700;"
            f" border: 2px solid {border}; border-radius: 3px;"
            "}"
        )

    def _rebuild_cue_buttons(self, cues):
        self._visible_cues = list(cues) if cues else None
        self._active_kind = None
        self._apply_pad_styles()

    def _apply_pad_styles(self):
        by_kind = {cue.kind: cue for cue in (self._visible_cues or []) if cue.kind != 0}
        for kind, button in self.pad_buttons.items():
            cue = by_kind.get(kind)
            button.setEnabled(bool(cue))
            if cue:
                self._style_pad(button, cue, active=kind == self._active_kind)
                button.setProperty("cue_ms", cue.in_ms)
            else:
                button.setStyleSheet(_EMPTY_PAD)
                button.setProperty("cue_ms", None)

    def _pad_pressed(self, kind):
        ms = self.pad_buttons[kind].property("cue_ms")
        if ms is None:
            return
        ms = int(ms)
        self._active_kind = kind
        self._apply_pad_styles()
        self.offsets.set_active(kind)
        self.overview.center_on(ms)
        self.play_from(ms)

    def _pad_released(self, kind):
        ms = self.pad_buttons[kind].property("cue_ms")
        if ms is None:
            return
        self._pending_play = False
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        self.jump_to(int(ms), center=True)

    def _set_volume(self, value):
        self.audio.setVolume(max(0.0, min(1.0, value / 100)))
        self.settings.setValue("cue_volume", int(value))

    def _release_player(self):
        self._seek_token += 1
        self._want_ms = None
        self._pending_load = False
        self._pending_play = False
        self.playhead_timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.art.clear()
        self.art.hide()

    def _current_source(self):
        return self.player.source().toLocalFile().replace("\\", "/")

    def _source_is_ready(self):
        if not self._audio_path:
            return False
        if self._current_source() != self._audio_path.replace("\\", "/"):
            return False
        return self.player.mediaStatus() in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferingMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.EndOfMedia,
        )

    def _preload_audio(self):
        self._pending_load = False
        self._pending_play = False
        self._want_ms = None
        self.player.stop()
        self.art.clear()
        self.art.hide()
        if not self._audio_path:
            self.player.setSource(QUrl())
            return
        if self._current_source() != self._audio_path.replace("\\", "/"):
            self.player.setSource(QUrl.fromLocalFile(self._audio_path))

    def _warm_visible(self):
        """Open the track on screen once the current one has stopped, so Play does not wait."""
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        if not self._audio_path or self._pending_play:
            return
        norm = self._audio_path.replace("\\", "/")
        if self._current_source() == norm:
            return
        self._pending_load = True
        self._pending_play = False
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(self._audio_path))

    def _update_art(self):
        if not self._visible_audio_loaded() and self._audio_path:
            return
        self._apply_cover(self.player)

    def _apply_cover(self, player):
        meta = player.metaData()
        image = None
        for key in (QMediaMetaData.Key.CoverArtImage, QMediaMetaData.Key.ThumbnailImage):
            value = meta.value(key)
            if value is None:
                continue
            if hasattr(value, "isNull") and value.isNull():
                continue
            image = value
            break
        if image is None or not isinstance(image, (QPixmap, QImage)):
            self.art.clear()
            self.art.setVisible(self._selected_report() is not None)
            return
        pix = image if isinstance(image, QPixmap) else QPixmap.fromImage(image)
        side = self.cover_size
        scaled = pix.scaled(side, side, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - side) // 2)
        y = max(0, (scaled.height() - side) // 2)
        self.art.setPixmap(scaled.copy(x, y, side, side))
        self.art.show()

    def jump_to(self, ms, center=False):
        if not self._audio_path and self.waveform is None:
            return
        ms = int(ms)
        self._want_ms = ms
        if center:
            self.overview.center_on(ms)
        self.overview.set_playhead(ms)
        self.navigator.set_playhead(ms)
        self._sync_clock(ms)
        if self._source_is_ready():
            self.player.setPosition(ms)

    def play_from(self, ms):
        if not self._audio_path:
            return
        self._want_ms = int(ms)
        self._pending_play = True
        self.overview.set_playhead(self._want_ms, follow=True)
        self.navigator.set_playhead(self._want_ms)
        self._sync_clock(self._want_ms)
        if self._source_is_ready():
            self._pending_load = False
            self._pending_play = False
            self._seek_to(self._want_ms, play=True)
            return
        self._pending_load = True
        norm = self._audio_path.replace("\\", "/")
        if self._current_source() != norm:
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(self._audio_path))

    def _scrub(self, ms):
        self._want_ms = int(ms)
        self.navigator.set_playhead(int(ms))
        self._sync_clock(int(ms))
        if self._source_is_ready():
            self.player.setPosition(int(ms))

    def _media_status(self, status):
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._update_art()
        if not self._pending_load:
            return
        if status not in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
            QMediaPlayer.MediaStatus.EndOfMedia,
        ):
            return
        self._pending_load = False
        play = self._pending_play
        self._pending_play = False
        if self._want_ms is not None:
            self._seek_to(self._want_ms, play=play)
        elif play:
            self.player.play()

    def _seek_to(self, ms, play=False):
        self._seek_token += 1
        token = self._seek_token
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.player.setPosition(int(ms))
        if play and not playing:
            self.player.play()
        QTimer.singleShot(80, lambda: self._fix_failed_seek(token, int(ms)))

    def _fix_failed_seek(self, token, ms):
        if token != self._seek_token:
            return
        if self.player.position() < 30 and ms > 80:
            self.player.setPosition(ms)
        if self._want_ms == ms:
            self._want_ms = None

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            return
        if not self._audio_path:
            return
        ms = self.overview.playhead_ms
        self.play_from(0 if ms is None else int(ms))

    def _sync_play_button(self, playing):
        self.play_button.setIcon(_transport_icon(playing, self.play_button.isEnabled()))
        self.play_button.setText("Pause" if playing else "Play")

    def _visible_audio_loaded(self):
        if not self._audio_path:
            return False
        return self._current_source() == self._audio_path.replace("\\", "/")

    def _row_can_snap(self, row):
        item = self.table.item(row, COL_CHECK)
        if item is None:
            return False
        return bool(self.reports[item.data(Qt.UserRole)].proposed)

    def _play_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._sync_play_button(playing)
        visible = self._visible_audio_loaded()
        self.overview.set_live(playing and visible)
        if playing:
            self.playhead_timer.start()
        else:
            self.playhead_timer.stop()
            if not visible:
                QTimer.singleShot(0, self._warm_visible)
                return
            pos = self.player.position() if self._want_ms is None else self._want_ms
            self.overview.set_playhead(pos)
            self.navigator.set_playhead(pos)
            self._sync_clock(pos)

    def _tick_playhead(self):
        if not self._visible_audio_loaded():
            return
        pos = self.player.position()
        self.overview.set_playhead(pos, follow=True)
        self.navigator.set_playhead(pos)
        self._sync_clock(pos)

    def _override(self, verdict):
        report = self._selected_report()
        if report is None:
            return
        self.overrides[report.track_id] = verdict
        row = self.table.currentRow()
        self._fill_table()
        if 0 <= row < self.table.rowCount():
            self.table.selectRow(row)

    def _ticked_reports(self):
        chosen = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.checkState() != Qt.Checked:
                continue
            report = self.reports[item.data(Qt.UserRole)]
            if report.proposed:
                chosen.append(report)
        return chosen

    def _update_snap_button(self, *_args):
        count = len(self._ticked_reports())
        self.snap_button.setText(f"Snap {count:,} track(s)" if count else "Snap selected")
        self.snap_button.setEnabled(count > 0 and not self.tasks.busy)

    def _confirm_rekordbox_closed(self):
        while is_rekordbox_running():
            answer = QMessageBox.warning(
                self,
                "Close Rekordbox",
                "Rekordbox is running. Close it completely, then click Retry.\n\n"
                "Changing the library while Rekordbox is open can lose your changes or damage the library.",
                QMessageBox.Retry | QMessageBox.Cancel,
            )
            if answer != QMessageBox.Retry:
                return False
        self._check_rekordbox()
        return True

    def snap_selected(self):
        reports = self._ticked_reports()
        if not reports:
            return
        unclear = sum(1 for r in reports if self._verdict(r) != Verdict.CUES_WRONG)
        text = f"Move cue points onto the beat grid for {len(reports):,} track(s)?"
        info = "A backup of the database is made first. Restore it from the main window if anything looks wrong."
        if unclear:
            info = f"{unclear:,} of them are not marked as 'cues off grid'.\n\n" + info
        if QMessageBox.question(self, "Snap cue points", f"{text}\n\n{info}") != QMessageBox.Yes:
            return
        if self._confirm_rekordbox_closed():
            self._release_player()
            self.tasks.run(apply_snaps, (self.db_path, reports), self._snap_done, "Snapping cues...")

    def _snap_done(self, result):
        self._release_player()
        lines = [
            f"Moved {result.moved_cues:,} cue(s) on {len(result.applied):,} track(s).",
            f"Backup: {result.backup.path}",
        ]
        if result.skipped:
            lines.append(f"Skipped {len(result.skipped):,}.")
        self.status_label.setText(lines[0])
        self.summary.setText(" ".join(lines))
        text = lines[0]
        info = "A backup was saved first. Use Restore a backup on the main window if anything looks wrong."
        if result.warnings:
            info += f"\n\n{len(result.warnings):,} warning(s). See the log for details."
        QTimer.singleShot(0, lambda: self._show_snap_message(text, info, bool(result.warnings or result.skipped)))

    def _show_snap_message(self, text, info, warning):
        QMessageBox.warning(self, "Done", f"{text}\n\n{info}") if warning else QMessageBox.information(
            self, "Done", f"{text}\n\n{info}"
        )
