"""Copy a local SQLite database into a NEW empty PostgreSQL database.

The source is opened read-only. Schema is migrated only on the new target.
Target URL comes from SECRET_AI_DATABASE_URL; no credentials on the command line.
"""
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote
from sqlalchemy import create_engine,inspect,MetaData,text
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from app.db import build_engine,migrate


def copy_database(source_path,target):
    if target.dialect.name!='postgresql' or inspect(target).get_table_names():
        raise RuntimeError('An empty dedicated PostgreSQL target is required')
    source_path=Path(source_path).resolve(strict=True)
    source=create_engine('sqlite://',creator=lambda:sqlite3.connect('file:'+quote(str(source_path),safe='/')+'?mode=ro',uri=True))
    migrate(target)
    metadata=MetaData();metadata.reflect(target)
    source_tables=set(inspect(source).get_table_names())
    counts={}
    with source.connect() as src,target.begin() as dst:
        for table in metadata.sorted_tables:
            if table.name=='alembic_version' or table.name not in source_tables:continue
            cols=set(table.columns.keys())
            source_table=__import__('sqlalchemy').Table(table.name,MetaData(),autoload_with=source)
            count=0
            rows=src.execute(source_table.select()).mappings()
            while batch:=rows.fetchmany(500):
                values=[{k:v for k,v in row.items() if k in cols} for row in batch]
                dst.execute(table.insert(),values);count+=len(values)
            counts[table.name]=count
            if 'id' in table.c and isinstance(table.c.id.type,__import__('sqlalchemy').Integer):
                preparer=target.dialect.identifier_preparer
                name=preparer.quote(table.name)
                dst.execute(text(f"SELECT setval(pg_get_serial_sequence(:table_name,'id'), GREATEST(COALESCE(MAX(id),0),1),COALESCE(MAX(id),0)>0) FROM {name}"),{'table_name':table.name})
    source.dispose()
    return counts

if __name__=='__main__':
    try:
        if len(sys.argv)!=2:raise RuntimeError('Specify the source SQLite path')
        print(copy_database(sys.argv[1],build_engine()))
    except Exception:
        print('Copy failed; source unchanged. Check target schema and migration logs.',file=sys.stderr);sys.exit(1)
