import logging
import os
import sys
from typing import Literal

from fastmcp import FastMCP
from pydantic import Field
from sqlalchemy import create_engine, inspect
from typing_extensions import Annotated

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Secure Schema MCP",
    instructions=(
        "Expose database schema metadata only. Use schema_overview for a safe "
        "low-token database map, list_tables for inventory, and inspect_table "
        "for one entity's details. Prefer compact format unless a human-readable "
        "Markdown table is explicitly needed. Never infer or request row values, "
        "row counts, samples, or query results. Respect ALLOWED_TABLES as the "
        "visible schema boundary."
    ),
)

_engine = None


def get_allowed_tables() -> frozenset[str] | None:
    """Optional comma-separated allowlist from ALLOWED_TABLES env var."""
    raw = os.getenv("ALLOWED_TABLES", "").strip()
    if not raw:
        return None
    return frozenset(name.strip() for name in raw.split(",") if name.strip())


def get_default_schema() -> str | None:
    """Optional default schema/catalog namespace from DATABASE_SCHEMA env var."""
    raw = os.getenv("DATABASE_SCHEMA", "").strip()
    return raw or None


def get_runtime_env() -> str:
    """Deployment environment hint. Production mode enables stricter validation."""
    return os.getenv("SECURE_SCHEMA_ENV", "development").strip().lower()


def is_production_mode() -> bool:
    return get_runtime_env() in {"prod", "production"}


def resolve_schema(schema: str | None = None) -> str | None:
    """Resolve the schema while treating production configuration as a boundary."""
    configured_schema = get_default_schema()
    if is_production_mode() and configured_schema:
        return configured_schema
    if schema:
        return schema
    return configured_schema


def schema_kwargs(schema: str | None = None) -> dict[str, str]:
    resolved_schema = resolve_schema(schema)
    return {"schema": resolved_schema} if resolved_schema else {}


def validate_startup_config() -> None:
    """Fail fast on unsafe production configuration."""
    if not os.getenv("DATABASE_URL"):
        print("CRITICAL ERROR: DATABASE_URL environment variable is missing.", file=sys.stderr)
        sys.exit(1)

    if is_production_mode() and get_allowed_tables() is None:
        print(
            "CRITICAL ERROR: SECURE_SCHEMA_ENV=production requires ALLOWED_TABLES. "
            "Schema metadata can be sensitive; allowlist only the tables/views agents need.",
            file=sys.stderr,
        )
        sys.exit(1)


def get_engine():
    """Reads the database URI string from the environment."""
    global _engine
    if _engine is not None:
        return _engine

    validate_startup_config()
    database_url = os.environ["DATABASE_URL"]

    _engine = create_engine(database_url, pool_pre_ping=True)
    return _engine


def reset_engine() -> None:
    """Reset cached engine — for tests only."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def safe_error(context: str) -> str:
    """Return a generic message to the client; log full details server-side."""
    logger.exception(context)
    return f"Error: {context}. Check server logs for details."


def filter_allowed(names: list[str]) -> list[str]:
    allowed = get_allowed_tables()
    if allowed is None:
        return names
    return [name for name in names if name in allowed]


def is_table_permitted(table_name: str) -> bool:
    allowed = get_allowed_tables()
    if allowed is None:
        return True
    return table_name in allowed


def table_unavailable_message(table_name: str) -> str:
    """Same message for missing and disallowed tables when allowlist is active."""
    if get_allowed_tables() is not None:
        return f"Error: Table or view '{table_name}' is not available."
    return f"Error: Table or view '{table_name}' does not exist in this database."


OutputFormat = Annotated[
    Literal["compact", "markdown"],
    Field(description="Output format. Use compact to reduce LLM token usage; markdown for human-readable output."),
]


@mcp.tool()
def list_tables(
    schema: Annotated[
        str | None,
        Field(
            description=(
                "Optional schema/catalog namespace. Overrides DATABASE_SCHEMA only outside production."
            )
        ),
    ] = None,
    format: OutputFormat = "compact",
) -> str:
    """
    Lists all user tables and views available in the current database.
    Use this to understand what architectural entities exist.
    """
    try:
        inspector = inspect(get_engine())
        schema_kw = schema_kwargs(schema)
        tables = filter_allowed(inspector.get_table_names(**schema_kw))
        views = filter_allowed(inspector.get_view_names(**schema_kw))

        if not tables and not views:
            return "No tables or views discovered in this database target."

        if format == "compact":
            parts = []
            if tables:
                parts.append(f"tables:{','.join(tables)}")
            if views:
                parts.append(f"views:{','.join(views)}")
            return "; ".join(parts)

        output = ["### Database Architecture Inventory"]
        if tables:
            output.append("\n**Tables:**")
            output.extend(f"- {t}" for t in tables)
        if views:
            output.append("\n**Views:**")
            output.extend(f"- {v}" for v in views)

        return "\n".join(output)
    except Exception:
        return safe_error("Unable to list tables")


@mcp.tool()
def schema_overview(
    schema: Annotated[
        str | None,
        Field(
            description=(
                "Optional schema/catalog namespace. Overrides DATABASE_SCHEMA only outside production."
            )
        ),
    ] = None,
    format: OutputFormat = "compact",
) -> str:
    """
    Summarizes available tables, views, primary keys, and foreign key relationships.
    Strictly constrained to structural metadata. Does not reveal data rows.
    """
    try:
        inspector = inspect(get_engine())
        schema_kw = schema_kwargs(schema)
        tables = filter_allowed(inspector.get_table_names(**schema_kw))
        views = filter_allowed(inspector.get_view_names(**schema_kw))
        available = set(tables) | set(views)

        if not tables and not views:
            return "No tables or views discovered in this database target."

        primary_keys = []
        relationships = []
        for table in tables:
            pk_columns = inspector.get_pk_constraint(table, **schema_kw).get("constrained_columns", [])
            if pk_columns:
                primary_keys.append((table, pk_columns))

            for fk in inspector.get_foreign_keys(table, **schema_kw):
                referred_table = fk["referred_table"]
                if referred_table not in available:
                    continue
                relationships.append((table, fk["constrained_columns"], referred_table, fk["referred_columns"]))

        if format == "compact":
            parts = []
            if tables:
                parts.append(f"tables:{','.join(tables)}")
            if views:
                parts.append(f"views:{','.join(views)}")
            if primary_keys:
                pk_parts = [f"{table}({','.join(columns)})" for table, columns in primary_keys]
                parts.append(f"pk:{';'.join(pk_parts)}")
            if relationships:
                rel_parts = [
                    f"{table}.{','.join(columns)}->{referred}.{','.join(referred_columns)}"
                    for table, columns, referred, referred_columns in relationships
                ]
                parts.append(f"fk:{';'.join(rel_parts)}")
            else:
                parts.append("fk:none")
            return " | ".join(parts)

        output = ["### Schema Overview"]

        if tables:
            output.append("\n**Tables:**")
            output.extend(f"- {table}" for table in tables)

        if views:
            output.append("\n**Views:**")
            output.extend(f"- {view}" for view in views)

        if primary_keys:
            output.append("\n**Primary Keys:**")
            output.extend(f"- {table}: {', '.join(columns)}" for table, columns in primary_keys)

        output.append("\n**Relationships:**")
        if relationships:
            for table, columns, referred_table, referred_columns in relationships:
                constrained = ", ".join(columns)
                referred = ", ".join(referred_columns)
                output.append(f"- {table}.{constrained} -> {referred_table}.{referred}")
        else:
            output.append("- No permitted foreign key relationships discovered.")

        return "\n".join(output)
    except Exception:
        return safe_error("Unable to build schema overview")


@mcp.tool()
def inspect_table(
    table_name: Annotated[str, Field(description="The exact case-sensitive name of the table to inspect.")],
    schema: Annotated[
        str | None,
        Field(
            description=(
                "Optional schema/catalog namespace. Overrides DATABASE_SCHEMA only outside production."
            )
        ),
    ] = None,
    format: OutputFormat = "compact",
) -> str:
    """
    Exposes exact column names, types, nullability, primary keys, and foreign key relationships.
    Strictly constrained to structural layouts. Does not reveal data rows.
    """
    try:
        if not is_table_permitted(table_name):
            return table_unavailable_message(table_name)

        inspector = inspect(get_engine())
        schema_kw = schema_kwargs(schema)

        all_tables = inspector.get_table_names(**schema_kw) + inspector.get_view_names(**schema_kw)
        if table_name not in all_tables:
            return table_unavailable_message(table_name)

        columns = inspector.get_columns(table_name, **schema_kw)
        pk_columns = inspector.get_pk_constraint(table_name, **schema_kw).get("constrained_columns", [])
        fk_constraints = inspector.get_foreign_keys(table_name, **schema_kw)
        unique_constraints = inspector.get_unique_constraints(table_name, **schema_kw)

        unique_columns = {
            col
            for constraint in unique_constraints
            for col in constraint.get("column_names", [])
        }

        fk_by_column = {}
        for fk in fk_constraints:
            referred_table = fk["referred_table"]
            for constrained, referred in zip(fk["constrained_columns"], fk["referred_columns"], strict=False):
                fk_by_column[constrained] = f"{referred_table}.{referred}"

        if format == "compact":
            column_parts = []
            for col in columns:
                name = col["name"]
                attrs = [f"{name}:{col['type']}"]
                nullable = col.get("nullable", True)
                if name in pk_columns:
                    nullable = False
                    attrs.append("pk")
                if name in unique_columns:
                    attrs.append("uniq")
                if not nullable:
                    attrs.append("nn")
                if name in fk_by_column:
                    attrs.append(f"fk->{fk_by_column[name]}")
                column_parts.append(" ".join(attrs))
            return f"{table_name}({', '.join(column_parts)})"

        output = [f"### Schema Matrix for Entity: '{table_name}'", ""]
        output.append("| Column Name | Python/SQL Type | Nullable? | Key Attribute |")
        output.append("|---|---|---|---|")

        for col in columns:
            name = col["name"]
            col_type = str(col["type"])
            nullable = col.get("nullable", True)
            if name in pk_columns:
                nullable = False
            nullable_str = "YES" if nullable else "NO"

            key_attr = ""
            if name in pk_columns:
                key_attr = "PRIMARY KEY"
            elif name in unique_columns:
                key_attr = "UNIQUE"

            output.append(f"| {name} | {col_type} | {nullable_str} | {key_attr} |")

        if fk_constraints:
            output.append("\n### Foreign Key Associations")
            for fk in fk_constraints:
                constrained = ", ".join(fk["constrained_columns"])
                referred_table = fk["referred_table"]
                referred_columns = ", ".join(fk["referred_columns"])
                output.append(
                    f"- Column(s) `({constrained})` references `{referred_table}({referred_columns})`"
                )

        return "\n".join(output)
    except Exception:
        return safe_error(f"Unable to inspect table '{table_name}'")


def main() -> None:
    """Console script entry point."""
    validate_startup_config()
    mcp.run()


if __name__ == "__main__":
    main()
