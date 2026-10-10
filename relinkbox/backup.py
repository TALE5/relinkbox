import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from relinkbox.rekordbox import ensure_rekordbox_closed

log = logging.getLogger(__name__)

BACKUPS_FOLDER = "Relinkbox backups"
DB_SIDECARS = ("-wal", "-shm", "-journal")
EXTRA_FILES = ("masterPlaylists6.xml",)
MANIFEST = "backup.json"
LEGACY_PATTERN = re.compile(r"(_backup_|^pre_restore_).*\.db$", re.IGNORECASE)
REKORDBOX_PATTERN = re.compile(r"^master\.backup.*\.db$", re.IGNORECASE)


class BackupError(RuntimeError):
    pass


@dataclass
class Backup:
    path: Path
    db_file: Path
    label: str
    created: datetime
    legacy: bool = False

    @property
    def anlz_dir(self):
        return self.path / "anlz"

    @property
    def title(self):
        stamp = self.created.strftime("%Y-%m-%d %H:%M:%S")
        return f"{stamp}  {self.label}" if self.label else stamp

    def add_anlz(self, share_dir, anlz_file):
        anlz_file = Path(anlz_file)
        try:
            rel = anlz_file.relative_to(share_dir)
        except ValueError:
            rel = Path(anlz_file.name)
        target = self.anlz_dir / rel
        if target.exists():
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(anlz_file, target)

    def write_text(self, name, text):
        (self.path / name).write_text(text, encoding="utf-8")


def backups_root(db_path):
    return Path(db_path).parent / BACKUPS_FOLDER


def share_dir(db_path):
    return Path(db_path).parent / "share"


def _copy_verified(src, dst):
    shutil.copy2(src, dst)
    if os.path.getsize(src) != os.path.getsize(dst):
        raise BackupError(f"Backup copy of {src} is incomplete.")


def create_backup(db_path, label):
    db_path = Path(db_path)
    if not db_path.exists():
        raise BackupError(f"Database not found: {db_path}")
    created = datetime.now()
    root = backups_root(db_path)
    folder = root / created.strftime("%Y-%m-%d_%H-%M-%S")
    suffix = 1
    while folder.exists():
        suffix += 1
        folder = root / f"{created.strftime('%Y-%m-%d_%H-%M-%S')}_{suffix}"
    folder.mkdir(parents=True)

    try:
        _copy_verified(db_path, folder / db_path.name)
        for sidecar in DB_SIDECARS:
            src = Path(str(db_path) + sidecar)
            if src.exists():
                _copy_verified(src, folder / src.name)
        for name in EXTRA_FILES:
            src = db_path.parent / name
            if src.exists():
                _copy_verified(src, folder / name)
        manifest = {"label": label, "created": created.isoformat(), "db_file": db_path.name}
        (folder / MANIFEST).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception as e:
        shutil.rmtree(folder, ignore_errors=True)
        raise BackupError(f"Could not create backup: {e}") from e

    log.info("Created backup %s (%s)", folder, label)
    return Backup(path=folder, db_file=folder / db_path.name, label=label, created=created)


def _read_backup_folder(folder):
    manifest_path = folder / MANIFEST
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        db_file = folder / data["db_file"]
        if not db_file.exists():
            return None
        return Backup(
            path=folder,
            db_file=db_file,
            label=data.get("label", ""),
            created=datetime.fromisoformat(data["created"]),
        )
    except Exception as e:
        log.warning("Ignoring unreadable backup %s: %s", folder, e)
        return None


def list_backups(db_path):
    db_path = Path(db_path)
    backups = []
    root = backups_root(db_path)
    if root.exists():
        for folder in root.iterdir():
            if folder.is_dir():
                backup = _read_backup_folder(folder)
                if backup:
                    backups.append(backup)
    for file in db_path.parent.glob("*.db"):
        if LEGACY_PATTERN.search(file.name):
            label = f"Older Relinkbox backup ({file.name})"
        elif REKORDBOX_PATTERN.search(file.name):
            label = f"Rekordbox's own backup ({file.name})"
        else:
            continue
        backups.append(
            Backup(
                path=file.parent,
                db_file=file,
                label=label,
                created=datetime.fromtimestamp(file.stat().st_mtime),
                legacy=True,
            )
        )
    backups.sort(key=lambda b: b.created, reverse=True)
    return backups


def backup_from_file(db_file):
    db_file = Path(db_file)
    backup = _read_backup_folder(db_file.parent)
    if backup and backup.db_file == db_file:
        return backup
    return Backup(
        path=db_file.parent,
        db_file=db_file,
        label=db_file.name,
        created=datetime.fromtimestamp(db_file.stat().st_mtime),
        legacy=True,
    )


def restore_backup(db_path, backup):
    """Restore a backup over the live library. Returns the safety backup made first."""
    ensure_rekordbox_closed()
    db_path = Path(db_path)
    if not backup.db_file.exists():
        raise BackupError(f"Backup file not found: {backup.db_file}")

    safety = create_backup(db_path, f"Before restoring {backup.title}")
    share = share_dir(db_path)
    anlz_files = []
    if not backup.legacy and backup.anlz_dir.exists():
        anlz_files = [p for p in backup.anlz_dir.rglob("*") if p.is_file()]
        for src in anlz_files:
            live = share / src.relative_to(backup.anlz_dir)
            if live.exists():
                safety.add_anlz(share, live)

    _copy_verified(backup.db_file, db_path)
    for sidecar in DB_SIDECARS:
        live = Path(str(db_path) + sidecar)
        saved = Path(str(backup.db_file) + sidecar)
        if saved.exists() and not backup.legacy:
            _copy_verified(saved, live)
        elif live.exists():
            live.unlink()
    if not backup.legacy:
        for name in EXTRA_FILES:
            src = backup.path / name
            if src.exists():
                _copy_verified(src, db_path.parent / name)
        for src in anlz_files:
            live = share / src.relative_to(backup.anlz_dir)
            live.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, live)

    log.info("Restored %s from %s (safety backup %s)", db_path, backup.path, safety.path)
    return safety
