import hmac
import os
from typing import Any

from dotenv import load_dotenv
from pydantic import AnyHttpUrl

from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from db import (
    describe_table as db_describe_table,
    execute_read,
    execute_write,
    list_tables as db_list_tables,
    ping_database,
)

load_dotenv()

PORT = int(os.getenv("PORT", "10000"))
HOST = os.getenv("HOST", "0.0.0.0")

MCP_BASE_URL = os.getenv("MCP_BASE_URL", f"http://127.0.0.1:{PORT}").rstrip("/")
MCP_RESOURCE_URL = f"{MCP_BASE_URL}/mcp"

# For a static bearer token, this is metadata only; the MCP server does not issue tokens.
# If you later adopt Auth0/Entra/Keycloak/etc., point this to that authorization server.
AUTH_ISSUER_URL = os.getenv("AUTH_ISSUER_URL", MCP_BASE_URL).rstrip("/") + "/"

MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")
ENABLE_WRITES = os.getenv("ENABLE_WRITES", "false").lower() == "true"

if not MCP_AUTH_TOKEN:
    raise RuntimeError("MCP_AUTH_TOKEN is required.")

if len(MCP_AUTH_TOKEN) < 32:
    raise RuntimeError("MCP_AUTH_TOKEN must be at least 32 characters long.")


class StaticTokenVerifier(TokenVerifier):
    """Verify a single bearer token stored in the environment."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token, MCP_AUTH_TOKEN):
            return None

        scopes = ["db:read"]
        if ENABLE_WRITES:
            scopes.append("db:write")

        return AccessToken(
            token=token,
            client_id="static-mcp-client",
            scopes=scopes,
            resource=MCP_RESOURCE_URL,
        )


mcp = MCPServer(
    "MySQL MCP Server",
    token_verifier=StaticTokenVerifier(),
    auth=AuthSettings(
        issuer_url=AnyHttpUrl(AUTH_ISSUER_URL),
        resource_server_url=AnyHttpUrl(MCP_RESOURCE_URL),
        required_scopes=["db:read"],
        validate_token_resource=True,
    ),
)


@mcp.tool()
def server_status() -> dict[str, Any]:
    """Check MCP server and MySQL connectivity without exposing credentials."""
    db_ok, db_message = ping_database()
    return {
        "server": "MySQL MCP Server",
        "mcp_resource_url": MCP_RESOURCE_URL,
        "database_connected": db_ok,
        "database_status": db_message,
        "writes_enabled": ENABLE_WRITES,
    }


@mcp.tool()
def list_tables() -> list[str]:
    """List tables in the configured MySQL database."""
    return db_list_tables()


@mcp.tool()
def describe_table(table_name: str) -> list[dict[str, Any]]:
    """
    Return column definitions for a MySQL table.

    Args:
        table_name: Exact table name in the configured database.
    """
    return db_describe_table(table_name)


@mcp.tool()
def query_database(
    sql: str,
    parameters: list[Any] | None = None,
) -> dict[str, Any]:
    """
    Run a read-only MySQL query.

    Allowed statements: SELECT, SHOW, DESCRIBE, DESC, EXPLAIN, and read-only WITH queries.
    Results are capped by MAX_RETURNED_ROWS.

    Use MySQL parameter placeholders (%s) and pass values in `parameters`.
    Example:
        sql = "SELECT * FROM customers WHERE customer_id = %s"
        parameters = [123]

    Args:
        sql: Read-only SQL statement.
        parameters: Optional ordered values for %s placeholders.
    """
    return execute_read(sql, parameters or [])


@mcp.tool()
def execute_database(
    sql: str,
    parameters: list[Any] | None = None,
) -> dict[str, Any]:
    """
    Execute INSERT, UPDATE, or DELETE against MySQL.

    This tool works only when ENABLE_WRITES=true.
    DDL statements such as DROP, ALTER, TRUNCATE, and CREATE are always rejected.

    Use MySQL parameter placeholders (%s) and pass values in `parameters`.

    Args:
        sql: INSERT, UPDATE, or DELETE statement.
        parameters: Optional ordered values for %s placeholders.
    """
    if not ENABLE_WRITES:
        raise PermissionError(
            "Database writes are disabled. Set ENABLE_WRITES=true in Render only if required."
        )

    return execute_write(sql, parameters or [])


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host=HOST,
        port=PORT,
        stateless_http=True,
    )
