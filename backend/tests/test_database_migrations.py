"""Database startup must be migration-driven and reject unknown schemas."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import inspect

from fretpilot.db.session import get_engine, init_db


def test_fresh_database_upgrades_to_head(tmp_path) -> None:
    database = tmp_path / "fresh.db"
    init_db(f"sqlite:///{database}")

    inspector = inspect(get_engine())
    assert set(inspector.get_table_names()) == {
        "alembic_version",
        "byok_configs",
        "export_records",
        "projects",
        "repair_jobs",
        "score_commands",
        "score_documents",
        "score_revisions",
        "score_snapshots",
        "users",
    }
    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    assert {"instrument_family", "track_summary"} <= project_columns
    repair_job_columns = {
        column["name"] for column in inspector.get_columns("repair_jobs")
    }
    assert "result_json" in repair_job_columns
    export_columns = {
        column["name"] for column in inspector.get_columns("export_records")
    }
    assert {"revision_id", "revision_hash"} <= export_columns
    revision_uniques = {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("score_revisions")
    }
    assert ("document_id", "revision_number") in revision_uniques


def test_in_memory_database_uses_application_connection() -> None:
    init_db("sqlite:///:memory:")
    assert "projects" in inspect(get_engine()).get_table_names()


def test_unknown_existing_schema_is_not_stamped(tmp_path) -> None:
    database = tmp_path / "foreign.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")

    with pytest.raises(RuntimeError, match="not a recognized FretPilot schema"):
        init_db(f"sqlite:///{database}")


def test_recognized_pre_alembic_schema_is_adopted(tmp_path) -> None:
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, email TEXT, password_hash TEXT, created_at DATETIME
            );
            CREATE TABLE byok_configs (
                id INTEGER PRIMARY KEY, user_id INTEGER, provider TEXT,
                encrypted_key TEXT, base_url TEXT, model TEXT,
                created_at DATETIME, updated_at DATETIME
            );
            CREATE TABLE projects (
                id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT,
                source_filename TEXT, status TEXT, style_label TEXT,
                degraded_mode BOOLEAN, midi_fidelity FLOAT,
                created_at DATETIME, updated_at DATETIME
            );
            CREATE TABLE export_records (
                id INTEGER PRIMARY KEY, project_id INTEGER, format_id TEXT,
                file_path TEXT, note_count INTEGER, created_at DATETIME
            );
            """
        )

    init_db(f"sqlite:///{database}")
    inspector = inspect(get_engine())
    project_columns = {column["name"] for column in inspector.get_columns("projects")}
    assert {"instrument_family", "track_summary"} <= project_columns
    assert {
        "alembic_version",
        "repair_jobs",
        "score_documents",
        "score_revisions",
        "score_snapshots",
        "score_commands",
    } <= set(inspector.get_table_names())
