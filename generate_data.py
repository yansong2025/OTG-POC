"""Build the demo database from scratch.

    python generate_data.py            # fake raw data + mapping + database
    python generate_data.py --skip-raw # re-map the raw CSVs already in data/raw/

For each tenant in config/tenants.yaml:
  1. a fake client system (sample_sources/) writes 12 months of raw CSVs,
     in that client's own column names and formats, to data/raw/<tenant_id>/
  2. the mapping layer (core/mapping.py + the archetype's mapping.yaml)
     cleans them and maps them into the common data model
  3. the result is written to SQLite (data/otg.db)
  4. KPI definitions are loaded from kpis.yaml and KPI values pre-computed
     for every week and month (kpi_snapshot), for fast trend charts
"""
import argparse
import importlib
import json
import time
import zlib

import numpy as np
import pandas as pd

from core.auth import hash_password
from core.config import DB_PATH, RAW_DIR, load_kpi_config, load_planning_areas, load_tenants
from core.data import from_tables
from core.db import create_database, write_table
from core.kpis import compute_snapshots
from core.mapping import map_tenant

DEMO_PASSWORD = "demo"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-raw", action="store_true", help="don't regenerate raw CSVs, just re-map them")
    args = parser.parse_args()

    conn = create_database()
    write_table(conn, "planning_area", load_planning_areas())

    for tenant in load_tenants():
        tenant_id, archetype = tenant["tenant_id"], tenant["archetype"]
        raw_dir = RAW_DIR / tenant_id
        started = time.time()
        print(f"\n== {tenant['name']} ({archetype})")

        # 1. Fake client export (a real client would supply these files instead)
        if tenant.get("sample_source") and not args.skip_raw:
            source = importlib.import_module(f"sample_sources.{tenant['sample_source']}")
            source.generate(raw_dir, np.random.default_rng(zlib.crc32(tenant_id.encode())))
            print(f"   raw files written to {raw_dir.relative_to(RAW_DIR.parent.parent)}")

        # 2. Clean and map into the common model
        tables, quality_log = map_tenant(tenant_id, archetype, raw_dir)

        # 3. Save
        write_table(conn, "tenant", pd.DataFrame([{"tenant_id": tenant_id, "name": tenant["name"], "archetype": archetype}]))
        write_table(conn, "app_user", pd.DataFrame([{
            "user_id": f"{tenant_id}:{u['username']}", "tenant_id": tenant_id, "username": u["username"],
            "role": u["role"], "display_name": u["display_name"], "password_hash": hash_password(DEMO_PASSWORD),
        } for u in tenant["users"]]))
        for table, df in tables.items():
            write_table(conn, table, df)
        write_table(conn, "data_quality_log", quality_log)

        # 4. KPI definitions (from kpis.yaml) and their weekly/monthly values
        kpis = load_kpi_config(archetype).get("kpis", [])
        write_table(conn, "kpi_definition", pd.DataFrame([{
            "tenant_id": tenant_id, "kpi_id": k["id"], "archetype": archetype, "name": k["name"],
            "formula": json.dumps({key: v for key, v in k.items() if key not in ("id", "name", "unit", "direction", "target", "amber_pct")}),
            "unit": k["unit"], "direction": k["direction"], "target": k["target"], "amber_pct": k.get("amber_pct", 5),
        } for k in kpis], columns=["tenant_id", "kpi_id", "archetype", "name", "formula", "unit", "direction", "target", "amber_pct"]))
        if kpis:
            write_table(conn, "kpi_snapshot", compute_snapshots(from_tables(tenant_id, tables), kpis))

        counts = ", ".join(f"{t} {len(df):,}" for t, df in tables.items() if len(df))
        print(f"   mapped: {counts}")
        print(f"   cleaning fixed {quality_log['rows_affected'].sum():,} rows across {len(quality_log)} issues"
              f" ({time.time() - started:.0f}s)")

    conn.commit()
    conn.close()
    print(f"\nDatabase ready: {DB_PATH}")


if __name__ == "__main__":
    main()
