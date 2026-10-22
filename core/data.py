"""One tenant's data, loaded once and passed around (KPIs, rules, models, pages)."""
from dataclasses import dataclass

import pandas as pd

from core.db import read_table

TABLES = ["txn", "line_item", "site", "customer", "resource", "shift", "product_service"]


@dataclass
class TenantData:
    tenant_id: str
    txn: pd.DataFrame
    line_item: pd.DataFrame
    site: pd.DataFrame
    customer: pd.DataFrame
    resource: pd.DataFrame
    shift: pd.DataFrame
    product_service: pd.DataFrame

    @property
    def now(self) -> pd.Timestamp:
        """'Today' for the demo: midnight after the last day that has data."""
        return self.txn["created_at"].max().normalize() + pd.Timedelta(days=1)

    @property
    def last_day(self) -> pd.Timestamp:
        return self.now - pd.Timedelta(days=1)


def load_tenant_data(tenant_id: str) -> TenantData:
    """Read every table for one tenant (always filtered by tenant_id)."""
    return TenantData(tenant_id, **{table: read_table(table, tenant_id) for table in TABLES})


def from_tables(tenant_id: str, tables: dict[str, pd.DataFrame]) -> TenantData:
    """Wrap freshly mapped tables (used by generate_data.py before they are saved)."""
    return TenantData(tenant_id, **{table: tables[table] for table in TABLES})
