"""D5 (illustrative): a simple, explainable customer credit-risk score.

A points-based scorecard: each rule in the "risk" section of kpis.yaml adds
points when its condition holds, and contributes a plain-English reason.
No machine learning: the point is that every score can be explained.
"""
import pandas as pd

from core.data import TenantData


def payment_features(data: TenantData, txn_type: str = "invoice") -> pd.DataFrame:
    """Per customer: how late they pay now vs before, and what is overdue today."""
    inv = data.txn[(data.txn["type"] == txn_type) & (data.txn["due_date"] < data.now)].copy()
    # Days late: paid invoices = paid date - due date; unpaid ones = today - due date (so far)
    inv["days_late"] = (inv["paid_at"].fillna(data.now) - inv["due_date"]).dt.days
    recent = inv[inv["due_date"] >= data.now - pd.Timedelta(days=90)]
    before = inv[(inv["due_date"] < data.now - pd.Timedelta(days=90)) & (inv["due_date"] >= data.now - pd.Timedelta(days=180))]
    unpaid = inv[inv["paid_at"].isna()]

    f = pd.DataFrame({
        "late_recent": recent.groupby("customer_id")["days_late"].mean(),
        "late_before": before.groupby("customer_id")["days_late"].mean(),
        "overdue_amount": unpaid.groupby("customer_id")["amount"].sum(),
        "oldest_overdue_days": unpaid.groupby("customer_id")["days_late"].max(),
    })
    f = f[f["late_recent"].notna() | f["overdue_amount"].notna()]
    f["late_change"] = f["late_recent"] - f["late_before"]
    limits = data.customer.set_index("customer_id")["credit_limit"]
    f["overdue_pct_of_limit"] = 100 * f["overdue_amount"] / f.index.map(limits)
    return f.fillna({"overdue_amount": 0})


def credit_risk(data: TenantData, config: dict) -> pd.DataFrame:
    """Score every customer with the rules from kpis.yaml. Highest score first."""
    f = payment_features(data, config.get("txn_type", "invoice"))
    f["score"] = 0
    f["reasons"] = [[] for _ in range(len(f))]
    for rule in config["rules"]:
        hit = f.eval(rule["when"]).fillna(False).astype(bool)   # missing values never trigger a rule
        f.loc[hit, "score"] += rule["points"]
        for customer in f.index[hit]:
            f.at[customer, "reasons"].append(rule["reason"].format(**f.loc[customer].to_dict()))

    levels = config.get("levels", {"high": 50, "medium": 25})
    f["level"] = pd.cut(f["score"], [-1, levels["medium"] - 1, levels["high"] - 1, 1000], labels=["Low", "Medium", "High"])
    f["reasons"] = f["reasons"].map(lambda r: "; ".join(r) if r else "Pays on time")
    f = f.round(1).reset_index().rename(columns={"index": "customer_id"})
    return f.sort_values(["score", "overdue_amount"], ascending=False)
