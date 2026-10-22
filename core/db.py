"""SQLite access.

D4 rule: the dashboard reads data ONLY through read_table() / tenant_query(),
which always filter on tenant_id. No page builds its own SQL without it.
"""
import sqlite3
from pathlib import Path

import pandas as pd

from core.config import DB_PATH, SCHEMA_PATH
from core.model import DATE_COLUMNS


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(path, check_same_thread=False)


def create_database(path: Path = DB_PATH) -> sqlite3.Connection:
    """Start from an empty database built from schema.sql."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = connect(path)
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def write_table(conn: sqlite3.Connection, table: str, df: pd.DataFrame):
    """Append rows to a table, storing dates as ISO text."""
    df = df.copy()
    for column in df.columns.intersection(list(DATE_COLUMNS)):
        df[column] = pd.to_datetime(df[column]).dt.strftime("%Y-%m-%d %H:%M:%S")
    df.to_sql(table, conn, if_exists="append", index=False)


# ---------------------------------------------------------------- tenant-safe reads

def tenant_query(sql: str, tenant_id: str, params: dict | None = None, conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """Run a SELECT that must filter on :tenant_id.

    Every table in the query needs its own "tenant_id = :tenant_id" condition;
    the check below refuses queries that forget it entirely.
    """
    if ":tenant_id" not in sql:
        raise ValueError("Refusing to run a query without a :tenant_id filter")
    if not tenant_id:
        raise ValueError("No tenant selected")
    conn = conn or connect()
    df = pd.read_sql_query(sql, conn, params={**(params or {}), "tenant_id": tenant_id})
    for column in df.columns.intersection(list(DATE_COLUMNS)):
        df[column] = pd.to_datetime(df[column])
    return df


def read_table(table: str, tenant_id: str, where: str = "", params: dict | None = None,
               conn: sqlite3.Connection | None = None) -> pd.DataFrame:
    """All rows of one table for one tenant, optionally narrowed by an extra WHERE clause."""
    sql = f"SELECT * FROM {table} WHERE tenant_id = :tenant_id"
    if where:
        sql += f" AND ({where})"
    return tenant_query(sql, tenant_id, params, conn)


# ---------------------------------------------------------------- login and audit

def find_user(username: str) -> dict | None:
    """Look up a login. The one read that cannot filter on tenant: we don't know the tenant yet."""
    conn = connect()
    row = conn.execute(
        "SELECT u.user_id, u.tenant_id, u.username, u.role, u.display_name, u.password_hash, t.name, t.archetype "
        "FROM app_user u JOIN tenant t ON t.tenant_id = u.tenant_id WHERE u.username = ?", (username,)).fetchone()
    conn.close()
    if row is None:
        return None
    keys = ["user_id", "tenant_id", "username", "role", "display_name", "password_hash", "tenant_name", "archetype"]
    return dict(zip(keys, row))


def log_event(tenant_id: str, user_id: str, action: str, detail: str = ""):
    """Append to the audit log (logins, exports)."""
    conn = connect()
    conn.execute("INSERT INTO audit_log (tenant_id, user_id, action, detail, at) VALUES (?, ?, ?, ?, datetime('now'))",
                 (tenant_id, user_id, action, detail))
    conn.commit()
    conn.close()
