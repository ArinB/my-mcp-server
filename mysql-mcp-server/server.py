import hmac
import os
from typing import Any

import uvicorn
from dotenv import load_dotenv
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server import MCPServer

from db import (
    describe_table as db_describe_table,
    execute_read,
    execute_write,
    list_tables as db_list_tables,
    ping_database,
)

load_dotenv()

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10000"))

MCP_BASE_URL = os.getenv(
    "MCP_BASE_URL",
    f"http://127.0.0.1:{PORT}",
).rstrip("/")

MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "")
ENABLE_WRITES = os.getenv("ENABLE_WRITES", "false").lower() == "true"

if not MCP_AUTH_TOKEN:
    raise RuntimeError("MCP_AUTH_TOKEN is required.")

if len(MCP_AUTH_TOKEN) < 32:
    raise RuntimeError("MCP_AUTH_TOKEN must be at least 32 characters long.")


mcp = MCPServer("MySQL MCP Server")


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """
    Protect the /mcp endpoint with a fixed Bearer token.

    Expected request header:
        Authorization: Bearer <MCP_AUTH_TOKEN>

    This intentionally does NOT publish OAuth protected-resource metadata,
    so clients are not directed into an OAuth sign-in flow.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path.startswith("/mcp"):
            auth_header = request.headers.get("Authorization", "")

            if not auth_header.startswith("Bearer "):
                return JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )

            supplied_token = auth_header[7:].strip()

            if not supplied_token or not hmac.compare_digest(
                supplied_token,
                MCP_AUTH_TOKEN,
            ):
                return JSONResponse(
                    {"error": "Unauthorized"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )

        return await call_next(request)


@mcp.tool()
def server_status() -> dict[str, Any]:
    """Check MCP server and MySQL connectivity without exposing credentials."""
    db_ok, db_message = ping_database()

    return {
        "server": "MySQL MCP Server",
        "mcp_resource_url": f"{MCP_BASE_URL}/mcp",
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

    Allowed statements are enforced by db.py.

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
    DDL statements such as DROP, ALTER, TRUNCATE, and CREATE
    are rejected by db.py.

    Args:
        sql: INSERT, UPDATE, or DELETE statement.
        parameters: Optional ordered values for %s placeholders.
    """
    if not ENABLE_WRITES:
        raise PermissionError(
            "Database writes are disabled. "
            "Set ENABLE_WRITES=true in Render only if required."
        )

    return execute_write(sql, parameters or [])


app = mcp.streamable_http_app()
app.add_middleware(BearerTokenMiddleware)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
    )
