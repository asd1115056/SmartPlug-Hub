"""Alembic environment: migrate the connection the app passes in, or open one for the CLI."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, String
from sqlalchemy.types import TypeDecorator, TypeEngine
from sqlmodel import SQLModel

from app.db import DB_PATH  # importing app.db also registers its tables on SQLModel.metadata
from app.migrate import migration_engine

config = context.config


def compare_type(
    _context: object, _inspected_column: object, _metadata_column: object,
    inspected_type: TypeEngine, metadata_type: TypeEngine,
) -> bool | None:
    """Treat TEXT, VARCHAR and VARCHAR(n) as the same type; defer to Alembic for the rest."""
    # SQLite stores them identically and never enforces a length. Columns added by hand before
    # Alembic are TEXT while the models say VARCHAR, which would otherwise show up as a change.
    if isinstance(inspected_type, String) and isinstance(_unwrap(metadata_type), String):
        return False
    return None


def _unwrap(type_: TypeEngine) -> TypeEngine:
    # sqlmodel's AutoString is a TypeDecorator around String, not a String subclass
    return type_.impl if isinstance(type_, TypeDecorator) else type_


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=SQLModel.metadata,
        compare_type=compare_type,
        render_as_batch=True,   # SQLite can't ALTER most things: rebuild the table instead
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise NotImplementedError("Offline (--sql) mode is not supported")

connection = config.attributes.get("connection")
if connection is not None:
    # Started by the app: it owns the transaction and the logging setup
    run_migrations(connection)
else:
    if config.config_file_name is not None:
        fileConfig(config.config_file_name)
    engine = migration_engine(DB_PATH)
    try:
        with engine.begin() as conn:
            run_migrations(conn)
    finally:
        engine.dispose()
