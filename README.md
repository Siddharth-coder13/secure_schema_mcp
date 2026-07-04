# Secure Schema MCP

<!-- mcp-name: io.github.Siddharth-coder13/secure-schema -->

A read-only MCP server that exposes **database schema metadata only** — table names, column types, keys, and foreign key relationships. It never reads row data. Tool outputs default to compact, low-token text for LLM use; pass `format="markdown"` when you want human-readable tables.

## Security guarantee

| Exposed in chat | Not exposed |
|---|---|
| Table and view names | Row values |
| Column names and types | Query results |
| Primary keys, unique constraints, FKs | Row counts or samples |

Schema metadata can still be sensitive (e.g. a column named `ssn`). Use `ALLOWED_TABLES` to restrict what is visible.

## Setup

```bash
uv sync --extra dev
uv run python tests/demo_database.py # creates test_schema.db with demo tables + seed data
uv run mcp-secure-schema # starts the MCP server
```

### Cursor MCP config

```json
{
  "mcpServers": {
    "mcp-secure-schema": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/secure_schema_mcp",
        "run",
        "mcp-secure-schema"
      ],
      "env": {
        "DATABASE_URL": "sqlite:////path/to/secure_schema_mcp/test_schema.db",
        "DATABASE_SCHEMA": "",
        "SECURE_SCHEMA_ENV": "development",
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_SHOW_SERVER_BANNER": "false"
      }
    }
  }
}
```

### Codex MCP config

Add this to `~/.codex/config.toml` or to a trusted project `.codex/config.toml`:

```toml
[mcp_servers.mcp-secure-schema]
command = "uv"
args = [
  "--directory",
  "/path/to/secure_schema_mcp",
  "run",
  "mcp-secure-schema"
]
enabled_tools = ["schema_overview", "list_tables", "inspect_table"]
startup_timeout_sec = 20
tool_timeout_sec = 30

[mcp_servers.mcp-secure-schema.env]
DATABASE_URL = "sqlite:////path/to/secure_schema_mcp/test_schema.db"
DATABASE_SCHEMA = ""
SECURE_SCHEMA_ENV = "development"
FASTMCP_CHECK_FOR_UPDATES = "off"
FASTMCP_SHOW_SERVER_BANNER = "false"
```

## Package and registry metadata

This repository includes the files needed to prepare for PyPI and MCP Registry publishing:

- `pyproject.toml` defines the `mcp-secure-schema` console script.
- `server.json` describes the server for the MCP Registry.
- The README contains the required MCP ownership marker.

The `server.json` `name` value and the README `mcp-name` ownership marker must remain identical.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | SQLAlchemy connection string (SQLite, PostgreSQL, MySQL) |
| `DATABASE_SCHEMA` | No | Default schema/catalog namespace. Useful for PostgreSQL, SQL Server, and Oracle-style schemas. Usually omit for SQLite and MySQL. Explicit tool `schema` arguments override this value. |
| `ALLOWED_TABLES` | No | Comma-separated table/view allowlist. When set, only listed names are visible. Disallowed names return a generic "not available" message (no existence leak). |
| `SECURE_SCHEMA_ENV` | No | Set to `production` (or `prod`) to fail startup unless `ALLOWED_TABLES` is configured. Defaults to `development`. |
| `FASTMCP_CHECK_FOR_UPDATES` | No | Set to `off` to disable FastMCP startup update checks. |
| `FASTMCP_SHOW_SERVER_BANNER` | No | Set to `false` to suppress the FastMCP startup banner. |

### Production deployment checklist

1. Set `SECURE_SCHEMA_ENV=production`; startup then fails closed when `ALLOWED_TABLES` is missing.
2. Set `ALLOWED_TABLES` to only the tables and views agents need (for example, `users,orders,products`).
3. Use a dedicated least-privilege database user; the MCP process holds its full connection credentials.
4. Set `DATABASE_SCHEMA` when agents should stay inside one PostgreSQL or other schema namespace (for example, `app` instead of `public`).
5. Prefer a staging or schema-replica database over a primary production database when possible.
6. Set `FASTMCP_CHECK_FOR_UPDATES=off` and `FASTMCP_SHOW_SERVER_BANNER=false` for predictable stdio startup.
7. Run the full test suite and the PostgreSQL smoke test against a disposable test database before release.

Production configuration example:

```text
DATABASE_URL=postgresql+psycopg2://schema_reader:...@db.example.com/appdb
DATABASE_SCHEMA=app
ALLOWED_TABLES=users,orders,products
SECURE_SCHEMA_ENV=production
FASTMCP_CHECK_FOR_UPDATES=off
FASTMCP_SHOW_SERVER_BANNER=false
```

Errors returned to MCP clients are sanitized; operational details are written to server stderr.

### PostgreSQL read-only role (example)

```sql
CREATE ROLE schema_reader LOGIN PASSWORD '...';
GRANT CONNECT ON DATABASE mydb TO schema_reader;
GRANT USAGE ON SCHEMA public TO schema_reader;
-- Metadata-only: no SELECT on data tables required for SQLAlchemy inspector
```

## Tools

- **`schema_overview`** — summarizes available tables, views, primary keys, and permitted FK relationships. Optional `schema` and `format` params.
- **`list_tables`** — lists tables and views (respects allowlist). Optional `format` param.
- **`inspect_table`** — column types, nullability, PKs, unique constraints, FKs. Optional `schema` and `format` params.

Schema resolution order is:

```text
explicit tool schema argument > DATABASE_SCHEMA env var > database default schema
```

### Output formats

All tools default to `format="compact"` to reduce LLM token usage:

```text
tables:order_items,orders,products,users | pk:order_items(order_id,product_id);orders(order_id);products(product_id);users(user_id) | fk:order_items.order_id->orders.order_id;order_items.product_id->products.product_id;orders.user_id->users.user_id
```

Use `format="markdown"` for human-readable output:

```text
inspect_table(table_name="users", format="markdown")
```

## Tests

```bash
uv run pytest
```

To run the opt-in PostgreSQL smoke test, provide a connection with permission to create and drop a temporary schema:

```bash
POSTGRES_TEST_DATABASE_URL='postgresql+psycopg2://...' uv run pytest tests/test_postgres_smoke.py -v
```

Security tests verify:

- Seed row data never appears in tool output
- Allowlist blocks and hides disallowed tables
- Disallowed tables don't leak existence via error messages
- Error responses don't include raw database exception text
- `server.py` contains no row-query code paths
- Compact output avoids Markdown scaffolding by default
