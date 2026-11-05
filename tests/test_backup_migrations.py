import os
import sqlite3

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from app.db import migrate, make_database
from scripts.backup import backup, restore


def test_legacy_database_migrates_without_losing_records(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE organizations(id INTEGER PRIMARY KEY,name TEXT NOT NULL);
            CREATE TABLE services(id INTEGER PRIMARY KEY,organization_id INTEGER NOT NULL,name TEXT NOT NULL,duration_minutes INTEGER NOT NULL);
            CREATE TABLE appointments(id INTEGER PRIMARY KEY,organization_id INTEGER NOT NULL,customer TEXT NOT NULL,service_id INTEGER NOT NULL,starts_at TEXT NOT NULL,ends_at TEXT NOT NULL);
            INSERT INTO organizations VALUES (4,'Existing company');
            INSERT INTO services VALUES (8,4,'Existing service',60);
            INSERT INTO appointments VALUES (11,4,'Existing customer',8,'2027-01-01T10:00:00+00:00','2027-01-01T11:00:00+00:00');
        """)
    engine = create_engine("sqlite:///"+str(path))
    migrate(engine)
    migrate(engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT customer FROM appointments WHERE id=11")).scalar() == "Existing customer"
        assert db.execute(text("SELECT timezone FROM organizations WHERE id=4")).scalar() == "Europe/Rome"
        assert db.execute(text("SELECT status FROM appointments WHERE id=11")).scalar() == "confirmed"
    engine.dispose()


def test_encrypted_backup_restore_and_nonempty_target_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_AI_ENCRYPTION_KEY", Fernet.generate_key().decode())
    source = create_engine("sqlite:///"+str(tmp_path / "source.sqlite3"))
    target = create_engine("sqlite:///"+str(tmp_path / "target.sqlite3"))
    migrate(source)
    with source.begin() as db:
        db.execute(text("INSERT INTO organizations(name) VALUES ('Backup test company')"))
    path = tmp_path / "encrypted.backup"
    backup(source, path)
    assert b"Backup test company" not in path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    restore(target, path)
    with target.connect() as db:
        assert db.execute(text("SELECT name FROM organizations")).scalar() == "Backup test company"
    try:
        restore(target, path)
        raise AssertionError("Nonempty restore must be refused")
    except RuntimeError:
        pass
    source.dispose()
    target.dispose()
