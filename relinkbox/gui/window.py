import os
import shutil

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from relinkbox import __version__
from relinkbox.brand import apply_window_icon, assets_dir, trimmed_pixmap
from relinkbox.gui.fonts import ui_font
from relinkbox.backup import backups_root, list_backups, restore_backup
from relinkbox.gui.dialogs import DisplayNameDialog, FolderMovedDialog, RestoreDialog
from relinkbox.gui.preview import PreviewDialog
from relinkbox.gui.workers import TaskRunner
from relinkbox.logs import log_dir
from relinkbox.matching import suggest_moved_prefix
from relinkbox.rekordbox import find_default_database, is_rekordbox_running
from relinkbox.relink import (
    apply_display_names,
    apply_relinks,
    find_untracked_files,
    missing_tracks,
    plan_display_names,
    scan_folder_move,
    scan_library,
)
from relinkbox.reports import write_m3u8, write_text_list

ROLE_DIR = Qt.UserRole


def _open_folder(path):
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


class _ActionButton(QPushButton):
    """QPushButton's own size ignores a child layout, which clips the two lines."""

    def sizeHint(self):
        layout = self.layout()
        if layout is None:
            return super().sizeHint()
        return layout.sizeHint()

    def minimumSizeHint(self):
        return self.sizeHint()


def _action_button(title, detail, tip):
    """Two-line action: the title is bold, the parenthetical line is not."""
    button = _ActionButton()
    button.setObjectName("actionButton")
    button.setToolTip(tip)
    button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    text = QVBoxLayout(button)
    text.setContentsMargins(12, 8, 12, 8)
    text.setSpacing(1)
    title_label = QLabel(title)
    title_label.setFont(ui_font(10, bold=True))
    title_label.setAlignment(Qt.AlignCenter)
    detail_label = QLabel(detail)
    detail_label.setFont(ui_font(10))
    detail_label.setAlignment(Qt.AlignCenter)
    detail_label.setWordWrap(True)
    for label in (title_label, detail_label):
        label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        label.setMinimumHeight(QFontMetrics(label.font()).lineSpacing() + 2)
        text.addWidget(label)
    return button


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setFont(ui_font(10))
        self.setStyleSheet("QMainWindow { background: #121214; }")
        apply_window_icon(self)
        self.setWindowTitle(f"Relinkbox {__version__}")
        self.setMinimumSize(820, 760)
        self.settings = QSettings("Relinkbox", "Relinkbox")

        self.db_path = None
        self.last_backup = None
        self.cue_window = None
        self.tasks = TaskRunner(self, self._set_busy, self._on_progress, self._failed)

        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.setCentralWidget(root)
        header = self._brand_header()
        if header is not None:
            outer.addWidget(header)
        body = QWidget()
        body.setObjectName("mainBody")
        body.setFont(ui_font(10))
        body.setAttribute(Qt.WA_StyledBackground, True)
        # Page, fields, and text use the same colors as Cue Manager.
        body.setStyleSheet(
            "QWidget#mainBody { background: #121214; }"
            "QGroupBox {"
            " background: #121214; color: #c4c4ca;"
            " border: 1px solid #2a2a2e; border-radius: 6px;"
            " margin-top: 10px; padding: 12px 8px 8px 8px;"
            "}"
            "QGroupBox::title {"
            " subcontrol-origin: margin; subcontrol-position: top left;"
            " left: 12px; padding: 0 4px; color: #c4c4ca; background: #121214;"
            "}"
            "QLabel { color: #c4c4ca; background: transparent; }"
            "QLabel#statusLabel { color: #9a9aa2; }"
            "QLabel#rekordboxBanner {"
            " background: #fef3c7; color: #78350f; padding: 6px; border-radius: 4px;"
            "}"
            "QListWidget, QTextEdit {"
            " color: #c4c4ca; background: #1c1c20; border: 1px solid #34343a;"
            " border-radius: 6px; selection-background-color: #3a332c; selection-color: #c4c4ca;"
            "}"
            "QListWidget::item { color: #c4c4ca; padding: 2px 4px; }"
            "QListWidget::item:selected { background: #3a332c; color: #c4c4ca; }"
            "QPushButton, QToolButton {"
            " background: #2a2a2e; color: #c4c4ca; border: 1px solid #3c3c42;"
            " border-radius: 6px; padding: 4px 12px;"
            "}"
            "QPushButton#actionButton { padding: 0; }"
            "QPushButton:hover, QToolButton:hover { background: #34343a; }"
            "QPushButton:disabled, QToolButton:disabled {"
            " background: #1c1c20; color: #8e8e96; border-color: #333338;"
            "}"
            "QPushButton#logButton { color: #c4c4ca; background: transparent; border: none; }"
            "QPushButton#cuesButton QLabel { color: #ffffff; background: transparent; font-weight: 700; }"
        )
        layout = QVBoxLayout(body)
        layout.setContentsMargins(11, 12, 11, 11)
        outer.addWidget(body, 1)

        self.rekordbox_banner = QLabel(
            "Rekordbox is running. You can scan, but close Rekordbox before saving any changes."
        )
        self.rekordbox_banner.setObjectName("rekordboxBanner")
        self.rekordbox_banner.setWordWrap(True)
        self.rekordbox_banner.setVisible(False)
        layout.addWidget(self.rekordbox_banner)

        db_box = QGroupBox("Rekordbox library")
        db_layout = QVBoxLayout(db_box)
        self.db_label = QLabel()
        self.db_label.setWordWrap(True)
        self.db_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        db_layout.addWidget(self.db_label)
        db_buttons = QHBoxLayout()
        self.db_button = QPushButton("Choose database...")
        self.db_button.clicked.connect(self.select_database)
        self.restore_button = QPushButton("Restore a backup...")
        self.restore_button.clicked.connect(self.restore_backup)
        self.folders_button = QToolButton()
        self.folders_button.setText("Open folder")
        self.folders_button.setPopupMode(QToolButton.InstantPopup)
        folders_menu = QMenu(self.folders_button)
        folders_menu.addAction("Rekordbox folder", self.open_rekordbox_folder)
        folders_menu.addAction("Backups folder", self.open_backups_folder)
        self.folders_button.setMenu(folders_menu)
        for button in (self.db_button, self.restore_button, self.folders_button):
            db_buttons.addWidget(button)
        db_buttons.addStretch(1)
        db_layout.addLayout(db_buttons)
        layout.addWidget(db_box)

        music_box = QGroupBox("Music folders to search")
        music_layout = QVBoxLayout(music_box)
        self.folder_list = QListWidget()
        self.folder_list.setMaximumHeight(110)
        music_layout.addWidget(self.folder_list)
        folder_buttons = QHBoxLayout()
        self.add_folder_button = QPushButton("Add folder...")
        self.add_folder_button.clicked.connect(self.add_folder)
        self.remove_folder_button = QPushButton("Remove selected")
        self.remove_folder_button.clicked.connect(self.remove_folder)
        folder_buttons.addWidget(self.add_folder_button)
        folder_buttons.addWidget(self.remove_folder_button)
        folder_buttons.addStretch(1)
        music_layout.addLayout(folder_buttons)

        cue_box = QGroupBox("Cue Manager")
        cue_box.setObjectName("cueBox")
        cue_box.setFont(ui_font(14))
        cue_layout = QVBoxLayout(cue_box)
        self.cues_button = QPushButton()
        self.cues_button.setObjectName("cuesButton")
        self.cues_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cue_text = QVBoxLayout(self.cues_button)
        cue_text.setContentsMargins(8, 8, 8, 8)
        cue_text.setSpacing(2)
        cue_title = QLabel("Cue Manager")
        cue_title.setFont(ui_font(14, bold=True))
        cue_title.setAlignment(Qt.AlignCenter)
        cue_sub = QLabel("(Opens in new window)")
        cue_sub.setFont(ui_font(10, bold=True))
        cue_sub.setAlignment(Qt.AlignCenter)
        for cue_label in (cue_title, cue_sub):
            cue_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            cue_text.addWidget(cue_label)
        self.cues_button.setToolTip(
            "Opens a separate window to find cue points that sit off the beat grid and snap them back."
        )
        self.cues_button.setStyleSheet(
            "QPushButton {"
            " background: #FF910F; color: #ffffff; font-weight: 700;"
            " border: 1px solid #e07f00; border-radius: 4px; padding: 8px;"
            "}"
            "QPushButton:hover { background: #ff9d33; }"
            "QPushButton:pressed { background: #e07f00; }"
            "QPushButton:disabled { background: #e8c9a0; color: #ffffff; border-color: #d7b48a; }"
        )
        self.cues_button.clicked.connect(self.open_cue_manager)
        cue_layout.addWidget(self.cues_button)
        cue_box.setFixedWidth(210)

        folders_row = QHBoxLayout()
        folders_row.setSpacing(12)
        folders_row.addWidget(music_box, 1)
        folders_row.addWidget(cue_box)
        layout.addLayout(folders_row)

        actions_box = QGroupBox("What do you want to do?")
        actions = QVBoxLayout(actions_box)
        self.relink_button = _action_button(
            "Scan for missing tracks",
            "(Review window. Nothing is saved until you confirm.)",
            "Looks for tracks whose file is missing and finds them in your music folders. "
            "Clicking only scans. A separate window opens so you can review matches. "
            "Nothing is written unless you confirm there.",
        )
        self.relink_button.clicked.connect(self.run_relinker)
        self.moved_button = _action_button(
            "A whole folder or drive letter changed",
            "(You enter the old and new location. Preview before anything is saved.)",
            "Use this when you already know the folder moved, for example E:\\Music is now F:\\Music. "
            "Every track that lived there is pointed at the new place. "
            "This is not a search for individual missing files. Nothing is saved until you confirm.",
        )
        self.moved_button.clicked.connect(self.folder_moved)
        self.untracked_button = _action_button(
            "Find music files Rekordbox doesn't have",
            "(Files in your folders with no library entry. A list only. They are not added.)",
            "Looks through your music folders for audio files that are not in the Rekordbox library. "
            "You can save the list or copy the files. Nothing is added to Rekordbox.",
        )
        self.untracked_button.clicked.connect(self.find_untracked)
        self.display_button = _action_button(
            "Rekordbox is showing the wrong file name",
            "(The name in the library doesn't match the file. The file stays put. You confirm first.)",
            "Rekordbox has its own file-name field, separate from the file on disk. "
            "When you rename a file, that field can keep the old name. "
            "This updates the name Rekordbox shows. The file's location is not changed, "
            "and nothing is saved until you confirm.",
        )
        self.display_button.clicked.connect(self.update_display_names)
        for button in (
            self.relink_button,
            self.moved_button,
            self.untracked_button,
            self.display_button,
        ):
            actions.addWidget(button)
        layout.addWidget(actions_box)

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.results_area = QTextEdit()
        self.results_area.setReadOnly(True)
        self.results_area.setPlaceholderText("Results appear here.")
        layout.addWidget(self.results_area, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        log_button = QPushButton("Open log folder")
        log_button.setObjectName("logButton")
        log_button.setFlat(True)
        log_button.clicked.connect(lambda: _open_folder(log_dir()))
        footer.addWidget(log_button)
        layout.addLayout(footer)

        self.busy_widgets = [
            self.db_button,
            self.restore_button,
            self.add_folder_button,
            self.remove_folder_button,
            self.relink_button,
            self.moved_button,
            self.untracked_button,
            self.display_button,
            self.cues_button,
        ]

        self._load_settings()
        self.rekordbox_timer = QTimer(self)
        self.rekordbox_timer.timeout.connect(self._check_rekordbox)
        self.rekordbox_timer.start(4000)
        self._check_rekordbox()

    # ----- settings and state -----

    def _brand_header(self):
        folder = assets_dir()
        if folder is None:
            return None
        word = trimmed_pixmap(folder / "png" / "relinkbox-wordmark-transparent.png", 30)
        if word.isNull():
            return None
        header = QWidget()
        header.setObjectName("brandHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setStyleSheet("QWidget#brandHeader { background: #202020; }")
        row = QHBoxLayout(header)
        row.setContentsMargins(16, 12, 16, 12)
        word_label = QLabel()
        word_label.setPixmap(word)
        word_label.setStyleSheet("background: transparent;")
        row.addWidget(word_label)
        row.addStretch(1)
        return header

    def _load_settings(self):
        saved_db = self.settings.value("db_path", "")
        if saved_db and os.path.exists(saved_db):
            self.db_path = saved_db
        else:
            self.db_path = find_default_database()
        folders = self.settings.value("music_folders", []) or []
        if isinstance(folders, str):
            folders = [folders]
        for folder in folders:
            if folder:
                self.folder_list.addItem(folder)
        self._update_db_label()

    def _save_settings(self):
        self.settings.setValue("db_path", self.db_path or "")
        self.settings.setValue("music_folders", self.music_folders())

    def music_folders(self):
        return [self.folder_list.item(i).text() for i in range(self.folder_list.count())]

    def _update_db_label(self):
        if self.db_path:
            self.db_label.setText(f"Database: {self.db_path}")
        else:
            self.db_label.setText("No Rekordbox database found. Choose your master.db.")
        self.folders_button.setEnabled(bool(self.db_path))

    def _check_rekordbox(self):
        self.rekordbox_banner.setVisible(is_rekordbox_running())

    def closeEvent(self, event):
        if self.tasks.busy:
            QMessageBox.information(self, "Still working", "Please wait for the current task to finish.")
            event.ignore()
            return
        self._save_settings()
        event.accept()

    # ----- background work -----

    def _set_busy(self, busy, text=""):
        for widget in self.busy_widgets:
            widget.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        self.progress_bar.setValue(0)
        self.status_label.setText(text)

    def _run(self, fn, args, on_done, busy_text):
        if self.cue_window is not None:
            self.cue_window._release_player()
        self.tasks.run(fn, args, on_done, busy_text)

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

    def open_cue_manager(self):
        if not self._require(folders=False):
            return
        from relinkbox.gui.cue_manager import CueManagerWindow

        if self.cue_window is None:
            self.cue_window = CueManagerWindow(self.db_path, self)
        self.cue_window.db_path = self.db_path
        self.cue_window.show()
        self.cue_window.raise_()
        self.cue_window.activateWindow()

    def _require(self, folders=True):
        if not self.db_path:
            QMessageBox.warning(self, "No database", "Choose your Rekordbox database (master.db) first.")
            return False
        if folders and not self.music_folders():
            QMessageBox.warning(self, "No music folder", "Add at least one music folder to search.")
            return False
        return True

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

    # ----- database and folders -----

    def select_database(self):
        start_dir = os.path.dirname(self.db_path) if self.db_path else ""
        file, _ = QFileDialog.getOpenFileName(
            self, "Open Rekordbox database", start_dir, "Rekordbox database (master.db);;Database files (*.db)"
        )
        if file:
            self.db_path = file
            self._update_db_label()
            self._save_settings()

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Add music folder")
        if not folder:
            return
        folder = os.path.normpath(folder)
        if folder not in self.music_folders():
            self.folder_list.addItem(folder)
            self._save_settings()

    def remove_folder(self):
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))
        self._save_settings()

    def open_backups_folder(self):
        if self.db_path:
            _open_folder(backups_root(self.db_path))

    def open_rekordbox_folder(self):
        if self.db_path:
            _open_folder(os.path.dirname(self.db_path))

    # ----- relink -----

    def run_relinker(self):
        if self._require():
            self._run(scan_library, (self.db_path, self.music_folders()), self._review_plan, "Scanning...")

    def folder_moved(self):
        if self._require(folders=False):
            self._run(missing_tracks, (self.db_path,), self._ask_folder_move, "Reading the library...")

    def _ask_folder_move(self, missing):
        if not missing:
            self._report_nothing_missing()
            return
        dialog = FolderMovedDialog(suggest_moved_prefix(missing), self)
        if dialog.exec():
            self._run(
                scan_folder_move,
                (self.db_path, dialog.old_prefix, dialog.new_prefix),
                self._review_plan,
                "Checking files...",
            )

    def _report_nothing_missing(self):
        self.status_label.setText("Nothing to relink.")
        QMessageBox.information(self, "Nothing to relink", "Every track points to a file that exists.")

    def _review_plan(self, plan):
        self.status_label.setText("")
        if plan.missing_total == 0:
            if plan.total_tracks and plan.ok_tracks == plan.total_tracks - plan.non_file_tracks:
                self._report_nothing_missing()
            else:
                QMessageBox.information(self, "No matches", "No missing tracks were found in that folder.")
            return
        lines = [
            f"Tracks in library: {plan.total_tracks:,}",
            f"Missing files: {plan.missing_total:,}",
            f"Proposed matches: {len(plan.matches):,}",
            f"Still missing: {len(plan.missing):,}",
        ]
        if plan.scan_errors:
            lines.append(f"Folders or files that could not be read: {len(plan.scan_errors):,} (see the log)")
        self.results_area.setPlainText("\n".join(lines))

        dialog = PreviewDialog(plan, parent=self)
        if not dialog.exec():
            self.status_label.setText("Cancelled. Nothing was changed.")
            return
        changes = dialog.selected_changes()
        if changes and self._confirm_rekordbox_closed():
            self._run(apply_relinks, (self.db_path, changes), self._relink_done, "Relinking...")

    def _relink_done(self, result):
        self._show_apply_result(result, "Relinked", "track(s)")

    def _show_apply_result(self, result, verb, noun):
        self.last_backup = result.backup
        self._update_db_label()
        lines = [f"{verb} {len(result.applied):,} {noun}.", f"Backup: {result.backup.path}", ""]
        if result.skipped:
            lines.append(f"Skipped {len(result.skipped):,}:")
            lines += [f"  {track.label}: {reason}" for track, reason in result.skipped]
            lines.append("")
        if result.warnings:
            lines.append(f"Warnings ({len(result.warnings):,}):")
            lines += [f"  {w}" for w in result.warnings]
            lines.append("")
        lines += [f"{c.old_path}  ->  {c.new_path}" for c in result.applied]
        self.results_area.setPlainText("\n".join(lines))
        self.status_label.setText(f"{verb} {len(result.applied):,} {noun}.")

        box = QMessageBox(self)
        box.setWindowTitle("Done")
        box.setIcon(QMessageBox.Warning if result.warnings or result.skipped else QMessageBox.Information)
        box.setText(f"{verb} {len(result.applied):,} {noun}.")
        info = "A backup was saved first. Use Restore a backup if anything looks wrong."
        if result.skipped or result.warnings:
            info = (
                f"{len(result.skipped):,} skipped, {len(result.warnings):,} warning(s). "
                "See the results list for details.\n\n" + info
            )
        box.setInformativeText(info)
        open_button = box.addButton("Open backup folder", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() == open_button:
            _open_folder(result.backup.path)

    # ----- display names -----

    def update_display_names(self):
        if self._require(folders=False):
            self._run(plan_display_names, (self.db_path,), self._review_display_names, "Checking display names...")

    def _review_display_names(self, changes):
        if not changes:
            self.status_label.setText("All display names already match their files.")
            QMessageBox.information(self, "Nothing to fix", "All display names already match their files.")
            return
        dialog = DisplayNameDialog(changes, self)
        if dialog.exec() and self._confirm_rekordbox_closed():
            self._run(apply_display_names, (self.db_path, changes), self._display_done, "Updating display names...")

    def _display_done(self, result):
        self._show_apply_result(result, "Updated", "display name(s)")

    # ----- untracked files -----

    def find_untracked(self):
        if self._require():
            self._run(
                find_untracked_files,
                (self.db_path, self.music_folders()),
                self._show_untracked,
                "Looking for files not in Rekordbox...",
            )

    def _show_untracked(self, files):
        if not files:
            self.results_area.setPlainText("Every music file in these folders is already in Rekordbox.")
            self.status_label.setText("No untracked files.")
            QMessageBox.information(self, "Nothing found", "Every music file in these folders is already in Rekordbox.")
            return
        self.status_label.setText(f"Found {len(files):,} file(s) not in Rekordbox.")
        self.results_area.setPlainText(f"{len(files):,} file(s) not in Rekordbox:\n\n" + "\n".join(files))

        box = QMessageBox(self)
        box.setWindowTitle("Files not in Rekordbox")
        box.setText(f"Found {len(files):,} music file(s) that are not in your Rekordbox library.")
        box.setInformativeText(
            "Save them as a playlist to import into Rekordbox (File > Import > Import Playlist), "
            "save a plain list, or copy the files somewhere."
        )
        playlist_button = box.addButton("Save as playlist (.m3u8)", QMessageBox.ActionRole)
        list_button = box.addButton("Save list (.txt)", QMessageBox.ActionRole)
        copy_button = box.addButton("Copy files...", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()

        clicked = box.clickedButton()
        if clicked == playlist_button:
            path, _ = QFileDialog.getSaveFileName(self, "Save playlist", "not-in-rekordbox.m3u8", "Playlist (*.m3u8)")
            if path:
                write_m3u8(path, files)
                self.status_label.setText(f"Saved playlist with {len(files):,} file(s) to {path}")
        elif clicked == list_button:
            path, _ = QFileDialog.getSaveFileName(self, "Save list", "not-in-rekordbox.txt", "Text files (*.txt)")
            if path:
                write_text_list(path, files)
                self.status_label.setText(f"Saved {len(files):,} path(s) to {path}")
        elif clicked == copy_button:
            self._copy_untracked_files(files)

    def _copy_untracked_files(self, files):
        target_dir = QFileDialog.getExistingDirectory(self, "Copy files to")
        if not target_dir:
            return

        structure = QMessageBox(self)
        structure.setWindowTitle("Copy files")
        structure.setText("How should the files be copied?")
        flat_button = structure.addButton("All in one folder", QMessageBox.ActionRole)
        keep_button = structure.addButton("Keep subfolders", QMessageBox.ActionRole)
        structure.addButton(QMessageBox.Cancel)
        structure.exec()
        if structure.clickedButton() not in (flat_button, keep_button):
            return
        keep_structure = structure.clickedButton() == keep_button

        progress = QProgressDialog("Copying files...", "Cancel", 0, len(files), self)
        progress.setWindowTitle("Copying")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        folders = self.music_folders()
        copied, skipped, errors = 0, 0, []
        for i, file_path in enumerate(files):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            try:
                base = next((f for f in folders if os.path.normcase(file_path).startswith(os.path.normcase(f))), None)
                if keep_structure and base:
                    dest_path = os.path.join(target_dir, os.path.relpath(file_path, base))
                else:
                    dest_path = os.path.join(target_dir, os.path.basename(file_path))
                if os.path.exists(dest_path):
                    skipped += 1
                    continue
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(file_path, dest_path)
                copied += 1
            except OSError as e:
                errors.append(f"{file_path}: {e}")
        progress.setValue(len(files))

        message = f"Copied {copied:,} of {len(files):,} file(s) to {target_dir}."
        if skipped:
            message += f"\n{skipped:,} already existed there and were not overwritten."
        if errors:
            preview = "\n".join(errors[:10])
            extra = f"\n...and {len(errors) - 10:,} more." if len(errors) > 10 else ""
            QMessageBox.warning(self, "Copied with errors", f"{message}\n\n{preview}{extra}")
        else:
            QMessageBox.information(self, "Copied", message)

    # ----- restore -----

    def restore_backup(self):
        if not self._require(folders=False):
            return
        dialog = RestoreDialog(list_backups(self.db_path), os.path.dirname(self.db_path), self)
        if not dialog.exec() or not dialog.selected:
            return
        backup = dialog.selected
        answer = QMessageBox.warning(
            self,
            "Restore backup",
            f"Replace your current Rekordbox library with this backup?\n\n{backup.title}\n\n"
            "Your current library is backed up first, so this can be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if answer == QMessageBox.Yes and self._confirm_rekordbox_closed():
            self._run(self._restore, (backup,), self._restore_done, "Restoring...")

    def _restore(self, backup, progress=None):
        return restore_backup(self.db_path, backup)

    def _restore_done(self, safety):
        self._update_db_label()
        self.status_label.setText("Backup restored.")
        self.results_area.setPlainText(f"Backup restored.\nYour library from before the restore was saved in:\n{safety.path}")
        QMessageBox.information(
            self,
            "Restored",
            f"The backup was restored.\n\nYour library from before the restore was saved in:\n{safety.path}",
        )
