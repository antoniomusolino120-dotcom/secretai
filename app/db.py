"""SQLAlchemy transactions shared by HTTP routes and background workers.

The small positional-parameter adapter keeps the original repository API while
all connections, binding, pooling and transactions are owned by SQLAlchemy.
"""
import os
import re
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
HEAD = "0007_personalization"
ID_TABLES = {"organizations", "users", "services", "appointments", "meta_messages",
             "contacts", "conversations", "messages", "audit_events", "jobs"}


def database_url():
    url = os.getenv("SECRET_AI_DATABASE_URL")
    if url:
        if url.startswith("postgres://"):
            url = "postgresql+psycopg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+psycopg://" + url[len("postgresql://"):]
        return url
    return "sqlite:///" + str(Path(os.getenv("SECRET_AI_DB", str(ROOT / "secretai.db"))).resolve())


def build_engine():
    url = database_url()
    engine = create_engine(url, pool_pre_ping=True, poolclass=NullPool,
                           **({"connect_args": {"timeout": 10}} if url.startswith("sqlite") else {}))
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=10000")
            connection.execute("PRAGMA journal_mode=WAL")
    return engine


def migrate(engine, revision="head"):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def initialize(engine):
    if os.getenv("SECRET_AI_ENV", "development") == "production":
        if engine.dialect.name != "postgresql":
            raise RuntimeError("Production requires a dedicated PostgreSQL database")
        with engine.connect() as connection:
            if connection.execute(text("SELECT version_num FROM alembic_version")).scalar() != HEAD:
                raise RuntimeError("Run alembic upgrade head before starting the application")
    else:
        migrate(engine)


class Result:
    def __init__(self, result, returned_id=False, sqlite_insert=False):
        self.result = result
        self.rowcount = result.rowcount
        # psycopg does not expose DBAPI lastrowid, including on SELECT/DDL.
        # PostgreSQL IDs are read exclusively through INSERT ... RETURNING.
        self.lastrowid = result.scalar() if returned_id else (result.lastrowid if sqlite_insert else None)

    def fetchone(self):
        return self.result.mappings().fetchone()

    def fetchall(self):
        return self.result.mappings().fetchall()

    def __iter__(self):
        return iter(self.result.mappings())


class Database:
    def __init__(self, connection):
        self.connection = connection
        self.dialect = connection.dialect.name

    def execute(self, sql, params=()):
        if isinstance(params, dict):
            values = params
        else:
            parts = sql.split("?")
            if len(parts) != len(params) + 1:
                raise ValueError("SQL parameter count mismatch")
            values = {f"p{i}": value for i, value in enumerate(params)}
            sql = "".join(part + (f":p{i}" if i < len(params) else "")
                          for i, part in enumerate(parts))
        if sql.strip().upper() == "BEGIN IMMEDIATE":
            raise RuntimeError("Use database(write=True) before reading or writing")
        # Both supported databases implement ON CONFLICT DO NOTHING.
        if sql.lstrip().upper().startswith("INSERT OR IGNORE INTO"):
            sql = re.sub(r"INSERT OR IGNORE INTO", "INSERT INTO", sql, count=1, flags=re.I)
            sql += " ON CONFLICT DO NOTHING"
        match = re.match(r"\s*INSERT\s+INTO\s+(\w+)", sql, re.I)
        returning = (self.dialect == "postgresql" and match is not None
                     and match.group(1).lower() in ID_TABLES and "RETURNING" not in sql.upper())
        if returning:
            sql += " RETURNING id"
        return Result(self.connection.execute(text(sql), values), returning,
                      sqlite_insert=self.dialect == "sqlite" and match is not None)

    def executescript(self, script):
        # Legacy tests may create already-existing tables. Application DDL lives
        # exclusively in versioned migrations.
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def lock_org(self, organization_id):
        sql = "SELECT id FROM organizations WHERE id=?"
        if self.dialect == "postgresql":
            sql += " FOR UPDATE"
        return self.execute(sql, (organization_id,)).fetchone()


def make_database(engine):
    @contextmanager
    def database(write=False, organization_id=None):
        with engine.connect() as connection:
            try:
                if write and engine.dialect.name == "sqlite":
                    connection.exec_driver_sql("BEGIN IMMEDIATE")
                db = Database(connection)
                if organization_id is not None:
                    db.lock_org(organization_id)
                yield db
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
    return database
