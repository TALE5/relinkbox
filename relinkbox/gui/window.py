import os
import shutil
from datetime import datetime

from PySide6.QtCore import Qt, QThread
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from relinkbox.gui.workers import (
    RelinkWorker,
    UntrackedFilesWorker,
    UpdateDisplayFilenamesWorker,
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Relinkbox")
        self.setMinimumWidth(800)
        self.setMinimumHeight(520)

        self.db_path = None
        self.music_folder = None
        self.last_backup_path = None
        self.thread = None
        self.worker = None

        root = QWidget()
        layout = QVBoxLayout(root)
        self.setCentralWidget(root)

        self.label = QLabel("Choose files to start...")
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        db_row = QHBoxLayout()
        self.db_button = QPushButton("Select Rekordbox Database")
        self.db_button.clicked.connect(self.select_database)
        db_row.addWidget(self.db_button)

        self.restore_button = QPushButton("Restore Backup")
        self.restore_button.clicked.connect(self.restore_backup)
        self.restore_button.setEnabled(False)
        self.restore_button.setToolTip("Restore the database from a backup")
        db_row.addWidget(self.restore_button)
        layout.addLayout(db_row)

        self.music_button = QPushButton("Select Music Folder")
        self.music_button.clicked.connect(self.select_folder)
        layout.addWidget(self.music_button)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        actions = QHBoxLayout()
        self.run_button = QPushButton("Run Relinker")
        self.run_button.clicked.connect(self.run_relinker)
        actions.addWidget(self.run_button)

        self.find_button = QPushButton("Find Untracked Files")
        self.find_button.clicked.connect(self.find_untracked)
        actions.addWidget(self.find_button)

        self.update_display_button = QPushButton("Fix Display Names")
        self.update_display_button.clicked.connect(self.update_display_names)
        self.update_display_button.setToolTip(
            "Updates displayed filenames without changing file paths"
        )
        actions.addWidget(self.update_display_button)
        layout.addLayout(actions)

        layout.addWidget(QLabel("Results:"))
        self.results_area = QTextEdit()
        self.results_area.setReadOnly(True)
        self.results_area.setVisible(False)
        layout.addWidget(self.results_area)

        self.auto_detect_database()

    def closeEvent(self, event):
        self._stop_worker()
        event.accept()

    def auto_detect_database(self):
        common_paths = [
            os.path.expanduser("~/AppData/Roaming/Pioneer/rekordbox/master.db"),
            os.path.expanduser("~/Library/Application Support/Pioneer/rekordbox/master.db"),
            os.path.expanduser("~/Pioneer/rekordbox/master.db"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                self.db_path = path
                self.db_button.setText(f"Database: {os.path.basename(path)}")
                self.update_status()
                break

    def select_database(self):
        default_db = os.path.expanduser("~/AppData/Roaming/Pioneer/rekordbox/master.db")
        start_dir = os.path.dirname(default_db) if os.path.exists(default_db) else ""
        if self.db_path and os.path.exists(self.db_path):
            start_dir = os.path.dirname(self.db_path)

        file, _ = QFileDialog.getOpenFileName(
            self, "Open Rekordbox Database", start_dir, "Database Files (*.db)"
        )
        if not file:
            return

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText("Please close Rekordbox before continuing.")
        msg.setInformativeText("The database cannot be modified while Rekordbox is running.")
        msg.setWindowTitle("Close Rekordbox")
        msg.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        if msg.exec() == QMessageBox.Cancel:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = os.path.basename(file).replace(".db", f"_backup_{timestamp}.db")
        backup_path = os.path.join(os.path.dirname(file), backup_filename)

        try:
            shutil.copy2(file, backup_path)
            self.db_path = file
            self.last_backup_path = backup_path
            self.db_button.setText(f"Database: {os.path.basename(file)} (backed up)")
            self.restore_button.setEnabled(True)
            self.update_status()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to create backup: {e}")

    def select_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Music Folder")
        if folder:
            self.music_folder = folder
            self.music_button.setText(f"Music: {os.path.basename(folder)}")
            self.update_status()

    def update_status(self):
        parts = []
        if self.db_path:
            parts.append(f"Database: {os.path.basename(self.db_path)}")
        if self.music_folder:
            parts.append(f"Music: {os.path.basename(self.music_folder)}")
        self.label.setText(" | ".join(parts) if parts else "Choose files to start...")

    def update_progress(self, current, total):
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        if current < 100:
            self.label.setText(f"Working... {current}%")
        else:
            self.label.setText("Complete!")
        QApplication.processEvents()

    def _set_busy(self, busy):
        self.run_button.setEnabled(not busy)
        self.find_button.setEnabled(not busy)
        self.update_display_button.setEnabled(not busy)
        self.db_button.setEnabled(not busy)
        self.music_button.setEnabled(not busy)

    def _stop_worker(self):
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(5000)
        if self.worker is not None:
            self.worker.deleteLater()
        if self.thread is not None:
            self.thread.deleteLater()
        self.worker = None
        self.thread = None

    def _start_worker(self, worker, on_finished):
        self._stop_worker()
        self.worker = worker
        self.thread = QThread()
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.worker.progress.connect(self.update_progress)
        self.thread.start()

    def run_relinker(self):
        if not self.db_path or not self.music_folder:
            QMessageBox.warning(self, "Missing Info", "Please select database and music folder.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.results_area.setVisible(False)
        self._set_busy(True)
        self._start_worker(
            RelinkWorker(self.db_path, self.music_folder),
            self.show_result,
        )

    def find_untracked(self):
        if not self.db_path or not self.music_folder:
            QMessageBox.warning(self, "Missing Info", "Please select database and music folder.")
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.results_area.setVisible(False)
        self._set_busy(True)
        self._start_worker(
            UntrackedFilesWorker(self.db_path, self.music_folder),
            self.show_untracked_files,
        )

    def update_display_names(self):
        if not self.db_path:
            QMessageBox.warning(self, "Missing Database", "Please select a Rekordbox database first.")
            return

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Information)
        msg.setText("This will update display filenames only.")
        msg.setInformativeText("File paths will not be changed. Continue?")
        msg.setWindowTitle("Fix Display Names")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if msg.exec() != QMessageBox.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.results_area.setVisible(False)
        self._set_busy(True)
        self._start_worker(
            UpdateDisplayFilenamesWorker(self.db_path),
            self.show_display_update_result,
        )

    def show_result(self, stats):
        self.progress_bar.setVisible(False)
        self._set_busy(False)
        self.update_status()
        self._stop_worker()

        if "error" in stats:
            QMessageBox.critical(self, "Error", f"An error occurred:\n\n{stats['error']}")
            return

        QMessageBox.information(
            self,
            "Done",
            (
                "Processing complete!\n\n"
                f"Tracks in database: {stats['total_tracks']}\n"
                f"Music files found: {stats['total_music_files']}\n"
                f"Tracks relinked: {stats['updated_tracks']}\n"
            ),
        )

    def show_display_update_result(self, stats):
        self.progress_bar.setVisible(False)
        self._set_busy(False)
        self.update_status()
        self._stop_worker()

        if "error" in stats:
            QMessageBox.critical(self, "Error", f"An error occurred:\n\n{stats['error']}")
            return

        QMessageBox.information(
            self,
            "Done",
            (
                "Display names updated!\n\n"
                f"Tracks checked: {stats['total_tracks']}\n"
                f"Filenames updated: {stats['updated_filenames']}\n"
            ),
        )

    def show_untracked_files(self, files):
        self.progress_bar.setVisible(False)
        self._set_busy(False)
        self.update_status()
        self._stop_worker()
        self.results_area.setVisible(True)

        if not files:
            self.results_area.setText("No untracked files found.")
            QMessageBox.information(
                self,
                "No Untracked Files",
                "All music files in the selected folder are already in Rekordbox.",
            )
            return

        self.results_area.setText(
            f"Found {len(files)} untracked files:\n\n" + "\n".join(files)
        )

        msg_box = QMessageBox()
        msg_box.setWindowTitle("Untracked Files")
        msg_box.setText(f"Found {len(files)} music files not in your Rekordbox database.")
        msg_box.setInformativeText("What would you like to do with these files?")
        save_list_button = msg_box.addButton("Save List to File", QMessageBox.ActionRole)
        copy_files_button = msg_box.addButton("Copy Files to Folder", QMessageBox.ActionRole)
        msg_box.addButton(QMessageBox.Cancel)
        msg_box.exec()

        if msg_box.clickedButton() == save_list_button:
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save Untracked Files List", "", "Text Files (*.txt)"
            )
            if save_path:
                with open(save_path, "w", encoding="utf-8") as handle:
                    handle.write("\n".join(files))
                QMessageBox.information(
                    self, "List Saved", f"Saved {len(files)} paths to {save_path}"
                )
        elif msg_box.clickedButton() == copy_files_button:
            self._copy_untracked_files(files)

    def _copy_untracked_files(self, files):
        target_dir = QFileDialog.getExistingDirectory(
            self, "Select Destination Folder for Untracked Files"
        )
        if not target_dir:
            return

        structure_msg = QMessageBox()
        structure_msg.setWindowTitle("Copy Structure")
        structure_msg.setText("How would you like to copy the files?")
        flat_button = structure_msg.addButton("Flat (all files in one folder)", QMessageBox.ActionRole)
        structure_button = structure_msg.addButton(
            "Preserve structure (maintain subfolders)", QMessageBox.ActionRole
        )
        structure_msg.exec()
        preserve_structure = structure_msg.clickedButton() == structure_button

        progress = QProgressDialog("Copying files...", "Cancel", 0, len(files), self)
        progress.setWindowTitle("Copy Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        copied = 0
        errors = []
        for i, file_path in enumerate(files):
            if progress.wasCanceled():
                break
            progress.setValue(i)
            try:
                if preserve_structure and self.music_folder and file_path.startswith(self.music_folder):
                    dest_path = os.path.join(target_dir, os.path.relpath(file_path, self.music_folder))
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                else:
                    dest_path = os.path.join(target_dir, os.path.basename(file_path))
                shutil.copy2(file_path, dest_path)
                copied += 1
            except Exception as e:
                errors.append(f"{file_path}: {e}")

        progress.setValue(len(files))
        if errors:
            preview = "\n".join(errors[:10])
            extra = f"\n... and {len(errors) - 10} more errors." if len(errors) > 10 else ""
            QMessageBox.warning(
                self,
                "Copy Complete with Errors",
                f"Copied {copied} of {len(files)} files.\n\n{preview}{extra}",
            )
        else:
            QMessageBox.information(
                self, "Copy Complete", f"Successfully copied {copied} files to {target_dir}"
            )

    def restore_backup(self):
        if not self.db_path:
            QMessageBox.warning(self, "No Database Selected", "Please select a database first.")
            return

        use_last = False
        if self.last_backup_path and os.path.exists(self.last_backup_path):
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Question)
            msg.setText("Use most recent backup or select another?")
            msg.setInformativeText(f"Most recent backup: {os.path.basename(self.last_backup_path)}")
            most_recent = msg.addButton("Use Most Recent", QMessageBox.ActionRole)
            select_another = msg.addButton("Select Another", QMessageBox.ActionRole)
            cancel = msg.addButton(QMessageBox.Cancel)
            msg.exec()
            if msg.clickedButton() == cancel:
                return
            use_last = msg.clickedButton() == most_recent

        backup_path = self.last_backup_path if use_last else None
        if not use_last:
            backup_path, _ = QFileDialog.getOpenFileName(
                self,
                "Select Backup File",
                os.path.dirname(self.db_path),
                "Database Files (*.db)",
            )
            if not backup_path:
                return

        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText("Restoring will overwrite the current database.")
        msg.setInformativeText(f"Restore from:\n{os.path.basename(backup_path)}?")
        msg.setWindowTitle("Confirm Database Restore")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        if msg.exec() != QMessageBox.Yes:
            return

        QMessageBox.information(
            self,
            "Close Rekordbox",
            "Make sure Rekordbox is closed before restoring.",
        )

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            pre_restore_backup = os.path.join(
                os.path.dirname(self.db_path),
                f"pre_restore_{os.path.basename(self.db_path).replace('.db', '')}_{timestamp}.db",
            )
            shutil.copy2(self.db_path, pre_restore_backup)
            shutil.copy2(backup_path, self.db_path)
            self.db_button.setText(f"Database: {os.path.basename(self.db_path)}")
            self.update_status()
            QMessageBox.information(
                self,
                "Restore Complete",
                (
                    f"Restored from {os.path.basename(backup_path)}.\n\n"
                    f"Previous database saved as {os.path.basename(pre_restore_backup)}."
                ),
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to restore database: {e}")
