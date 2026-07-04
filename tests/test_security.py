import os
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa

import server
from demo_database import build_demo_database

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_PATH = PROJECT_ROOT / "test_security.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"

SENSITIVE_MARKERS = [
    "john@secretcompany.com",
    "jane@leakproof.io",
    "john_doe",
    "jane_smith",
    "Secure Core Terminal",
    "SEC-001",
]


@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", TEST_DB_URL)
    monkeypatch.delenv("ALLOWED_TABLES", raising=False)
    server.reset_engine()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()
    build_demo_database(db_path=TEST_DB_URL)
    yield
    server.reset_engine()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.fixture
def allowlist_users_orders(monkeypatch):
    monkeypatch.setenv("ALLOWED_TABLES", "users,orders")


def test_production_mode_requires_allowed_tables(monkeypatch, capsys):
    monkeypatch.setenv("SECURE_SCHEMA_ENV", "production")
    monkeypatch.delenv("ALLOWED_TABLES", raising=False)

    with pytest.raises(SystemExit) as exc:
        server.validate_startup_config()

    assert exc.value.code == 1
    assert "requires ALLOWED_TABLES" in capsys.readouterr().err


def test_production_mode_accepts_allowed_tables(allowlist_users_orders, monkeypatch):
    monkeypatch.setenv("SECURE_SCHEMA_ENV", "production")

    server.validate_startup_config()


def test_startup_validation_requires_database_url(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(SystemExit) as exc:
        server.validate_startup_config()

    assert exc.value.code == 1
    assert "DATABASE_URL" in capsys.readouterr().err


def test_seed_data_not_exposed_by_list_tables():
    result = server.list_tables()
    for marker in SENSITIVE_MARKERS:
        assert marker not in result


def test_seed_data_not_exposed_by_inspect_table():
    for table in ("users", "products", "orders", "order_items"):
        result = server.inspect_table(table)
        for marker in SENSITIVE_MARKERS:
            assert marker not in result


def test_seed_data_not_exposed_by_schema_overview():
    result = server.schema_overview()
    for marker in SENSITIVE_MARKERS:
        assert marker not in result


def test_allowlist_limits_list_tables(allowlist_users_orders):
    result = server.list_tables()
    assert "users" in result
    assert "orders" in result
    assert "products" not in result
    assert "order_items" not in result


def test_allowlist_limits_schema_overview(allowlist_users_orders):
    result = server.schema_overview()
    assert "users" in result
    assert "orders" in result
    assert "products" not in result
    assert "order_items" not in result
    assert "orders.user_id->users.user_id" in result
    assert "order_items.product_id" not in result


def test_allowlist_blocks_inspect_of_disallowed_table(allowlist_users_orders):
    result = server.inspect_table("products")
    assert "not available" in result
    assert "does not exist" not in result


def test_allowlist_does_not_confirm_disallowed_table_exists(allowlist_users_orders):
    """Disallowed and missing tables both return 'not available' — no existence leak."""
    blocked = server.inspect_table("products")
    missing = server.inspect_table("definitely_missing_table")
    assert "not available" in blocked
    assert "not available" in missing
    assert "does not exist" not in blocked
    assert "does not exist" not in missing


def test_allowlist_permits_inspect_of_allowed_table(allowlist_users_orders):
    result = server.inspect_table("users")
    assert "username" in result
    assert "email" in result


def test_error_messages_are_sanitized(monkeypatch):
    def broken_engine():
        raise sa.exc.OperationalError("connection failed", {}, Exception("password=supersecret"))

    with patch.object(server, "get_engine", side_effect=broken_engine):
        result = server.list_tables()

    assert "supersecret" not in result
    assert "connection failed" not in result
    assert "Check server logs for details" in result


def test_schema_overview_error_messages_are_sanitized(monkeypatch):
    def broken_engine():
        raise sa.exc.OperationalError("connection failed", {}, Exception("password=supersecret"))

    with patch.object(server, "get_engine", side_effect=broken_engine):
        result = server.schema_overview()

    assert "supersecret" not in result
    assert "connection failed" not in result
    assert "Check server logs for details" in result


def test_server_has_no_row_query_paths():
    source = (PROJECT_ROOT / "server.py").read_text()
    forbidden = (".execute(", "sa.text(", "SELECT ", "select(")
    for pattern in forbidden:
        assert pattern not in source


def test_unique_constraints_are_reflected():
    result = server.inspect_table("users")
    assert "username:TEXT uniq nn" in result
    assert "email:TEXT uniq nn" in result


def test_markdown_output_remains_available():
    result = server.inspect_table("users", format="markdown")
    assert "| Column Name | Python/SQL Type | Nullable? | Key Attribute |" in result
    assert "UNIQUE" in result


def test_schema_overview_reflects_relationships():
    result = server.schema_overview()
    assert "orders.user_id->users.user_id" in result
    assert "order_items.order_id->orders.order_id" in result
    assert "order_items.product_id->products.product_id" in result


def test_compact_outputs_avoid_markdown_scaffolding():
    assert "###" not in server.list_tables()
    assert "**" not in server.schema_overview()
    assert "| Column Name |" not in server.inspect_table("users")


def test_database_schema_env_is_used_by_default(monkeypatch):
    observed_schemas = []

    class FakeInspector:
        def get_table_names(self, **kwargs):
            observed_schemas.append(kwargs.get("schema"))
            return []

        def get_view_names(self, **kwargs):
            observed_schemas.append(kwargs.get("schema"))
            return []

    monkeypatch.setenv("DATABASE_SCHEMA", "app")

    with patch.object(server, "inspect", return_value=FakeInspector()):
        result = server.list_tables()

    assert "No tables or views" in result
    assert observed_schemas == ["app", "app"]


def test_explicit_schema_overrides_database_schema_env(monkeypatch):
    observed_schemas = []

    class FakeInspector:
        def get_table_names(self, **kwargs):
            observed_schemas.append(kwargs.get("schema"))
            return []

        def get_view_names(self, **kwargs):
            observed_schemas.append(kwargs.get("schema"))
            return []

    monkeypatch.setenv("DATABASE_SCHEMA", "app")

    with patch.object(server, "inspect", return_value=FakeInspector()):
        result = server.list_tables(schema="billing")

    assert "No tables or views" in result
    assert observed_schemas == ["billing", "billing"]
