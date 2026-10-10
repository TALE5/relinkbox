from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from relinkbox.matching import Confidence
from relinkbox.relink import Change
from relinkbox.reports import write_missing_csv, write_plan_csv

COLUMNS = ("Track", "Path in Rekordbox", "New file", "How it was matched", "Confidence", "Notes")
CHOOSE_TEXT = "Choose a file..."


def _item(text, tooltip=None):
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
    item.setToolTip(tooltip or text)
    return item


class PreviewDialog(QDialog):
    """Shows every proposed change before anything is written. exec() then selected_changes()."""

    def __init__(self, plan, title="Review changes", parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle(title)
        self.resize(1100, 620)

        layout = QVBoxLayout(self)
        ambiguous = sum(1 for m in plan.matches if m.ambiguous)
        found = len(plan.matches) - ambiguous
        parts = []
        if found:
            parts.append(f"{found:,} have a likely match")
        if ambiguous:
            parts.append(f"{ambiguous:,} need you to pick the right file")
        if plan.missing:
            parts.append(f"{len(plan.missing):,} could not be found")
        summary = f"{plan.missing_total:,} of {plan.total_tracks:,} tracks point to files that don't exist"
        summary += ": " + ", ".join(parts) + "." if parts else "."
        summary_label = QLabel(summary)
        summary_label.setWordWrap(True)
        layout.addWidget(summary_label)

        hint = QLabel(
            "Nothing has been changed yet. Tick the tracks to relink. High and medium confidence "
            "matches are ticked for you; check the rest yourself. A backup is made before saving."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        if plan.offline_drives:
            warning = QLabel(
                f"Warning: drive {', '.join(plan.offline_drives)} is not connected. If you only "
                "unplugged it, don't relink those tracks; plug the drive back in instead."
            )
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #b45309; font-weight: 500;")
            layout.addWidget(warning)

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        matches_page = QWidget()
        matches_layout = QVBoxLayout(matches_page)
        selection_row = QHBoxLayout()
        for text, handler in (
            ("Select recommended", self.select_recommended),
            ("Select all", lambda: self._set_all(True)),
            ("Select none", lambda: self._set_all(False)),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            selection_row.addWidget(button)
        selection_row.addStretch(1)
        matches_layout.addLayout(selection_row)

        self.table = QTableWidget(len(plan.matches), len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        matches_layout.addWidget(self.table)
        tabs.addTab(matches_page, f"Proposed matches ({len(plan.matches):,})")

        self._fill_matches()
        self.table.itemChanged.connect(self._update_apply_button)

        missing_page = QWidget()
        missing_layout = QVBoxLayout(missing_page)
        missing_table = QTableWidget(len(plan.missing), 2)
        missing_table.setHorizontalHeaderLabels(("Track", "Path in Rekordbox"))
        missing_table.setWordWrap(False)
        missing_table.verticalHeader().setVisible(False)
        missing_table.horizontalHeader().setStretchLastSection(True)
        for row, track in enumerate(plan.missing):
            missing_table.setItem(row, 0, _item(track.label))
            missing_table.setItem(row, 1, _item(track.path))
        missing_table.resizeColumnToContents(0)
        missing_layout.addWidget(missing_table)
        export_missing = QPushButton("Export missing tracks (CSV)...")
        export_missing.clicked.connect(self.export_missing)
        export_missing.setEnabled(bool(plan.missing))
        missing_layout.addWidget(export_missing, 0, Qt.AlignLeft)
        tabs.addTab(missing_page, f"Still missing ({len(plan.missing):,})")
        if not plan.matches:
            tabs.setCurrentIndex(1)

        buttons = QHBoxLayout()
        export_button = QPushButton("Export full report (CSV)...")
        export_button.clicked.connect(self.export_report)
        buttons.addWidget(export_button)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.apply_button = QPushButton()
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self._confirm)
        buttons.addWidget(self.apply_button)
        layout.addLayout(buttons)
        self._update_apply_button()

    def _fill_matches(self):
        self.table.blockSignals(True)
        for row, match in enumerate(self.plan.matches):
            track_item = _item(match.track.label)
            track_item.setFlags(track_item.flags() | Qt.ItemIsUserCheckable)
            track_item.setCheckState(Qt.Checked if match.selected_by_default else Qt.Unchecked)
            self.table.setItem(row, 0, track_item)
            self.table.setItem(row, 1, _item(match.track.path))
            if match.ambiguous:
                combo = QComboBox()
                combo.addItem(CHOOSE_TEXT, None)
                for candidate in match.candidates:
                    combo.addItem(candidate.path, candidate.path)
                combo.setToolTip("Several files could be this track. Pick the right one.")
                combo.currentIndexChanged.connect(lambda _i, r=row, c=combo: self._choose(r, c))
                self.table.setCellWidget(row, 2, combo)
            else:
                self.table.setItem(row, 2, _item(match.new_path))
            self.table.setItem(row, 3, _item(match.method.value))
            confidence = match.confidence.value + (" (pick a file)" if match.ambiguous else "")
            self.table.setItem(row, 4, _item(confidence))
            notes = " ".join(match.notes)
            self.table.setItem(row, 5, _item(notes, "\n".join(match.notes) or None))
        for column, width in enumerate((240, 300, 300, 190, 110)):
            self.table.setColumnWidth(column, width)
        self.table.blockSignals(False)

    def _choose(self, row, combo):
        match = self.plan.matches[row]
        match.chosen = combo.currentData()
        self.table.item(row, 0).setCheckState(Qt.Checked if match.chosen else Qt.Unchecked)

    def _rows(self):
        for row, match in enumerate(self.plan.matches):
            yield row, match, self.table.item(row, 0)

    def _set_all(self, checked):
        self.table.blockSignals(True)
        for _row, match, item in self._rows():
            item.setCheckState(Qt.Checked if checked and match.new_path else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_apply_button()

    def select_recommended(self):
        self.table.blockSignals(True)
        for _row, match, item in self._rows():
            item.setCheckState(Qt.Checked if match.selected_by_default else Qt.Unchecked)
        self.table.blockSignals(False)
        self._update_apply_button()

    def selected_changes(self):
        changes = []
        for _row, match, item in self._rows():
            if item.checkState() == Qt.Checked and match.new_path:
                changes.append(Change(track=match.track, new_path=match.new_path, method=match.method.value))
        return changes

    def _update_apply_button(self, *_args):
        self.table.blockSignals(True)
        for _row, match, item in self._rows():
            if item.checkState() == Qt.Checked and not match.new_path:
                item.setCheckState(Qt.Unchecked)
        self.table.blockSignals(False)
        count = len(self.selected_changes())
        self.apply_button.setText(f"Relink {count:,} track(s)")
        self.apply_button.setEnabled(count > 0)

    def _confirm(self):
        changes = self.selected_changes()
        low = sum(
            1
            for _row, match, item in self._rows()
            if item.checkState() == Qt.Checked and match.confidence == Confidence.LOW
        )
        text = f"Relink {len(changes):,} track(s) in your Rekordbox library?"
        info = "A backup of the database is made first, and you can restore it from the main window."
        if low:
            info = f"{low:,} of them are low-confidence matches.\n\n" + info
        answer = QMessageBox.question(self, "Relink tracks", f"{text}\n\n{info}")
        if answer == QMessageBox.Yes:
            self.accept()

    def export_report(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export report", "relinkbox-report.csv", "CSV files (*.csv)")
        if path:
            write_plan_csv(path, self.plan)

    def export_missing(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export missing tracks", "missing-tracks.csv", "CSV files (*.csv)"
        )
        if path:
            write_missing_csv(path, self.plan.missing)
