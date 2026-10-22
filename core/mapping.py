"""D2 mapping layer: a client's raw files -> the common data model.

Nothing in this file knows about any industry. All industry knowledge is in
config/archetypes/<archetype>/mapping.yaml (see MAPPING_GUIDE.md).

    raw CSVs --(map_source: rename, clean, type)--> common tables
             --(post-processing: locate, fill, derive, check)--> ready for the DB
"""
from pathlib import Path

import pandas as pd

from core import cleaning
from core.cleaning import QualityLog
from core.config import load_mapping, load_planning_areas
from core.geo import locate
from core.model import DATE_COLUMNS, ID_COLUMNS, MODEL, PRIMARY_KEYS, REFERENCES


def map_tenant(tenant_id: str, archetype: str, raw_dir: Path) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Map every raw file of one tenant. Returns ({table: DataFrame}, data-quality log)."""
    mapping = load_mapping(archetype)
    log = QualityLog(tenant_id)

    # 1. Map each source file on its own
    parts: dict[str, list[pd.DataFrame]] = {}
    for spec in mapping["tables"]:
        parts.setdefault(spec["target"], []).append(map_source(spec, raw_dir, tenant_id, log))

    # 2. Stack files that load into the same table (e.g. jobs + invoices + payments -> txn)
    tables = {}
    for table in PRIMARY_KEYS:
        frames = parts.get(table, [])
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        tables[table] = conform(df, table)
    tables["txn"] = cleaning.drop_duplicate_ids(tables["txn"], "txn_id", log, "all transaction files")

    # 3. Generic post-processing, then the archetype's "derive" rules
    post_process(tables, log)
    derive(tables, mapping.get("derive", {}), log)
    check_references(tables, log)
    return tables, log.to_frame()


def map_source(spec: dict, raw_dir: Path, tenant_id: str, log: QualityLog) -> pd.DataFrame:
    """Turn one raw file into rows of one common-model table, following its mapping spec."""
    source, target = spec["source"], spec["target"]
    raw = pd.read_csv(raw_dir / source, dtype=str, keep_default_na=False)  # read everything as text first
    raw = cleaning.strip_text(raw)
    raw = cleaning.drop_exact_duplicates(raw, log, source)

    # Rename: common column <- raw column (or several raw columns joined together)
    out = pd.DataFrame(index=raw.index)
    separator = spec.get("join_with", " ")
    for column, raw_column in spec["columns"].items():
        if isinstance(raw_column, list):
            joined = raw[raw_column[0]].astype("string")
            for part in raw_column[1:]:
                joined = joined + separator + raw[part].astype("string")
            out[column] = joined
        else:
            out[column] = raw[raw_column]

    for column, value in spec.get("constants", {}).items():
        out[column] = value

    # Standardise codes such as status ("COMPLETED", "Done" -> "completed")
    for column, value_map in spec.get("values", {}).items():
        out[column] = cleaning.normalise_values(out[column], value_map, log, source, column)

    # Tidy capitalisation of free text, e.g. "GOLDEN TRADING pte ltd" -> "Golden Trading Pte Ltd"
    for column, style in spec.get("text_case", {}).items():
        fixed = getattr(out[column].str, style)()      # str.title() / str.upper() / str.lower()
        log.add(source, f"inconsistent casing in {column}", (out[column] != fixed).sum(), f"converted to {style} case")
        out[column] = fixed

    for column, value in spec.get("defaults", {}).items():
        out[column] = out[column].fillna(value)

    # Types: dates and numbers, based on the column names/types in schema.sql
    date_formats = spec.get("date_formats", {})
    for column in out.columns:
        if column in DATE_COLUMNS:
            out[column] = cleaning.to_datetime(out[column], date_formats.get(column), log, source, column)
        elif MODEL[target].get(column) in ("REAL", "INTEGER"):
            out[column] = cleaning.to_number(out[column], log, source, column)

    # Prefix every ID with the tenant so two clients' records can never collide
    for column in out.columns.intersection(list(ID_COLUMNS)):
        out[column] = tenant_id + ":" + out[column].astype("string")

    key = PRIMARY_KEYS[target]
    out = cleaning.drop_missing(out, key, log, source)
    out = cleaning.drop_duplicate_ids(out, key, log, source)
    out["tenant_id"] = tenant_id
    return out


def conform(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Give a DataFrame exactly the columns of the model table (missing ones become empty)."""
    columns = list(MODEL[table])
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    return df[columns].reset_index(drop=True)


def post_process(tables: dict[str, pd.DataFrame], log: QualityLog):
    """Generic fixes that apply to every archetype."""
    areas = load_planning_areas()

    # Sites: postal code -> planning area -> lat/lon
    sites = locate(tables["site"], areas)
    log.add("site", "postal code missing or not in a known planning area",
            sites["planning_area"].isna().sum(), "kept, but left off the maps")
    tables["site"] = sites

    # Resources: 'TAMPINES ' -> 'Tampines'
    res = tables["resource"]
    if res["home_area"].notna().any():
        res["home_area"] = cleaning.match_names(res["home_area"], areas["planning_area"].tolist(), log, "resource", "home_area")

    # Line items: take price/cost from the product list when the source leaves them out
    lines, products = tables["line_item"], tables["product_service"].set_index("product_id")
    if len(lines):
        lines["unit_price"] = lines["unit_price"].fillna(lines["product_id"].map(products["unit_price"]))
        lines["unit_cost"] = lines["unit_cost"].fillna(lines["product_id"].map(products["unit_cost"]))
        lines["discount_pct"] = lines["discount_pct"].fillna(0)
        lines["line_amount"] = (lines["qty"] * lines["unit_price"] * (1 - lines["discount_pct"] / 100)).round(2)

    # Transactions: a missing total can be rebuilt from its line items
    txn = tables["txn"]
    line_totals = lines.groupby("txn_id")["line_amount"].sum() if len(lines) else pd.Series(dtype=float)
    fixable = txn["amount"].isna() & txn["txn_id"].isin(line_totals.index)
    if fixable.any():
        txn.loc[fixable, "amount"] = txn.loc[fixable, "txn_id"].map(line_totals)
    log.add("txn", "missing amount", fixable.sum(), "rebuilt from line items")
    txn["is_repeat"] = 0


def derive(tables: dict[str, pd.DataFrame], rules: dict, log: QualityLog):
    """Optional, config-driven derived fields (the 'derive' section of mapping.yaml)."""
    txn = tables["txn"]

    # Copy e.g. site_id/customer_id down a document chain (job -> invoice -> payment)
    columns = rules.get("inherit_from_parent", [])
    for _ in range(4):  # chains are at most 5 documents long
        parent = txn.set_index("txn_id")
        for column in columns:
            missing = txn[column].isna() & txn["parent_txn_id"].notna()
            txn.loc[missing, column] = txn.loc[missing, "parent_txn_id"].map(parent[column])

    # An invoice's paid_at = date of its (latest) payment
    if "paid_at_from_child" in rules:
        r = rules["paid_at_from_child"]
        paid = txn[txn["type"] == r["child_type"]].groupby("parent_txn_id")["created_at"].max()
        is_parent = txn["type"] == r["parent_type"]
        txn.loc[is_parent, "paid_at"] = txn.loc[is_parent, "txn_id"].map(paid)

    # Repeat jobs: same key (e.g. site + job type) again within N days
    if "repeat" in rules:
        r = rules["repeat"]
        jobs = txn[(txn["type"] == r["type"]) & (txn["status"] != "cancelled")]
        if "categories" in r:   # e.g. only call-backs for repairs count, not routine servicing
            jobs = jobs[jobs["category"].isin(r["categories"])]
        jobs = jobs.sort_values("created_at")
        previous = jobs.groupby(r["key"])["created_at"].shift()
        repeat = (jobs["created_at"] - previous).dt.days <= r["window_days"]
        txn.loc[jobs.index, "is_repeat"] = repeat.astype(int)


def check_references(tables: dict[str, pd.DataFrame], log: QualityLog):
    """Log links that point at records we don't have. Orphan line items are dropped."""
    for table, column, ref_table in REFERENCES:
        df, ref_key = tables[table], PRIMARY_KEYS[ref_table]
        broken = df[column].notna() & ~df[column].isin(tables[ref_table][ref_key])
        if table == "line_item" and column == "txn_id":
            log.add(table, f"{column} not found in {ref_table}", broken.sum(), "row removed")
            tables[table] = df[~broken]
        else:
            log.add(table, f"{column} not found in {ref_table}", broken.sum(), "kept, link left as is")
