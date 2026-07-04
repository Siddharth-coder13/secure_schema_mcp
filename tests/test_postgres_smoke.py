import os
import uuid

import pytest
import sqlalchemy as sa

import server


POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="Set POSTGRES_TEST_DATABASE_URL to run the PostgreSQL smoke test.",
)


def test_postgres_schema_inspection_without_row_data(monkeypatch):
    schema_name = f"secure_schema_smoke_{uuid.uuid4().hex[:8]}"
    engine = sa.create_engine(POSTGRES_URL)

    with engine.begin() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema_name}"'))
        connection.execute(
            sa.text(
                f'CREATE TABLE "{schema_name}".users '
                "(id INTEGER PRIMARY KEY, email TEXT NOT NULL)"
            )
        )
        connection.execute(
            sa.text(
                f'INSERT INTO "{schema_name}".users (id, email) '
                "VALUES (1, 'postgres-smoke-secret@example.com')"
            )
        )

    try:
        monkeypatch.setenv("DATABASE_URL", POSTGRES_URL)
        monkeypatch.setenv("DATABASE_SCHEMA", schema_name)
        monkeypatch.setenv("ALLOWED_TABLES", "users")
        monkeypatch.setenv("SECURE_SCHEMA_ENV", "production")
        server.reset_engine()

        overview = server.schema_overview()
        table = server.inspect_table("users")

        assert "users" in overview
        assert "email" in table
        assert "postgres-smoke-secret@example.com" not in overview
        assert "postgres-smoke-secret@example.com" not in table
    finally:
        server.reset_engine()
        with engine.begin() as connection:
            connection.execute(sa.text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        engine.dispose()
