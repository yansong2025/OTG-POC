"""Action-list rules: "what should someone act on this week?"

Each archetype's kpis.yaml lists actions as {rule: <name>, params: {...}}.
Every rule below is generic (it works on the common model, not on one
industry) and returns two tables that share an "item" column:

    summary  - one row per thing to act on (shown in the action list)
    records  - the underlying records behind each item (the drill-down)

IDs (site_id, customer_id, resource_id) are left as IDs here; the page turns
them into readable, masked names.
"""
import numpy as np
import pandas as pd

from core.data import TenantData


def run_action(action: dict, data: TenantData) -> tuple[pd.DataFrame, pd.DataFrame]:
    return RULES[action["rule"]](data, **action.get("params", {}))


def _site_area(data: TenantData) -> pd.Series:
    return data.site.set_index("site_id")["planning_area"]


# ---------------------------------------------------------------- rules

def missing_child(data, parent_type, child_type, parent_status=None, min_age_days=7):
    """Documents without their follow-up, e.g. completed jobs with no invoice."""
    t = data.txn
    parents = t[t["type"] == parent_type]
    if parent_status:
        parents = parents[parents["status"] == parent_status]
    done = parents["completed_at"].fillna(parents["created_at"])
    age = (data.now - done).dt.days
    has_child = parents["txn_id"].isin(t.loc[t["type"] == child_type, "parent_txn_id"])
    missing = parents[~has_child & (age >= min_age_days)].assign(days_waiting=age, item=lambda d: d["txn_id"])

    summary = missing.assign(area=missing["site_id"].map(_site_area(data)), done_on=done.dt.date)[
        ["item", "source_ref", "done_on", "days_waiting", "customer_id", "site_id", "area", "resource_id", "category", "amount"]
    ].sort_values("amount", ascending=False)
    # Drill-down: everything on record for that customer in the last year (other jobs, invoices, payments)
    history = t[t["created_at"] >= data.now - pd.Timedelta(days=365)]
    records = missing[["item", "customer_id"]].merge(history, on="customer_id").sort_values("created_at")
    return summary, records


def repeat_sites(data, txn_type, lookback_days=60):
    """Sites that needed a repeat visit recently, with all their recent visits as drill-down."""
    t = data.txn
    recent = t[(t["type"] == txn_type) & (t["created_at"] >= data.now - pd.Timedelta(days=lookback_days))]
    repeats = recent[recent["is_repeat"] == 1]
    records = recent[recent["site_id"].isin(repeats["site_id"])].assign(item=lambda d: d["site_id"])

    summary = repeats.groupby("site_id").agg(
        repeat_visits=("txn_id", "count"),
        job_type=("category", lambda s: ", ".join(sorted(set(s)))),
        last_visit=("created_at", "max"),
        technicians=("resource_id", lambda s: ", ".join(sorted({r.split(":")[-1] for r in s.dropna()}))),
    ).reset_index()
    summary["area"] = summary["site_id"].map(_site_area(data))
    summary["last_visit"] = summary["last_visit"].dt.date
    summary["item"] = summary["site_id"]
    summary = summary[["item", "site_id", "area", "repeat_visits", "job_type", "technicians", "last_visit"]]
    return summary.sort_values(["repeat_visits", "last_visit"], ascending=False), records


def overdue(data, txn_type="invoice", min_days_overdue=1):
    """Customers with unpaid invoices past due, and whether that is getting worse."""
    t = data.txn
    invoices = t[t["type"] == txn_type]

    def overdue_on(day):
        return invoices[(invoices["due_date"] < day) & (invoices["created_at"] < day)
                        & (invoices["paid_at"].isna() | (invoices["paid_at"] >= day))]

    now = overdue_on(data.now)
    now = now[(data.now - now["due_date"]).dt.days >= min_days_overdue]
    month_ago = overdue_on(data.now - pd.Timedelta(days=30)).groupby("customer_id")["amount"].sum()
    records = now.assign(days_overdue=(data.now - now["due_date"]).dt.days, item=now["customer_id"])

    summary = records.groupby("customer_id").agg(
        overdue_amount=("amount", "sum"), invoices=("txn_id", "count"), oldest_days=("days_overdue", "max"),
    ).reset_index()
    summary["overdue_30_days_ago"] = summary["customer_id"].map(month_ago).fillna(0)
    summary["trend"] = np.where(summary["overdue_amount"] > summary["overdue_30_days_ago"] * 1.1, "growing", "stable")
    summary["item"] = summary["customer_id"]
    summary = summary[["item", "customer_id", "overdue_amount", "invoices", "oldest_days", "overdue_30_days_ago", "trend"]]
    return summary.sort_values("overdue_amount", ascending=False), records


def open_quotes(data, txn_type="quotation", min_age_days=5):
    """Open quotations ranked by value x this customer's usual win rate."""
    t = data.txn
    quotes = t[t["type"] == txn_type]
    closed = quotes[quotes["status"].isin(["won", "lost"])]
    overall_rate = (closed["status"] == "won").mean()
    win_rate = closed.groupby("customer_id")["status"].apply(lambda s: (s == "won").mean())

    open_ = quotes[(quotes["status"] == "open") & ((data.now - quotes["created_at"]).dt.days >= min_age_days)].copy()
    open_["age_days"] = (data.now - open_["created_at"]).dt.days
    open_["days_to_expiry"] = (open_["due_date"] - data.now).dt.days
    open_["customer_win_rate"] = (open_["customer_id"].map(win_rate).fillna(overall_rate) * 100).round(0)
    open_["priority_score"] = (open_["amount"] * open_["customer_win_rate"] / 100).round(0)
    open_["note"] = np.where(open_["days_to_expiry"] < 0, "expired: close or re-quote", "")
    open_["item"] = open_["txn_id"]

    summary = open_[["item", "source_ref", "customer_id", "resource_id", "age_days", "days_to_expiry", "amount",
                     "discount_pct", "customer_win_rate", "priority_score", "note"]]
    # Drill-down: this customer's quotation history, to judge how likely they are to say yes
    history = quotes[quotes["created_at"] >= data.now - pd.Timedelta(days=365)]
    records = open_[["item", "customer_id"]].merge(history, on="customer_id")
    # Still-valid quotes first (by priority), expired ones after them
    summary = summary.assign(expired=summary["days_to_expiry"] < 0).sort_values(["expired", "priority_score"], ascending=[True, False])
    return summary.drop(columns="expired"), records


def site_decline(data, txn_type, field="amount", recent_weeks=4, baseline_weeks=8, drop_pct=10):
    """Sites whose recent weekly average fell well below their own earlier weekly average."""
    t = data.txn
    start = data.now - pd.Timedelta(weeks=recent_weeks + baseline_weeks)
    rows = t[(t["type"] == txn_type) & (t["status"] == "completed") & (t["created_at"] >= start)]
    weekly = (rows.assign(week=rows["created_at"].dt.to_period("W-SUN").dt.start_time)
              .groupby(["site_id", "week"])[field].agg(["sum", "count"]).reset_index()
              .rename(columns={"sum": "value", "count": "transactions"}))
    cutoff = data.now - pd.Timedelta(weeks=recent_weeks)
    recent = weekly[weekly["week"] >= cutoff].groupby("site_id")["value"].mean()
    before = weekly[weekly["week"] < cutoff].groupby("site_id")["value"].mean()

    summary = pd.DataFrame({"recent_weekly_avg": recent.round(0), "earlier_weekly_avg": before.round(0)}).reset_index()
    summary["change_pct"] = (100 * (summary["recent_weekly_avg"] / summary["earlier_weekly_avg"] - 1)).round(1)
    summary = summary[summary["change_pct"] <= -drop_pct]
    summary["area"] = summary["site_id"].map(_site_area(data))
    summary["item"] = summary["site_id"]
    records = weekly[weekly["site_id"].isin(summary["site_id"])].assign(item=lambda d: d["site_id"])
    return summary[["item", "site_id", "area", "recent_weekly_avg", "earlier_weekly_avg", "change_pct"]], records


def understaffed(data, txn_type, weeks=4, max_per_staff=3.0):
    """Hours where orders per person on shift are above a comfortable maximum."""
    start = data.now - pd.Timedelta(weeks=weeks)
    t = data.txn
    rows = t[(t["type"] == txn_type) & (t["status"] == "completed") & (t["created_at"] >= start)]
    orders = rows.groupby(["site_id", rows["created_at"].dt.floor("h").rename("hour")]).size().rename("orders")

    # Staff on shift in each hour (counted at half past the hour)
    shifts = data.shift[data.shift["start_at"] >= start]
    staff = []
    for s in shifts.itertuples():
        for hour in pd.date_range(s.start_at.floor("h"), s.end_at, freq="h"):
            if s.start_at <= hour + pd.Timedelta(minutes=30) < s.end_at:
                staff.append((s.site_id, hour))
    staff = pd.DataFrame(staff, columns=["site_id", "hour"]).groupby(["site_id", "hour"]).size().rename("staff_on_shift")

    hourly = pd.concat([orders, staff], axis=1).fillna(0).reset_index()
    hourly = hourly[hourly["orders"] > 0]
    hourly["orders_per_staff"] = hourly["orders"] / hourly["staff_on_shift"].clip(lower=1)
    hourly["day_type"] = np.where(hourly["hour"].dt.dayofweek < 5, "Weekday", "Weekend")
    hourly["time"] = hourly["hour"].dt.strftime("%H:00")
    hourly["item"] = hourly["site_id"] + "|" + hourly["day_type"] + "|" + hourly["time"]

    summary = hourly.groupby(["item", "site_id", "day_type", "time"]).agg(
        avg_orders=("orders", "mean"), avg_staff=("staff_on_shift", "mean"), days=("orders", "count"),
    ).reset_index()
    summary["orders_per_staff"] = (summary["avg_orders"] / summary["avg_staff"].clip(lower=1)).round(1)
    summary = summary[summary["orders_per_staff"] > max_per_staff].copy()
    summary["extra_staff_needed"] = np.ceil(summary["avg_orders"] / max_per_staff - summary["avg_staff"]).astype(int)
    summary[["avg_orders", "avg_staff"]] = summary[["avg_orders", "avg_staff"]].round(1)
    records = hourly[hourly["item"].isin(summary["item"])].assign(date=lambda d: d["hour"].dt.date)
    records = records[["item", "site_id", "date", "time", "orders", "staff_on_shift", "orders_per_staff"]]
    return summary.sort_values("orders_per_staff", ascending=False).drop(columns="days"), records


def margin_gap(data, txn_type, group_by="promo_code", weeks=8, min_gap_pts=5):
    """Groups (e.g. promo codes) whose gross margin is clearly below the no-group baseline."""
    t = data.txn
    rows = t[(t["type"] == txn_type) & (t["status"] == "completed")
             & (t["created_at"] >= data.now - pd.Timedelta(weeks=weeks))]
    lines = data.line_item.merge(rows[["txn_id", group_by]], on="txn_id")
    lines["cost"] = lines["qty"] * lines["unit_cost"]
    baseline = lines[lines[group_by].isna()]
    base_margin = 100 * (1 - baseline["cost"].sum() / baseline["line_amount"].sum())

    grouped = lines.dropna(subset=[group_by]).groupby(group_by).agg(
        orders=("txn_id", "nunique"), revenue=("line_amount", "sum"), cost=("cost", "sum")).reset_index()
    grouped["margin_pct"] = (100 * (1 - grouped["cost"] / grouped["revenue"])).round(1)
    grouped["baseline_margin_pct"] = round(base_margin, 1)
    grouped["gap_pts"] = (grouped["margin_pct"] - base_margin).round(1)
    grouped["margin_lost_vs_baseline"] = (-grouped["gap_pts"] / 100 * grouped["revenue"]).round(0)
    summary = grouped[grouped["gap_pts"] <= -min_gap_pts].assign(item=lambda d: d[group_by]).drop(columns="cost")
    summary["revenue"] = summary["revenue"].round(0)

    # Drill-down: which products are sold under that promo, and at what margin
    flagged = lines[lines[group_by].isin(summary["item"])]
    records = flagged.groupby([group_by, "product_id"]).agg(
        qty=("qty", "sum"), revenue=("line_amount", "sum"), cost=("cost", "sum")).reset_index()
    records["margin_pct"] = (100 * (1 - records["cost"] / records["revenue"])).round(1)
    records = records.assign(item=records[group_by], revenue=records["revenue"].round(0)).drop(columns="cost")
    return summary[["item", group_by, "orders", "revenue", "margin_pct", "baseline_margin_pct", "gap_pts",
                    "margin_lost_vs_baseline"]], records.sort_values("revenue", ascending=False)


def discount_trend(data, txn_type, group_by="resource_id", recent_days=60, baseline_days=180, min_increase_pts=3):
    """People (or groups) whose average discount has risen clearly, and what it does to margin."""
    t = data.txn
    rows = t[t["type"] == txn_type]
    cutoff = data.now - pd.Timedelta(days=recent_days)
    recent = rows[rows["created_at"] >= cutoff]
    before = rows[(rows["created_at"] < cutoff) & (rows["created_at"] >= cutoff - pd.Timedelta(days=baseline_days))]

    def margin(df):
        lines = data.line_item[data.line_item["txn_id"].isin(df["txn_id"])].merge(df[["txn_id", group_by]], on="txn_id")
        g = lines.assign(cost=lines["qty"] * lines["unit_cost"]).groupby(group_by)[["line_amount", "cost"]].sum()
        return (100 * (1 - g["cost"] / g["line_amount"])).round(1)

    summary = pd.DataFrame({
        "recent_avg_discount": recent.groupby(group_by)["discount_pct"].mean().round(1),
        "earlier_avg_discount": before.groupby(group_by)["discount_pct"].mean().round(1),
        "recent_margin_pct": margin(recent),
        "earlier_margin_pct": margin(before),
        "recent_quotes": recent.groupby(group_by).size(),
    }).reset_index()
    summary["increase_pts"] = (summary["recent_avg_discount"] - summary["earlier_avg_discount"]).round(1)
    summary = summary[summary["increase_pts"] >= min_increase_pts].assign(item=lambda d: d[group_by])
    records = recent[recent[group_by].isin(summary["item"])].assign(item=lambda d: d[group_by])
    return summary.sort_values("increase_pts", ascending=False), records


RULES = {
    "missing_child": missing_child,
    "repeat_sites": repeat_sites,
    "overdue": overdue,
    "open_quotes": open_quotes,
    "site_decline": site_decline,
    "understaffed": understaffed,
    "margin_gap": margin_gap,
    "discount_trend": discount_trend,
}
