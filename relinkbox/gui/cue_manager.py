import os

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from relinkbox.analysis import read_beat_grid, read_waveform
from relinkbox.cues import Verdict, apply_snaps, scan_cues
from relinkbox.gui.waveform import CueStrip, OverviewWaveform
from relinkbox.gui.workers import TaskRunner
from relinkbox.logs import log_dir
from relinkbox.rekordbox import is_rekordbox_running

COLUMNS = ("Track", "Type", "Cues", "Offset", "Cause", "Verdict")
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


class CueManagerWindow(QMainWindow):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.reports = []
        self.overrides = {}
        self.grid = None
        self.waveform = None
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
        header.setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self._show_selected)
        self.table.itemChanged.connect(self._update_snap_button)
        layout.addWidget(self.table, 2)

        self.detail_title = QLabel("Select a track to see its waveform and cues.")
        self.detail_title.setWordWrap(True)
        layout.addWidget(self.detail_title)
        self.detail_reason = QLabel()
        self.detail_reason.setWordWrap(True)
        layout.addWidget(self.detail_reason)

        overrides = QHBoxLayout()
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
        overrides.addStretch(1)
        layout.addLayout(overrides)

        self.overview = OverviewWaveform()
        self.overview.clicked.connect(self.seek)
        layout.addWidget(self.overview)

        self.strips_host = QWidget()
        self.strips_layout = QVBoxLayout(self.strips_host)
        self.strips_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.strips_host)
        scroll.setMinimumHeight(180)
        layout.addWidget(scroll, 1)

        player = QHBoxLayout()
        self.play_button = QPushButton("Play")
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(False)
        player.addWidget(self.play_button)
        self.cue_buttons = QWidget()
        self.cue_buttons_layout = QHBoxLayout(self.cue_buttons)
        self.cue_buttons_layout.setContentsMargins(0, 0, 0, 0)
        player.addWidget(self.cue_buttons)
        player.addStretch(1)
        layout.addLayout(player)

        self.status_label = QLabel()
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.playhead_timer = QTimer(self)
        self.playhead_timer.setInterval(33)
        self.playhead_timer.timeout.connect(self._tick_playhead)
        self.player.playbackStateChanged.connect(self._play_state_changed)

        self.busy_widgets = [self.scan_button, self.filter, self.snap_button]
        self.rekordbox_timer = QTimer(self)
        self.rekordbox_timer.timeout.connect(self._check_rekordbox)
        self.rekordbox_timer.start(4000)
        self._check_rekordbox()

    def closeEvent(self, event):
        if self.tasks.busy:
            QMessageBox.information(self, "Still working", "Please wait for the current task to finish.")
            event.ignore()
            return
        self.player.stop()
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
        self.player.stop()
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
        self.status_label.setText("Scan finished. Nothing has been changed yet.")

    def _visible_reports(self):
        wanted = FILTERS[self.filter.currentIndex()][1]
        return [(i, r) for i, r in enumerate(self.reports) if wanted is None or r.verdict == wanted]

    def _fill_table(self):
        rows = self._visible_reports()
        self.table.blockSignals(True)
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
        self.table.setColumnWidth(0, 320)
        self.table.setColumnWidth(1, 60)
        self.table.setColumnWidth(2, 50)
        self.table.setColumnWidth(3, 80)
        self.table.setColumnWidth(4, 160)
        self.table.blockSignals(False)
        self._update_snap_button()
        if rows:
            self.table.selectRow(0)
        else:
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
        self.player.stop()
        self.detail_title.setText(f"{report.label}  ({report.file_type or 'unknown'})")
        extra = " You marked the grid as right." if self.overrides.get(report.track_id) == Verdict.CUES_WRONG else ""
        extra = " You marked the cues as right." if self.overrides.get(report.track_id) == Verdict.GRID_WRONG else extra
        self.detail_reason.setText((report.reason or "Cues sit on the beat grid.") + extra)
        has_choice = bool(report.proposed)
        self.cues_right_button.setEnabled(has_choice)
        self.grid_right_button.setEnabled(has_choice)

        self.grid = None
        self.waveform = None
        if report.dat_path:
            try:
                self.grid = read_beat_grid(report.dat_path)
            except Exception:
                self.grid = None
        if report.ext_path:
            try:
                self.waveform = read_waveform(report.ext_path)
            except Exception:
                self.waveform = None
        duration = int(self.grid.times[-1]) if self.grid and self.grid.times else None
        self.overview.set_data(self.waveform, report.cues, duration)
        self.overview.set_playhead(None)
        self._rebuild_strips(report)
        self._rebuild_cue_buttons(report)
        self._load_audio(report.path)

    def _clear_detail(self):
        self.player.stop()
        self.detail_title.setText("Select a track to see its waveform and cues.")
        self.detail_reason.setText("")
        self.cues_right_button.setEnabled(False)
        self.grid_right_button.setEnabled(False)
        self.overview.set_data(None, [])
        self._rebuild_strips(None)
        self._rebuild_cue_buttons(None)
        self.play_button.setEnabled(False)

    def _rebuild_strips(self, report):
        while self.strips_layout.count():
            item = self.strips_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if report is None:
            return
        for cue in report.cues:
            strip = CueStrip()
            strip.set_data(
                self.waveform,
                self.grid,
                cue,
                report.proposed.get(cue.id, (None, None))[0],
                report.hits_offset,
            )
            strip.clicked.connect(self.seek)
            self.strips_layout.addWidget(strip)

    def _rebuild_cue_buttons(self, report):
        while self.cue_buttons_layout.count():
            item = self.cue_buttons_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if report is None:
            return
        for cue in report.cues:
            button = QPushButton(cue.label)
            button.clicked.connect(lambda _=False, t=cue.in_ms: self.play_from(t))
            self.cue_buttons_layout.addWidget(button)

    def _load_audio(self, path):
        if path and os.path.isfile(path):
            self.player.setSource(QUrl.fromLocalFile(path))
            self.play_button.setEnabled(True)
        else:
            self.player.setSource(QUrl())
            self.play_button.setEnabled(False)

    def seek(self, ms):
        self.player.setPosition(int(ms))
        self.overview.set_playhead(int(ms))

    def play_from(self, ms):
        self.seek(ms)
        self.player.play()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _play_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText("Pause" if playing else "Play")
        if playing:
            self.playhead_timer.start()
        else:
            self.playhead_timer.stop()
            self.overview.set_playhead(self.player.position())

    def _tick_playhead(self):
        self.overview.set_playhead(self.player.position())

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
            self.player.stop()
            self.tasks.run(apply_snaps, (self.db_path, reports), self._snap_done, "Snapping cues...")

    def _snap_done(self, result):
        lines = [
            f"Moved {result.moved_cues:,} cue(s) on {len(result.applied):,} track(s).",
            f"Backup: {result.backup.path}",
        ]
        if result.skipped:
            lines.append(f"Skipped {len(result.skipped):,}.")
        if result.warnings:
            lines += result.warnings[:20]
        self.status_label.setText(lines[0])
        self.summary.setText(" ".join(lines[:3]))
        box = QMessageBox(self)
        box.setWindowTitle("Done")
        box.setIcon(QMessageBox.Warning if result.warnings or result.skipped else QMessageBox.Information)
        box.setText(lines[0])
        box.setInformativeText("A backup was saved first. Use Restore a backup on the main window if anything looks wrong.")
        if result.warnings:
            box.setDetailedText("\n".join(result.warnings))
        box.exec()
        self.scan()
