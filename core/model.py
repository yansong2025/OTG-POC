"""Facts about the common data model that the Python code needs.

The column list is read straight from schema.sql, so schema.sql stays the
single source of truth: add a column there and the mapping layer accepts it.
"""
import sqlite3

from core.config import SCHEMA_PATH


def _read_schema() -> dict[str, dict[str, str]]:
    """{table: {column: SQL type}} by loading schema.sql into a throwaway database."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA_PATH.read_text())
    tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    model = {t: {col[1]: col[2] for col in conn.execute(f"PRAGMA table_info({t})")} for t in tables}
    conn.close()
    return model


MODEL = _read_schema()

# Tables a mapping file can load into, and their primary key
PRIMARY_KEYS = {
    "site": "site_id",
    "customer": "customer_id",
    "resource": "resource_id",
    "shift": "shift_id",
    "product_service": "product_id",
    "txn": "txn_id",
    "line_item": "line_id",
}

# Columns that hold IDs: these get the tenant prefix ("tidewell:J00042")
ID_COLUMNS = {"site_id", "customer_id", "resource_id", "shift_id", "product_id", "txn_id", "parent_txn_id", "line_id"}

# Columns that hold dates/times
DATE_COLUMNS = {"created_at", "completed_at", "due_date", "paid_at", "first_seen", "start_at", "end_at", "period_start", "at"}

# Foreign keys checked after mapping: (table, column, referenced table)
REFERENCES = [
    ("txn", "site_id", "site"),
    ("txn", "customer_id", "customer"),
    ("txn", "resource_id", "resource"),
    ("txn", "parent_txn_id", "txn"),
    ("line_item", "txn_id", "txn"),
    ("line_item", "product_id", "product_service"),
    ("shift", "resource_id", "resource"),
    ("shift", "site_id", "site"),
]
