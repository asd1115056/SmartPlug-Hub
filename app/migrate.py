"""Schema migrations — Alembic, applied at startup and from the alembic CLI."""

import logging
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, Engine, create_engine, event, inspect

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).parent / "migrations"
# The schema the last release before Alembic left every database in
_BASELINE_REVISION = "0001"


class MigrationError(Exception):
    """A migration left the database inconsistent; it was rolled back."""


def migration_engine(path: Path) -> Engine:
    """Engine for schema changes: transactional DDL, foreign keys not enforced until commit."""
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def _connect(dbapi_conn: Any, _record: Any) -> None:
        # Batch migrations rebuild a table (copy, drop, rename); enforcing foreign keys would
        # make dropping a referenced table fail or cascade. upgrade() checks them before commit.
        dbapi_conn.execute("PRAGMA foreign_keys=OFF")
        # The driver alone leaves DDL outside any transaction, so a failing migration could stop
        # half-applied. With autocommit here, SQLAlchemy's own BEGIN (below) covers everything.
        dbapi_conn.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin(conn: Connection) -> None:
        conn.exec_driver_sql("BEGIN")

    return engine


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_SCRIPT_DIR))
    cfg.attributes["connection"] = connection
    return cfg


def upgrade(path: Path) -> None:
    """Bring the database at path to the latest revision in one transaction. Blocking."""
    engine = migration_engine(path)
    try:
        with engine.begin() as conn:
            before = MigrationContext.configure(conn).get_current_revision()
            cfg = alembic_config(conn)
            if before is None and inspect(conn).has_table("device"):
                command.stamp(cfg, _BASELINE_REVISION)   # made before Alembic: adopt as is
            command.upgrade(cfg, "head")
            if violations := conn.exec_driver_sql("PRAGMA foreign_key_check").all():
                raise MigrationError(f"Foreign key violations after migrating: {violations}")
            after = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    if after != before:
        logger.info("Database migrated: %s → %s", before or "empty", after)
