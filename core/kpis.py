"""KPI engine: evaluates the KPI definitions in config/archetypes/<archetype>/kpis.yaml.

A KPI definition picks a *calculator* (calc) and gives it parameters. The
calculators below are generic: "count", "sum", "share" etc. work for orders,
jobs and quotations alike. Adding a KPI for a new industry is usually just
config; a genuinely new kind of calculation is one new function here.
"""
import pandas as pd

from core.data import TenantData

# Calculators whose value grows with the length of the period (so a weekly
# target is the monthly target scaled down). Rates and balances are not scaled.
ADDITIVE = {"count", "sum", "missing_child", "per_resource"}


# ---------------------------------------------------------------- calculators
# Each one gets: rows = the KPI's transactions (type + "where" already applied),
# the KPI definition, all tenant data, and the period [start, end).

def in_period(rows: pd.DataFrame, start, end, column: str = "created_at") -> pd.DataFrame:
    return rows[(rows[column] >= start) & (rows[column] < end)]


def calc_count(rows, kpi, data, start, end):
    return len(in_period(rows, start, end))


def calc_sum(rows, kpi, data, start, end):
    return in_period(rows, start, end)[kpi["field"]].sum()


def calc_mean(rows, kpi, data, start, end):
    return in_period(rows, start, end)[kpi["field"]].mean()


def calc_share(rows, kpi, data, start, end):
    """% of rows that meet the 'numerator' condition."""
    rows = in_period(rows, start, end)
    if rows.empty:
        return None
    return 100 * len(rows.query(kpi["numerator"], engine="python")) / len(rows)


def calc_line_margin_pct(rows, kpi, data, start, end):
    """Gross margin % from line items: (sales - cost) / sales."""
    ids = in_period(rows, start, end)["txn_id"]
    lines = data.line_item[data.line_item["txn_id"].isin(ids)]
    sales = lines["line_amount"].sum()
    cost = (lines["qty"] * lines["unit_cost"]).sum()
    return 100 * (sales - cost) / sales if sales else None


def calc_missing_child(rows, kpi, data, start, end):
    """Value of documents that have no follow-up document, e.g. jobs with no invoice."""
    rows = rows.assign(done=rows["completed_at"].fillna(rows["created_at"]))
    rows = in_period(rows, start, end, "done")
    children = data.txn.loc[data.txn["type"] == kpi["child_type"], "parent_txn_id"]
    return rows.loc[~rows["txn_id"].isin(children), "amount"].sum()


def calc_overdue_balance(rows, kpi, data, start, end):
    """Amount past its due date and still unpaid at the END of the period."""
    overdue = (rows["created_at"] < end) & (rows["due_date"] < end) & (rows["paid_at"].isna() | (rows["paid_at"] >= end))
    return rows.loc[overdue, "amount"].sum()


def calc_per_resource(rows, kpi, data, start, end):
    """Count per worker, e.g. jobs per technician."""
    workers = (data.resource["resource_type"] == kpi["resource_type"]).sum()
    return len(in_period(rows, start, end)) / workers if workers else None


def calc_per_shift_hour(rows, kpi, data, start, end):
    """Count per rostered staff hour, e.g. orders per labour hour."""
    shifts = in_period(data.shift, start, end, "start_at")
    hours = ((shifts["end_at"] - shifts["start_at"]).dt.total_seconds() / 3600).sum()
    return len(in_period(rows, start, end)) / hours if hours else None


CALCULATORS = {
    "count": calc_count,
    "sum": calc_sum,
    "mean": calc_mean,
    "share": calc_share,
    "line_margin_pct": calc_line_margin_pct,
    "missing_child": calc_missing_child,
    "overdue_balance": calc_overdue_balance,
    "per_resource": calc_per_resource,
    "per_shift_hour": calc_per_shift_hour,
}


# ---------------------------------------------------------------- evaluation

def kpi_rows(kpi: dict, data: TenantData) -> pd.DataFrame:
    """The transactions a KPI looks at: its txn_type, narrowed by its 'where' condition."""
    rows = data.txn[data.txn["type"] == kpi["txn_type"]]
    if kpi.get("where"):
        rows = rows.query(kpi["where"], engine="python")
    return rows


def periods(data: TenantData, grain: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """All complete weeks (Mon-Sun) or calendar months in the data, oldest first."""
    first = data.txn["created_at"].min().normalize()
    if grain == "week":   # every Monday on or after the first day of data
        spans = [(s, s + pd.Timedelta(days=7)) for s in pd.date_range(first, data.now, freq="W-MON")]
    else:                 # every 1st of the month on or after the first day of data
        spans = [(s, s + pd.offsets.MonthBegin()) for s in pd.date_range(first, data.now, freq="MS")]
    return [(s, e) for s, e in spans if e <= data.now]


def compute_snapshots(data: TenantData, kpis: list[dict]) -> pd.DataFrame:
    """KPI value for every complete week and month -> rows for the kpi_snapshot table."""
    out = []
    for kpi in kpis:
        rows = kpi_rows(kpi, data)
        calculator = CALCULATORS[kpi["calc"]]
        for grain in ("week", "month"):
            for start, end in periods(data, grain):
                value = calculator(rows, kpi, data, start, end)
                out.append({"tenant_id": data.tenant_id, "kpi_id": kpi["id"], "grain": grain,
                            "period_start": start, "value": None if value is None else float(value)})
    return pd.DataFrame(out)


def target_for(kpi: dict, grain: str) -> float:
    """Targets in kpis.yaml are monthly; scale additive KPIs down for a week."""
    if grain == "week" and kpi["calc"] in ADDITIVE:
        return kpi["target"] * 12 / 52
    return kpi["target"]


def status(value, kpi: dict, grain: str) -> str:
    """green = on target, amber = within amber_pct of target, red = worse."""
    if value is None or pd.isna(value):
        return "grey"
    target = target_for(kpi, grain)
    band = target * kpi.get("amber_pct", 5) / 100
    if kpi["direction"] == "up":
        return "green" if value >= target else "amber" if value >= target - band else "red"
    return "green" if value <= target else "amber" if value <= target + band else "red"
