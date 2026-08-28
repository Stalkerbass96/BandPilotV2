"""SQLAlchemy session management.

Provides a synchronous session factory and an ``init_db`` helper that upgrades
the database schema with Alembic. SQLite is the MVP database; the engine is
configured with ``check_same_thread=False`` so FastAPI sync route handlers can
share it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

_engine = None
_SessionLocal: sessionmaker | None = None

_LEGACY_REQUIRED_COLUMNS = {
    "users": {"id", "email", "password_hash", "created_at"},
    "byok_configs": {
        "id", "user_id", "provider", "encrypted_key", "base_url", "model",
        "created_at", "updated_at",
    },
    "projects": {
        "id", "user_id", "title", "source_filename", "status", "style_label",
        "degraded_mode", "midi_fidelity", "created_at", "updated_at",
    },
    "export_records": {
        "id", "project_id", "format_id", "file_path", "note_count", "created_at",
    },
}


def _alembic_config(database_url: str) -> Config:
    migrations_dir = Path(__file__).with_name("migrations")
    config = Config()
    config.set_main_option("script_location", str(migrations_dir))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def _run_alembic(
    config: Config,
    operation: Callable[[Config, str], None],
    revision: str,
) -> None:
    """Run an Alembic command on the application engine's own connection."""
    if _engine is None:  # pragma: no cover - guarded by init_db
        raise RuntimeError("Database engine is not initialized")
    with _engine.begin() as connection:
        config.attributes["connection"] = connection
        operation(config, revision)


def _upgrade_schema(database_url: str) -> None:
    """Upgrade a fresh or Alembic-managed database to the current schema.

    Early FretPilot builds used ``metadata.create_all`` without a version table.
    When such a database is found, add the two columns introduced since that
    schema and stamp it at the initial revision before future migrations run.
    """
    if _engine is None:  # pragma: no cover - guarded by init_db
        raise RuntimeError("Database engine is not initialized")

    inspector = inspect(_engine)
    table_names = set(inspector.get_table_names())
    config = _alembic_config(database_url)

    if not table_names:
        _run_alembic(config, command.upgrade, "head")
        return

    if "alembic_version" not in table_names:
        legacy_tables = set(_LEGACY_REQUIRED_COLUMNS)
        if not legacy_tables.issubset(table_names):
            raise RuntimeError(
                "Existing database is not a recognized FretPilot schema; "
                "refusing to stamp it automatically."
            )
        for table, required_columns in _LEGACY_REQUIRED_COLUMNS.items():
            actual_columns = {
                column["name"] for column in inspector.get_columns(table)
            }
            if not required_columns.issubset(actual_columns):
                raise RuntimeError(
                    "Existing database is not a recognized FretPilot schema; "
                    f"table {table!r} is missing expected columns."
                )
        project_columns = {column["name"] for column in inspector.get_columns("projects")}
        with _engine.begin() as connection:
            if "instrument_family" not in project_columns:
                connection.execute(
                    text(
                        "ALTER TABLE projects ADD COLUMN instrument_family "
                        "VARCHAR(32) NOT NULL DEFAULT 'guitar'"
                    )
                )
            if "track_summary" not in project_columns:
                connection.execute(text("ALTER TABLE projects ADD COLUMN track_summary TEXT"))
        # The recognized metadata-created schema matches revision 0001 after
        # the two project columns above are added.  Stamping ``head`` here
        # would silently skip every later migration and leave a partially
        # upgraded database.
        _run_alembic(config, command.stamp, "20260823_0001")
        _run_alembic(config, command.upgrade, "head")
        return

    _run_alembic(config, command.upgrade, "head")


def init_db(database_url: str) -> None:
    """Create the engine and migrate all tables. Called once at app startup."""
    global _engine, _SessionLocal
    connect_args = (
        {"check_same_thread": False}
        if database_url.startswith("sqlite")
        else {}
    )
    _engine = create_engine(database_url, connect_args=connect_args, echo=False)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    _upgrade_schema(database_url)


def get_engine():
    """Return the current engine (raises if init_db was not called)."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context-managed DB session that commits on success, rolls back on error."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["init_db", "get_engine", "session_scope", "get_db"]
