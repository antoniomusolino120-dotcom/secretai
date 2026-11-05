"""Encrypted full database backups; environment provides URL and Fernet key.

Usage: python scripts/backup.py backup /private/path/secretai.backup.fernet
       python scripts/backup.py restore /private/path/secretai.backup.fernet
Restore refuses a nonempty database. Keep the encryption key off the backup host.
"""
import argparse
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import build_engine
from app.secrets import cipher
from sqlalchemy import inspect


def pg_environment(url):
    env = os.environ.copy()
    env.update({"PGHOST": url.host or "localhost", "PGPORT": str(url.port or 5432),
                "PGUSER": url.username or "", "PGPASSWORD": url.password or "", "PGDATABASE": url.database or ""})
    if url.query.get("sslmode"):
        env["PGSSLMODE"] = url.query["sslmode"]
    return env


def backup(engine, path):
    if path.exists():
        raise RuntimeError("Backup destination already exists")
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory) / "database.dump"
        if engine.dialect.name == "sqlite":
            with sqlite3.connect(engine.url.database) as source, sqlite3.connect(temporary) as target:
                source.backup(target)
        else:
            subprocess.run([os.getenv("PG_DUMP_BIN","pg_dump"), "--format=custom", "--no-owner", "--no-privileges", "--file", str(temporary)],
                           env=pg_environment(engine.url), check=True, capture_output=True)
        encrypted = cipher().encrypt(temporary.read_bytes())
        with path.open("xb") as output:
            os.chmod(path, 0o600)
            output.write(encrypted)


def restore(engine, path):
    if inspect(engine).get_table_names():
        raise RuntimeError("Restore requires an empty target database")
    data = cipher().decrypt(path.read_bytes())
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory) / "database.dump"
        temporary.write_bytes(data)
        if engine.dialect.name == "sqlite":
            with sqlite3.connect(temporary) as source, sqlite3.connect(engine.url.database) as target:
                source.backup(target)
        else:
            subprocess.run([os.getenv("PG_RESTORE_BIN","pg_restore"), "--no-owner", "--no-privileges", "--exit-on-error", "--dbname", engine.url.database, str(temporary)],
                           env=pg_environment(engine.url), check=True, capture_output=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["backup", "restore"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        globals()[args.operation](build_engine(), args.path)
        print("Operation completed")
    except Exception:
        # Provider exceptions can contain database credentials.
        print("Operation failed. Check destination, database tools and encryption key.", file=sys.stderr)
        sys.exit(1)
