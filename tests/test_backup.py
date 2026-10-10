import pytest

from relinkbox import backup as backup_module
from relinkbox.backup import backup_from_file, create_backup, list_backups, restore_backup


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_module, "ensure_rekordbox_closed", lambda: None)
    lib = tmp_path / "rekordbox"
    lib.mkdir()
    (lib / "master.db").write_bytes(b"original")
    (lib / "masterPlaylists6.xml").write_text("<playlists/>")
    anlz = lib / "share" / "PIONEER" / "USBANLZ" / "abc" / "ANLZ0000.DAT"
    anlz.parent.mkdir(parents=True)
    anlz.write_bytes(b"anlz-original")
    return lib


def test_backup_contains_database_and_playlists(library):
    backup = create_backup(library / "master.db", "Test")
    assert backup.db_file.read_bytes() == b"original"
    assert (backup.path / "masterPlaylists6.xml").exists()
    assert [b.label for b in list_backups(library / "master.db")] == ["Test"]


def test_restore_puts_back_database_and_anlz_and_keeps_safety_copy(library):
    db = library / "master.db"
    anlz = library / "share" / "PIONEER" / "USBANLZ" / "abc" / "ANLZ0000.DAT"
    backup = create_backup(db, "Before change")
    backup.add_anlz(library / "share", anlz)

    db.write_bytes(b"changed")
    anlz.write_bytes(b"anlz-changed")
    (library / "master.db-wal").write_bytes(b"stale wal")

    safety = restore_backup(db, backup)

    assert db.read_bytes() == b"original"
    assert anlz.read_bytes() == b"anlz-original"
    assert not (library / "master.db-wal").exists()
    assert safety.db_file.read_bytes() == b"changed"
    assert (safety.path / "master.db-wal").read_bytes() == b"stale wal"
    assert (safety.anlz_dir / "PIONEER" / "USBANLZ" / "abc" / "ANLZ0000.DAT").read_bytes() == b"anlz-changed"


def test_older_backups_are_listed_and_restorable(library):
    legacy = library / "master_backup_20250101_120000.db"
    legacy.write_bytes(b"legacy")
    (library / "master.backup.20261008.db").write_bytes(b"rekordbox")
    labels = [b.label for b in list_backups(library / "master.db")]
    assert any("Older Relinkbox backup" in label for label in labels)
    assert any("Rekordbox's own backup" in label for label in labels)

    restore_backup(library / "master.db", backup_from_file(legacy))
    assert (library / "master.db").read_bytes() == b"legacy"


def test_restore_refuses_while_rekordbox_runs(library, monkeypatch):
    from relinkbox.rekordbox import RekordboxRunningError

    def running():
        raise RekordboxRunningError()

    backup = create_backup(library / "master.db", "x")
    monkeypatch.setattr(backup_module, "ensure_rekordbox_closed", running)
    with pytest.raises(RekordboxRunningError):
        restore_backup(library / "master.db", backup)
    assert (library / "master.db").read_bytes() == b"original"
