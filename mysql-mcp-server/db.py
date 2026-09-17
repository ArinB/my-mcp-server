import os
import re
import threading
from typing import Any

import mysql.connector
from mysql.connector import pooling

_POOL = None
_POOL_LOCK = threading.Lock()

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_$]+$")
_LEADING_COMMENT_RE = re.compile(
    r"^\s*(?:(?:--[^\n]*(?:\n|$))|(?:#[^\n]*(?:\n|$))|(?:/\*.*?\*/\s*))*",
    re.DOTALL,
)

READ_PREFIXES = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}
WRITE_PREFIXES = {"INSERT", "UPDATE", "DELETE"}
DISALLOWED_ANYWHERE = {
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "RENAME",
    "GRANT",
    "REVOKE",
    "CALL",
    "LOAD",
    "HANDLER",
}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def _connection_config() -> dict[str, Any]:
    required = {
        "MYSQL_HOST": os.getenv("MYSQL_HOST"),
        "MYSQL_USER": os.getenv("MYSQL_USER"),
        "MYSQL_PASSWORD": os.getenv("MYSQL_PASSWORD"),
        "MYSQL_DATABASE": os.getenv("MYSQL_DATABASE"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "Missing required MySQL environment variables: " + ", ".join(missing)
        )

    config: dict[str, Any] = {
        "host": required["MYSQL_HOST"],
        "port": _env_int("MYSQL_PORT", 3306),
        "user": required["MYSQL_USER"],
        "password": required["MYSQL_PASSWORD"],
        "database": required["MYSQL_DATABASE"],
        "connection_timeout": _env_int("MYSQL_CONNECT_TIMEOUT", 10),
        "autocommit": False,
        "charset": "utf8mb4",
        "use_unicode": True,
    }

    # Keep TLS on by default. Set MYSQL_SSL_DISABLED=true only when your MySQL
    # endpoint explicitly requires a non-TLS connection (usually local/private).
    config["ssl_disabled"] = os.getenv("MYSQL_SSL_DISABLED", "false").lower() == "true"

    ssl_ca = os.getenv("MYSQL_SSL_CA")
    if ssl_ca:
        config["ssl_ca"] = ssl_ca

    return config


def get_pool() -> pooling.MySQLConnectionPool:
    global _POOL
    if _POOL is None:
        with _POOL_LOCK:
            if _POOL is None:
                _POOL = pooling.MySQLConnectionPool(
                    pool_name="mcp_mysql_pool",
                    pool_size=_env_int("MYSQL_POOL_SIZE", 5),
                    pool_reset_session=True,
                    **_connection_config(),
                )
    return _POOL


def get_connection():
    return get_pool().get_connection()


def _strip_leading_comments(sql: str) -> str:
    return _LEADING_COMMENT_RE.sub("", sql, count=1).strip()


def _first_keyword(sql: str) -> str:
    cleaned = _strip_leading_comments(sql)
    if not cleaned:
        raise ValueError("SQL statement cannot be empty.")
    return cleaned.split(None, 1)[0].upper()


def _reject_multiple_statements(sql: str) -> None:
    # A trailing semicolon is fine. Any other semicolon indicates multiple statements.
    normalized = sql.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1]
    if ";" in normalized:
        raise ValueError("Multiple SQL statements are not allowed.")


def _tokenize(sql: str) -> set[str]:
    # Conservative keyword scan used only as an additional safety guard.
    return {token.upper() for token in re.findall(r"\b[A-Za-z_]+\b", sql)}


def _validate_read_sql(sql: str) -> None:
    _reject_multiple_statements(sql)
    first = _first_keyword(sql)

    if first not in READ_PREFIXES:
        raise PermissionError(
            f"Read tool rejected statement beginning with {first!r}."
        )

    tokens = _tokenize(sql)
    dangerous = tokens.intersection(DISALLOWED_ANYWHERE)
    if dangerous:
        raise PermissionError(
            "SQL contains a disallowed keyword: " + ", ".join(sorted(dangerous))
        )

    # WITH can prefix data-changing statements in MySQL. Reject common write words.
    if first == "WITH" and tokens.intersection(WRITE_PREFIXES):
        raise PermissionError("WITH queries must be read-only.")


def _validate_write_sql(sql: str) -> None:
    _reject_multiple_statements(sql)
    first = _first_keyword(sql)

    if first not in WRITE_PREFIXES:
        raise PermissionError(
            "Write tool accepts only INSERT, UPDATE, or DELETE statements."
        )

    tokens = _tokenize(sql)
    dangerous = tokens.intersection(DISALLOWED_ANYWHERE)
    if dangerous:
        raise PermissionError(
            "SQL contains a disallowed keyword: " + ", ".join(sorted(dangerous))
        )


def _json_safe(value: Any) -> Any:
    # MCP output must be JSON serializable. Convert common MySQL-specific objects.
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, bytes):
        return value.hex()

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    return str(value)


def _json_safe_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_safe(value) for key, value in row.items()}


def ping_database() -> tuple[bool, str]:
    try:
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            return True, "connected"
        finally:
            conn.close()
    except Exception as exc:
        # Deliberately avoid returning credentials or full connector internals.
        return False, f"{type(exc).__name__}: database connection failed"


def list_tables() -> list[str]:
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        rows = cursor.fetchall()
        cursor.close()
        return [str(row[0]) for row in rows]
    finally:
        conn.close()


def describe_table(table_name: str) -> list[dict[str, Any]]:
    if not _IDENTIFIER_RE.fullmatch(table_name):
        raise ValueError("Invalid table name.")

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(f"DESCRIBE `{table_name}`")
        rows = cursor.fetchall()
        cursor.close()
        return [_json_safe_row(row) for row in rows]
    finally:
        conn.close()


def execute_read(sql: str, parameters: list[Any]) -> dict[str, Any]:
    _validate_read_sql(sql)

    max_rows = _env_int("MAX_RETURNED_ROWS", 500)

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, tuple(parameters))

        rows = cursor.fetchmany(max_rows + 1)
        truncated = len(rows) > max_rows
        rows = rows[:max_rows]

        columns = list(cursor.column_names or [])
        cursor.close()

        return {
            "columns": columns,
            "rows": [_json_safe_row(row) for row in rows],
            "row_count_returned": len(rows),
            "truncated": truncated,
            "max_rows": max_rows,
        }
    finally:
        conn.close()


def execute_write(sql: str, parameters: list[Any]) -> dict[str, Any]:
    _validate_write_sql(sql)

    conn = get_connection()
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, tuple(parameters))
            affected = cursor.rowcount
            lastrowid = cursor.lastrowid
            conn.commit()
            return {
                "success": True,
                "affected_rows": affected,
                "last_insert_id": lastrowid,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
    finally:
        conn.close()
