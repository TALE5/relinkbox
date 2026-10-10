import os
from collections import OrderedDict

from PySide6.QtCore import QEvent, QSettings, QSize, QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPalette, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from relinkbox.analysis import read_beat_grid, read_waveform
from relinkbox.cues import Verdict, apply_snaps, display_cues, scan_cues
from relinkbox.gui.waveform import CueOffsetRow, OverviewWaveform, TrackNavigator, bake_track, cue_color
from relinkbox.gui.workers import TaskRunner
from relinkbox.logs import log_dir
from relinkbox.rekordbox import is_rekordbox_running

COLUMNS = ("Track", "Type", "Cues", "Offset", "Cause", "Verdict")
COVER_SIZE = 62
_EMPTY_PAD = "QPushButton { border-radius: 0px; border: 1px solid palette(mid); }"
FILTERS = (
    ("All tracks", None),
    ("Cues off grid", Verdict.CUES_WRONG),
    ("Grid looks off", Verdict.GRID_WRONG),
    ("Check manually", Verdict.UNCLEAR),
    ("On grid", Verdict.ON_GRID),
)


def _item(text, tooltip=None):
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    item.setToolTip(tooltip or text)
    return item


def _track_meta(report):
    parts = []
    if report.file_type:
        parts.append(report.file_type.upper())
    if report.bit_rate:
        parts.append(f"{report.bit_rate:,} kbps")
    if report.sample_rate:
        khz = f"{report.sample_rate / 1000:.1f}".rstrip("0").rstrip(".")
        parts.append(f"{khz} kHz")
    return "  ·  ".join(parts)


class CueManagerWindow(QMainWindow):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
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
        self._sort_col = 0
        self._sort_desc = False
        self._wave_cache = OrderedDict()
        self.settings = QSettings("Relinkbox", "Relinkbox")
        self.tasks = TaskRunner(self, self._set_busy, self._on_progress, self._failed)

        self.setWindowTitle("Cue points")
        self.setMinimumSize(1100, 760)
        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        self.banner = QLabel(
            "Rekordbox is running. You can scan, but close Rekordbox before snapping any cues."
        )
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet("background: #fef3c7; color: #78350f; padding: 6px; border-radius: 4px;")
        self.banner.setVisible(False)
        layout.addWidget(self.banner)

        top = QHBoxLayout()
        self.scan_button = QPushButton("Scan library")
        self.scan_button.clicked.connect(self.scan)
        top.addWidget(self.scan_button)
        self.filter = QComboBox()
        for label, _value in FILTERS:
            self.filter.addItem(label)
        self.filter.currentIndexChanged.connect(self._fill_table)
        top.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tracks...")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(220)
        self.search.textChanged.connect(self._fill_table)
        top.addWidget(self.search)
        self.summary = QLabel("Scan the library to compare cue points with each track's beat grid.")
        self.summary.setWordWrap(True)
        top.addWidget(self.summary, 1)
        self.snap_button = QPushButton("Snap selected")
        self.snap_button.setEnabled(False)
        self.snap_button.clicked.connect(self.snap_selected)
        top.addWidget(self.snap_button)
        layout.addLayout(top)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setStretchLastSection(False)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(0, Qt.AscendingOrder)
        header.sectionClicked.connect(self._sort_by)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.itemChanged.connect(self._update_snap_button)
        self.table.setColumnWidth(1, 70)
        self.table.setColumnWidth(2, 55)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 130)
        layout.addWidget(self.table, 2)

        title_row = QHBoxLayout()
        self.art = QLabel()
        self.art.setFixedSize(COVER_SIZE, COVER_SIZE)
        self.art.setAlignment(Qt.AlignCenter)
        self.art.hide()
        title_row.addWidget(self.art, 0, Qt.AlignTop)
        title_text = QVBoxLayout()
        title_text.setSpacing(2)
        self.detail_title = QLabel("Select a track to see its waveform and cues.")
        self.detail_title.setWordWrap(True)
        title_font = QFont(self.detail_title.font())
        title_font.setPointSize(13)
        title_font.setBold(True)
        self.detail_title.setFont(title_font)
        self.detail_genre = QLabel()
        genre_font = QFont(self.detail_title.font())
        genre_font.setPointSize(9)
        genre_font.setBold(False)
        self.detail_genre.setFont(genre_font)
        self.detail_genre.setStyleSheet("color: #8a8a8a;")
        self.detail_genre.hide()
        self.detail_meta = QLabel()
        meta_font = QFont(self.detail_title.font())
        meta_font.setPointSize(10)
        meta_font.setBold(False)
        self.detail_meta.setFont(meta_font)
        self.detail_meta.hide()
        title_text.addWidget(self.detail_title)
        title_text.addWidget(self.detail_genre)
        title_text.addWidget(self.detail_meta)
        title_row.addLayout(title_text, 1)
        side = QVBoxLayout()
        side.setSpacing(4)
        overrides = QHBoxLayout()
        overrides.setSpacing(6)
        self.cues_right_button = QPushButton("The cues are right")
        self.cues_right_button.setToolTip("Keep the cues. The beat grid is probably wrong.")
        self.cues_right_button.clicked.connect(lambda: self._override(Verdict.GRID_WRONG))
        self.grid_right_button = QPushButton("The grid is right")
        self.grid_right_button.setToolTip("Snap the cues onto the beat grid.")
        self.grid_right_button.clicked.connect(lambda: self._override(Verdict.CUES_WRONG))
        self.cues_right_button.setEnabled(False)
        self.grid_right_button.setEnabled(False)
        overrides.addWidget(self.cues_right_button)
        overrides.addWidget(self.grid_right_button)
        side.addLayout(overrides)
        self.detail_reason = QLabel()
        self.detail_reason.setWordWrap(True)
        self.detail_reason.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.detail_reason.setMaximumWidth(360)
        side.addWidget(self.detail_reason, 0, Qt.AlignRight)
        title_row.addLayout(side)
        layout.addLayout(title_row)

        self.navigator = TrackNavigator()
        self.navigator.clicked.connect(lambda ms: self.jump_to(ms, center=True))
        self.navigator.scrubbed.connect(lambda ms: self.jump_to(ms, center=True))
        layout.addWidget(self.navigator)
        self.overview = OverviewWaveform()
        self.overview.clicked.connect(self.jump_to)
        self.overview.view_changed.connect(self.navigator.set_view)
        self.overview.scrubbed.connect(self._scrub)
        layout.addWidget(self.overview)
        self.offsets = CueOffsetRow()
        self.offsets.hide()
        layout.addWidget(self.offsets)

        player = QHBoxLayout()
        player.setAlignment(Qt.AlignTop)
        pads = QWidget()
        pad_grid = QGridLayout(pads)
        pad_grid.setContentsMargins(0, 0, 0, 0)
        pad_grid.setSpacing(4)
        self.pad_buttons = {}
        for row, col, kind, letter in (
            (0, 0, 1, "A"),
            (1, 0, 2, "B"),
            (2, 0, 3, "C"),
            (3, 0, 5, "D"),
            (0, 1, 6, "E"),
            (1, 1, 7, "F"),
            (2, 1, 8, "G"),
            (3, 1, 9, "H"),
        ):
            button = QPushButton(letter)
            button.setFixedSize(40, 26)
            button.setEnabled(False)
            button.setAutoRepeat(False)
            button.setStyleSheet(_EMPTY_PAD)
            button.pressed.connect(lambda k=kind: self._pad_pressed(k))
            button.released.connect(lambda k=kind: self._pad_released(k))
            pad_grid.addWidget(button, row, col)
            self.pad_buttons[kind] = button
        left = QHBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(pads, 0, Qt.AlignTop)
        left.addStretch(1)
        self.play_button = QPushButton("Play")
        self.play_button.setFixedHeight(48)
        self.play_button.setMinimumWidth(108)
        self.play_button.setIconSize(QSize(20, 20))
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(False)
        self._sync_play_button(False)
        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)
        right.addStretch(1)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setFixedWidth(120)
        self.volume.setValue(int(self.settings.value("cue_volume", 40)))
        self.volume.valueChanged.connect(self._set_volume)
        right.addWidget(QLabel("Vol"), 0, Qt.AlignVCenter)
        right.addWidget(self.volume, 0, Qt.AlignVCenter)
        player.addLayout(left, 1)
        player.addWidget(self.play_button, 0, Qt.AlignTop)
        player.addLayout(right, 1)
        layout.addLayout(player)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        layout.addSpacing(8)
        self.status_label = QLabel()
        self._style_status_bar()
        layout.addWidget(self.status_label)

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
        self._style_status_bar()
        super().showEvent(event)

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
            self._sort_desc = False
        self.table.horizontalHeader().setSortIndicator(
            column, Qt.DescendingOrder if self._sort_desc else Qt.AscendingOrder
        )
        if self.table.rowCount():
            self._reorder_table()
        else:
            self._fill_table()

    def _sort_key(self, report):
        if self._sort_col == 1:
            return report.file_type or ""
        if self._sort_col == 2:
            return len(report.cues)
        if self._sort_col == 3:
            return report.offset if report.offset is not None else float("inf")
        if self._sort_col == 4:
            return report.cause.lower()
        if self._sort_col == 5:
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
        selected = None
        current = self.table.selectedItems()
        if current:
            selected = self.table.item(current[0].row(), 0).data(Qt.UserRole)
        packed = []
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        for row in range(self.table.rowCount()):
            cells = [self.table.takeItem(row, col) for col in range(cols)]
            if cells[0] is None:
                continue
            index = cells[0].data(Qt.UserRole)
            packed.append((self._sort_key(self.reports[index]), cells))
        packed.sort(key=lambda item: item[0], reverse=self._sort_desc)
        for row, (_key, cells) in enumerate(packed):
            for col, cell in enumerate(cells):
                self.table.setItem(row, col, cell)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        if selected is not None:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).data(Qt.UserRole) == selected:
                    self.table.selectRow(row)
                    break
        self._update_snap_button()

    def _fill_table(self):
        rows = self._visible_reports()
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(rows))
        for row, (index, report) in enumerate(rows):
            track = _item(report.label, report.path)
            track.setData(Qt.UserRole, index)
            track.setFlags(track.flags() | Qt.ItemIsUserCheckable)
            track.setCheckState(Qt.Checked if self._should_tick(report) else Qt.Unchecked)
            self.table.setItem(row, 0, track)
            self.table.setItem(row, 1, _item(report.file_type or "?"))
            self.table.setItem(row, 2, _item(str(len(report.cues))))
            offset = f"{report.offset:+.0f} ms" if report.offset is not None else ""
            self.table.setItem(row, 3, _item(offset))
            self.table.setItem(row, 4, _item(report.cause))
            self.table.setItem(row, 5, _item(self._verdict(report), report.reason))
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
        items = self.table.selectedItems()
        if not items:
            return None
        index = self.table.item(items[0].row(), 0).data(Qt.UserRole)
        if index is None:
            return None
        return self.reports[index]

    def _show_selected(self):
        report = self._selected_report()
        if report is None:
            self._clear_detail()
            return
        self._release_player()
        self.detail_title.setText(report.label)
        self.detail_title.setStyleSheet("color: #FF910F;")
        genre = (report.genre or "").strip()
        self.detail_genre.setText(genre)
        self.detail_genre.setVisible(bool(genre))
        meta = _track_meta(report)
        self.detail_meta.setText(meta)
        self.detail_meta.setVisible(bool(meta))
        extra = " You marked the grid as right." if self.overrides.get(report.track_id) == Verdict.CUES_WRONG else ""
        extra = " You marked the cues as right." if self.overrides.get(report.track_id) == Verdict.GRID_WRONG else extra
        self.detail_reason.setText((report.reason or "Cues sit on the beat grid.") + extra)
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
        )
        self.navigator.set_data(visuals["overview"], visible, visuals["duration"])
        self.offsets.set_data(self.waveform, self.grid, visible)
        self.overview.set_playhead(None)
        self.navigator.set_playhead(None)
        self._rebuild_cue_buttons(visible)
        self._audio_path = report.path if report.path and os.path.isfile(report.path) else None
        self.play_button.setEnabled(bool(self._audio_path))
        self._preload_audio()

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
        self._release_player()
        self._audio_path = None
        self.detail_title.setText("Select a track to see its waveform and cues.")
        self.detail_title.setStyleSheet("")
        self.detail_genre.clear()
        self.detail_genre.hide()
        self.detail_meta.clear()
        self.detail_meta.hide()
        self.detail_reason.setText("")
        self.art.clear()
        self.art.hide()
        self.cues_right_button.setEnabled(False)
        self.grid_right_button.setEnabled(False)
        self.overview.set_data(None, [])
        self.navigator.set_data(None, [], 1)
        self.offsets.set_data(None, None, [])
        self._rebuild_cue_buttons(None)
        self.play_button.setEnabled(False)

    def _style_pad(self, button, cue):
        color = cue_color(cue)
        luma = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        fg = "#111" if luma > 150 else "#fff"
        button.setStyleSheet(
            "QPushButton {"
            f" background: {color.name()}; color: {fg}; font-weight: 700;"
            " border: none; border-radius: 0px;"
            " }"
        )

    def _rebuild_cue_buttons(self, cues):
        by_kind = {cue.kind: cue for cue in (cues or []) if cue.kind != 0}
        for kind, button in self.pad_buttons.items():
            cue = by_kind.get(kind)
            button.setEnabled(bool(cue))
            if cue:
                self._style_pad(button, cue)
                button.setProperty("cue_ms", cue.in_ms)
            else:
                button.setStyleSheet(_EMPTY_PAD)
                button.setProperty("cue_ms", None)

    def _pad_pressed(self, kind):
        ms = self.pad_buttons[kind].property("cue_ms")
        if ms is None:
            return
        ms = int(ms)
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

    def _update_art(self):
        meta = self.player.metaData()
        image = None
        for key in (QMediaMetaData.Key.CoverArtImage, QMediaMetaData.Key.ThumbnailImage):
            value = meta.value(key)
            if value is None:
                continue
            if hasattr(value, "isNull") and value.isNull():
                continue
            image = value
            break
        if image is None:
            self.art.clear()
            self.art.hide()
            return
        if isinstance(image, QPixmap):
            pix = image
        elif isinstance(image, QImage):
            pix = QPixmap.fromImage(image)
        else:
            self.art.clear()
            self.art.hide()
            return
        self.art.setPixmap(pix.scaled(COVER_SIZE, COVER_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))
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
        if self._source_is_ready():
            self.player.setPosition(ms)
            return
        if not self._audio_path:
            return
        self._pending_load = True
        self._pending_play = False
        if self._current_source() != self._audio_path.replace("\\", "/"):
            self.player.setSource(QUrl.fromLocalFile(self._audio_path))

    def play_from(self, ms):
        if not self._audio_path:
            return
        self._want_ms = int(ms)
        self._pending_play = True
        self.overview.set_playhead(self._want_ms, follow=True)
        self.navigator.set_playhead(self._want_ms)
        if self._source_is_ready():
            self._seek_to(self._want_ms, play=True)
            return
        self._pending_load = True
        if self._current_source() != self._audio_path.replace("\\", "/"):
            self.player.setSource(QUrl.fromLocalFile(self._audio_path))

    def _scrub(self, ms):
        self._want_ms = int(ms)
        self.navigator.set_playhead(int(ms))
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
        if self._want_ms is not None:
            self.play_from(self._want_ms)
            return
        if not self._audio_path:
            return
        if not self._source_is_ready():
            self._pending_load = True
            self._pending_play = True
            self.player.setSource(QUrl.fromLocalFile(self._audio_path))
            return
        self.player.play()

    def _sync_play_button(self, playing):
        icon = QStyle.StandardPixmap.SP_MediaPause if playing else QStyle.StandardPixmap.SP_MediaPlay
        self.play_button.setIcon(self.style().standardIcon(icon))
        self.play_button.setText("Pause" if playing else "Play")

    def _style_status_bar(self):
        bg = self.palette().color(QPalette.ColorRole.Window).darker(145)
        fg = QColor(self.palette().color(QPalette.ColorRole.WindowText))
        fg = fg.darker(165) if fg.lightness() > 140 else fg.lighter(150)
        self.status_label.setStyleSheet(
            f"QLabel {{ background-color: {bg.name()}; color: {fg.name()}; padding: 8px 12px; }}"
        )

    def _play_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self._sync_play_button(playing)
        self.overview.set_live(playing)
        if playing:
            self.playhead_timer.start()
        else:
            self.playhead_timer.stop()
            pos = self.player.position() if self._want_ms is None else self._want_ms
            self.overview.set_playhead(pos)
            self.navigator.set_playhead(pos)

    def _tick_playhead(self):
        pos = self.player.position()
        self.overview.set_playhead(pos, follow=True)
        self.navigator.set_playhead(pos)

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
