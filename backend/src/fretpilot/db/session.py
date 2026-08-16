"""SQLAlchemy session management.

Provides a synchronous session factory and an ``init_db`` helper that creates
all registered tables. SQLite is the MVP database; the engine is configured
with ``check_same_thread=False`` so FastAPI sync route handlers can share it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from fretpilot.db.models import Base

_engine = None
_SessionLocal: sessionmaker | None = None


def init_db(database_url: str) -> None:
    """Create the engine and all tables. Called once at app startup."""
    global _engine, _SessionLocal
    connect_args = (
        {"check_same_thread": False}
        if database_url.startswith("sqlite")
        else {}
    )
    _engine = create_engine(database_url, connect_args=connect_args, echo=False)
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=_engine)


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
