import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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
