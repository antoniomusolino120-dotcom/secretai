"""CI-only backup/restore and SQLite->PostgreSQL migration proof on disposable DBs."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import uuid
from sqlalchemy import create_engine,text
from sqlalchemy.engine import make_url
from cryptography.fernet import Fernet
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.db import migrate
from scripts.backup import backup,restore
from scripts.migrate_database import copy_database

def main():
    url=make_url(os.environ['SECRET_AI_TEST_DATABASE_URL'])
    if not url.database.endswith('_test'):raise RuntimeError('Refusing a non-test database')
    names=['secretai_verify_'+uuid.uuid4().hex for _ in range(3)]
    root=create_engine(url,isolation_level='AUTOCOMMIT')
    engines=[]
    try:
        with root.connect() as db:
            for name in names:db.execute(text('CREATE DATABASE '+name))
        engines=[create_engine(url.set(database=name)) for name in names]
        source,target,import_target=engines
        migrate(source)
        with source.begin() as db:db.execute(text("INSERT INTO organizations(id,name) VALUES (77,'Restore verification')"))
        os.environ['SECRET_AI_ENCRYPTION_KEY']=Fernet.generate_key().decode()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'database.backup'
            backup(source,path);restore(target,path)
            with target.connect() as db:assert db.execute(text('SELECT name FROM organizations WHERE id=77')).scalar()=='Restore verification'
            local=Path(directory)/'legacy.sqlite3'
            with sqlite3.connect(local) as db:
                db.executescript("CREATE TABLE organizations(id INTEGER PRIMARY KEY,name TEXT NOT NULL);INSERT INTO organizations VALUES (91,'Imported organization');")
            counts=copy_database(local,import_target);assert counts['organizations']==1
            with import_target.begin() as db:
                assert db.execute(text('SELECT name FROM organizations WHERE id=91')).scalar()=='Imported organization'
                assert db.execute(text("INSERT INTO organizations(name) VALUES ('Next organization') RETURNING id")).scalar()==92
        print('PostgreSQL encrypted backup/restore and read-only SQLite import verified')
    finally:
        for engine in engines:engine.dispose()
        with root.connect() as db:
            for name in names:db.execute(text('DROP DATABASE IF EXISTS '+name+' WITH (FORCE)'))
        root.dispose()
if __name__=='__main__':main()
