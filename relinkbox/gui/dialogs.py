import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from relinkbox.backup import backup_from_file


class FolderMovedDialog(QDialog):
    """Ask for the old folder (as stored in Rekordbox) and where it lives now."""

    def __init__(self, suggestion=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Folder or drive moved")
        self.setMinimumWidth(620)
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Use this when a whole folder moved or a drive letter changed, for example "
            "E:\\Music became F:\\Music. Tracks keep their subfolders and names, so the "
            "result is exact. You'll see every change before anything is saved."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self.old_edit = QLineEdit()
        self.old_edit.setPlaceholderText("E:/Music")
        if suggestion:
            folder, count = suggestion
            self.old_edit.setText(folder)
            self.old_edit.setToolTip(f"{count:,} missing track(s) were in this folder.")
        form.addRow("Old folder (as Rekordbox knows it):", self.old_edit)

        new_row = QHBoxLayout()
        self.new_edit = QLineEdit()
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        new_row.addWidget(self.new_edit, 1)
        new_row.addWidget(browse)
        form.addRow("Where that folder is now:", new_row)
        layout.addLayout(form)

        if suggestion:
            hint = QLabel(f"Suggested from your missing tracks: {suggestion[1]:,} were in {suggestion[0]}.")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Preview changes")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.error = QLabel()
        self.error.setStyleSheet("color: #b91c1c;")
        layout.addWidget(self.error)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Where is that folder now?")
        if folder:
            self.new_edit.setText(folder)

    def _accept(self):
        if not self.old_prefix:
            self.error.setText("Enter the old folder.")
        elif not os.path.isdir(self.new_prefix):
            self.error.setText("Choose the folder where the music is now.")
        else:
            self.accept()

    @property
    def old_prefix(self):
        return self.old_edit.text().strip()

    @property
    def new_prefix(self):
        return self.new_edit.text().strip()


class RestoreDialog(QDialog):
    def __init__(self, backups, start_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Restore a backup")
        self.setMinimumSize(560, 360)
        self.start_dir = start_dir
        self.selected = None
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Pick the backup to restore. Your current library is backed up first, "
            "so you can undo the restore too."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.list = QListWidget()
        for backup in backups:
            item = QListWidgetItem(backup.title)
            item.setToolTip(str(backup.db_file))
            item.setData(Qt.UserRole, backup)
            self.list.addItem(item)
        if backups:
            self.list.setCurrentRow(0)
        else:
            self.list.addItem("No backups found next to this database.")
            self.list.setEnabled(False)
        self.list.itemDoubleClicked.connect(lambda _item: self._accept())
        layout.addWidget(self.list, 1)

        buttons = QHBoxLayout()
        browse = QPushButton("Browse for a backup file...")
        browse.clicked.connect(self._browse)
        buttons.addWidget(browse)
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        restore = QPushButton("Restore")
        restore.setDefault(True)
        restore.setEnabled(bool(backups))
        restore.clicked.connect(self._accept)
        buttons.addWidget(restore)
        layout.addLayout(buttons)

    def _accept(self):
        item = self.list.currentItem()
        if item and item.data(Qt.UserRole):
            self.selected = item.data(Qt.UserRole)
            self.accept()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select backup file", self.start_dir, "Database files (*.db)"
        )
        if path:
            self.selected = backup_from_file(path)
            self.accept()


class DisplayNameDialog(QDialog):
    """Before/after view of the file name Rekordbox shows versus the file on disk."""

    def __init__(self, changes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("File names in Rekordbox")
        self.resize(920, 520)
        self.setStyleSheet(
            "QDialog { background: #121214; color: #c4c4ca; }"
            "QLabel { color: #c4c4ca; }"
            "QTableWidget {"
            " background: #1c1c20; color: #c4c4ca; border: 1px solid #34343a;"
            " gridline-color: #2a2a2e; selection-background-color: #3a332c;"
            " selection-color: #c4c4ca;"
            "}"
            "QHeaderView::section {"
            " background: #2c2c34; color: #c4c4ca; border: none;"
            " border-bottom: 1px solid #3a3a42; padding: 6px 8px; font-weight: 700;"
            "}"
            "QPushButton {"
            " background: #2a2a2e; color: #c4c4ca; border: 1px solid #3c3c42;"
            " border-radius: 6px; padding: 6px 14px;"
            "}"
            "QPushButton:hover { background: #34343a; }"
            "QPushButton#updateNames {"
            " background: #FF910F; color: #ffffff; font-weight: 700; border: none;"
            "}"
            "QPushButton#updateNames:hover { background: #ff9d33; }"
        )

        layout = QVBoxLayout(self)
        count = len(changes)
        summary = QLabel(
            f"{count:,} track(s) where the name Rekordbox shows does not match the file on disk."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        hint = QLabel(
            "The file stays where it is. Only the name shown in Rekordbox changes. "
            "A backup is made before anything is saved."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        table = QTableWidget(count, 3)
        table.setHorizontalHeaderLabels(("Track", "Shown in Rekordbox", "File on disk"))
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setShowGrid(False)
        table.setAlternatingRowColors(True)
        table.verticalHeader().setDefaultSectionSize(32)
        for row, change in enumerate(changes):
            track = change.track
            shown = track.display_name or "(empty)"
            actual = change.new_path or "(empty)"
            location = track.path or ""
            cells = (
                (track.label, location),
                (shown, shown),
                (actual, actual),
            )
            for column, (text, tip) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(tip or text)
                table.setItem(row, column, item)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        update = QPushButton("Update these names")
        update.setObjectName("updateNames")
        update.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(update)
        layout.addLayout(buttons)
