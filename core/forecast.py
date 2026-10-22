"""D5 (illustrative): a simple 4-week volume forecast.

Method: fit a straight line through the last 26 weekly counts and extend it
4 weeks. The band is +/- 2 x the typical distance of past weeks from the line.
Deliberately basic so it can be explained in one sentence.
"""
import numpy as np
import pandas as pd

from core.data import TenantData
from core.location import filtered, with_location


def weekly_counts(data: TenantData, txn_type: str, group_by: str, where: str | None = None,
                  weeks: int = 26) -> pd.DataFrame:
    """Rows = the last N complete weeks (Monday start), columns = groups, values = counts."""
    rows = with_location(filtered(data, txn_type, where), data)
    if group_by == "segment":
        rows["segment"] = rows["customer_id"].map(data.customer.set_index("customer_id")["segment"])
    rows["week"] = rows["created_at"].dt.to_period("W-SUN").dt.start_time
    counts = rows.groupby(["week", group_by]).size().unstack(fill_value=0)
    last_full_week = data.now - pd.Timedelta(days=7)
    return counts[counts.index <= last_full_week].tail(weeks)


def linear_forecast(series: pd.Series, horizon: int = 4) -> pd.DataFrame:
    """Straight-line trend + forecast. Returns weeks with actual, trend, forecast, low, high."""
    x = np.arange(len(series))
    slope, intercept = np.polyfit(x, series.to_numpy(dtype=float), 1)
    trend = intercept + slope * x
    spread = 2 * np.std(series.to_numpy() - trend)

    future_x = np.arange(len(series), len(series) + horizon)
    future_weeks = [series.index[-1] + pd.Timedelta(weeks=i) for i in range(1, horizon + 1)]
    forecast = np.clip(intercept + slope * future_x, 0, None)
    past = pd.DataFrame({"actual": series.to_numpy(), "trend": trend}, index=series.index)
    ahead = pd.DataFrame({"forecast": forecast, "low": np.clip(forecast - spread, 0, None),
                          "high": forecast + spread}, index=future_weeks)
    return pd.concat([past, ahead])


def forecast_summary(counts: pd.DataFrame, horizon: int = 4) -> pd.DataFrame:
    """Per group: last 4 weeks vs the next 4 forecast weeks."""
    rows = []
    for group in counts.columns:
        f = linear_forecast(counts[group], horizon)
        last = counts[group].tail(horizon).mean()
        nxt = f["forecast"].dropna().mean()
        rows.append({"group": group, "last_4_weeks_avg": round(last, 1), "next_4_weeks_avg": round(nxt, 1),
                     "change_pct": round(100 * (nxt / last - 1), 1) if last else None})
    return pd.DataFrame(rows).sort_values("next_4_weeks_avg", ascending=False)
