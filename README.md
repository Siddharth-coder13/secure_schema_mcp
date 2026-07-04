# Secure Schema MCP

<!-- mcp-name: io.github.Siddharth-coder13/secure-schema -->

A read-only MCP server that gives AI coding tools database structure without exposing row data. It returns table and view names, columns, types, keys, and relationships in a compact format designed to reduce LLM token usage.

## What it exposes

| Exposed | Not exposed |
|---|---|
| Table and view names | Row values or query results |
| Column names and SQL types | Row counts or samples |
| Primary and unique keys | Database credentials |
| Foreign-key relationships | Write or query tools |

Schema metadata can still be sensitive. A column name such as `ssn` reveals information even without values, so production deployments should always use the table allowlist and a dedicated database account.

## Requirements

- An MCP-compatible client such as Cursor or Codex
- A reachable SQLite, PostgreSQL, or MySQL database
- Python 3.12 or newer when installing without `uvx`

SQLite support uses Python's built-in driver. PostgreSQL and MySQL drivers are included. Other SQLAlchemy dialects are not tested or bundled in v1.

## Configure your IDE

The recommended setup uses [`uvx`](https://docs.astral.sh/uv/guides/tools/) to download and run the published Python package in an isolated environment. You do not need to clone this repository or start the server separately. Your IDE launches it over stdio when needed.

### Cursor

Add this server to your Cursor MCP configuration:

```json
{
  "mcpServers": {
    "secure-schema": {
      "command": "uvx",
      "args": ["mcp-secure-schema"],
      "env": {
        "DATABASE_URL": "postgresql+psycopg2://schema_reader:password@localhost:5432/appdb",
        "DATABASE_SCHEMA": "public",
        "ALLOWED_TABLES": "users,orders,products",
        "SECURE_SCHEMA_ENV": "production",
        "FASTMCP_CHECK_FOR_UPDATES": "off",
        "FASTMCP_SHOW_SERVER_BANNER": "false"
      }
    }
  }
}
```

Restart or reload Cursor after changing its MCP configuration.

### Codex

Add this to `~/.codex/config.toml` or a trusted project's `.codex/config.toml`:

```toml
[mcp_servers.secure-schema]
command = "uvx"
args = ["mcp-secure-schema"]
enabled_tools = ["schema_overview", "list_tables", "inspect_table"]
startup_timeout_sec = 30
tool_timeout_sec = 30

[mcp_servers.secure-schema.env]
DATABASE_URL = "postgresql+psycopg2://schema_reader:password@localhost:5432/appdb"
DATABASE_SCHEMA = "public"
ALLOWED_TABLES = "users,orders,products"
SECURE_SCHEMA_ENV = "production"
FASTMCP_CHECK_FOR_UPDATES = "off"
FASTMCP_SHOW_SERVER_BANNER = "false"
```

### Install once instead

If you prefer a persistent installation:

```bash
pipx install mcp-secure-schema
```

Then use `"command": "mcp-secure-schema"` with an empty `args` list in the IDE configuration.

## Database URLs

Secure Schema MCP accepts SQLAlchemy connection URLs:

```text
# SQLite (absolute path)
sqlite:////Users/me/project/app.db

# PostgreSQL
postgresql+psycopg2://user:password@localhost:5432/appdb

# Remote PostgreSQL with certificate verification
postgresql+psycopg2://user:password@db.example.com:5432/appdb?sslmode=verify-full&sslrootcert=/path/to/ca.pem

# MySQL
mysql+pymysql://user:password@localhost:3306/appdb
```

Percent-encode special characters in URL usernames and passwords. For example, `@` in a password becomes `%40`.

Local and remote databases use the same MCP configuration. For remote databases, the machine running the IDE must also have working DNS, network access, firewall permission, and valid TLS settings.

## Configuration

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | SQLAlchemy connection URL. Treated as a secret by the registry manifest. |
| `DATABASE_SCHEMA` | No | Default schema or catalog namespace. Recommended for PostgreSQL. Locked against tool overrides in production. |
| `ALLOWED_TABLES` | Production | Comma-separated, case-sensitive table and view allowlist. Production mode refuses to start without it. |
| `SECURE_SCHEMA_ENV` | No | Set to `production` or `prod` for strict startup validation. Defaults to `development`. |
| `FASTMCP_CHECK_FOR_UPDATES` | No | Set to `off` for predictable stdio startup. |
| `FASTMCP_SHOW_SERVER_BANNER` | No | Set to `false` to suppress the startup banner. |

### Multiple schemas

`DATABASE_SCHEMA` selects the default namespace. Resolution works as follows:

- In production, a configured `DATABASE_SCHEMA` is a security boundary and tool arguments cannot override it.
- Outside production, an explicit tool `schema` argument overrides `DATABASE_SCHEMA`.
- Without either value, the database driver's default schema is used.

For strict production access to multiple schemas, run one MCP server entry per schema with its own `DATABASE_SCHEMA` and `ALLOWED_TABLES` values. The table allowlist contains unqualified names, not `schema.table` values.

## Tools

- `schema_overview`: compact map of permitted tables, views, primary keys, and foreign-key relationships
- `list_tables`: permitted table and view inventory
- `inspect_table`: columns, SQL types, nullability, primary keys, unique constraints, and foreign keys for one entity

Every tool defaults to `format="compact"` for lower token usage:

```text
tables:orders,users | pk:orders(order_id);users(user_id) | fk:orders.user_id->users.user_id
```

Pass `format="markdown"` when a human-readable table is more useful.

## Security notes

- The server exposes only SQLAlchemy inspection operations; it provides no row-query or write tool.
- Missing and disallowed table names return the same message when an allowlist is active, avoiding an existence leak.
- Client-facing errors are sanitized. Operational details are written to server stderr.
- The IDE launches the MCP process and supplies its environment, so treat the IDE and its configuration as trusted.
- Do not commit configurations containing credentials. For stronger isolation, launch through a wrapper that obtains `DATABASE_URL` from an OS keychain or secret manager.
- Use a dedicated least-privilege database account and TLS certificate verification for remote connections.

Example PostgreSQL role:

```sql
CREATE ROLE schema_reader LOGIN PASSWORD 'use-a-secret-manager';
GRANT CONNECT ON DATABASE appdb TO schema_reader;
GRANT USAGE ON SCHEMA public TO schema_reader;
```

Metadata visibility varies by PostgreSQL provider and database policy. Grant only the additional catalog or object privileges required for inspection; avoid granting row `SELECT` unless your environment requires it.

## Troubleshooting

**The server exits immediately**

Check the IDE's MCP logs. `DATABASE_URL` is mandatory, and production mode also requires a non-empty `ALLOWED_TABLES` value.

**No tables or views are discovered**

Confirm `DATABASE_SCHEMA`, exact table-name casing, database permissions, and whether the allowlist contains the expected names.

**The connection URL fails with a valid password**

Percent-encode reserved URL characters or use a secret-injection wrapper. Do not paste real credentials into issues or logs.

**`uvx` is not found**

Install `uv` using its official instructions, or install the package with `pipx` and use `mcp-secure-schema` as the command.

**Starting the command appears to hang**

That is normal for a stdio MCP server. It waits for an MCP client on standard input and is normally started by the IDE.

## Development

Clone the repository only when developing or testing the server:

```bash
git clone https://github.com/Siddharth-coder13/secure_schema_mcp.git
cd secure_schema_mcp
uv sync --extra dev
uv run python tests/demo_database.py
DATABASE_URL="sqlite:///$PWD/test_schema.db" uv run mcp-secure-schema
```

Run the test suite:

```bash
uv run pytest
```

Run the opt-in PostgreSQL integration test against a disposable database. The test creates and removes a randomly named schema:

```bash
POSTGRES_TEST_DATABASE_URL='postgresql+psycopg2://user@localhost:5432/testdb' \
  uv run pytest tests/test_postgres_smoke.py -v
```

The tests verify row-data isolation, allowlist behavior, sanitized errors, compact output, relationships, schema selection, and the locked production namespace.

## Release checklist

Maintainers should update the matching versions in `pyproject.toml` and `server.json`, run the complete SQLite and PostgreSQL suites, build with `uv build --no-sources`, verify installation from the wheel, publish to PyPI, and only then publish `server.json` to the MCP Registry.

## License

Licensed under the Apache License 2.0. See `LICENSE` and `NOTICE`.
