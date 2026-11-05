from alembic import context
from app.db import build_engine

config = context.config


def run(connection):
    context.configure(connection=connection, render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


if config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    with build_engine().begin() as connection:
        run(connection)
