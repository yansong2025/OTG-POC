"""Location analytics for the Smart City view: activity by planning area and by site.

Generic building blocks; which ones a tenant sees (and how they are coloured)
is set in the "location" section of kpis.yaml.
"""
import numpy as np
import pandas as pd

from core.config import load_planning_areas
from core.data import TenantData
from core.geo import distance_km


def filtered(data: TenantData, txn_type: str, where: str | None = None) -> pd.DataFrame:
    rows = data.txn[data.txn["type"] == txn_type]
    return rows.query(where, engine="python") if where else rows


def with_location(rows: pd.DataFrame, data: TenantData) -> pd.DataFrame:
    """Add the site's planning area and coordinates to each transaction."""
    sites = data.site.set_index("site_id")
    return rows.assign(planning_area=rows["site_id"].map(sites["planning_area"]),
                       lat=rows["site_id"].map(sites["lat"]), lon=rows["site_id"].map(sites["lon"]))


def area_summary(data: TenantData, txn_type: str, where: str | None = None, weeks: int = 8) -> pd.DataFrame:
    """Per planning area: volume in the last N weeks, growth vs the N weeks before, repeat share."""
    rows = with_location(filtered(data, txn_type, where), data)
    cutoff = data.now - pd.Timedelta(weeks=weeks)
    recent = rows[rows["created_at"] >= cutoff]
    before = rows[(rows["created_at"] < cutoff) & (rows["created_at"] >= cutoff - pd.Timedelta(weeks=weeks))]

    out = recent.groupby("planning_area").agg(
        count=("txn_id", "count"), value=("amount", "sum"), repeats=("is_repeat", "sum"), sites=("site_id", "nunique"))
    out["count_before"] = before.groupby("planning_area").size()
    out = out.fillna({"count_before": 0}).reset_index()
    out["per_week"] = (out["count"] / weeks).round(1)
    out["growth_pct"] = (100 * (out["count"] / out["count_before"].replace(0, np.nan) - 1)).round(1)
    out["repeat_pct"] = (100 * out["repeats"] / out["count"]).round(1)
    areas = load_planning_areas()[["planning_area", "region", "lat", "lon"]]
    return areas.merge(out, on="planning_area")


def site_summary(data: TenantData, txn_type: str, where: str | None = None,
                 recent_weeks: int = 4, baseline_weeks: int = 8) -> pd.DataFrame:
    """Per site: weekly value recently vs before, for colouring outlets on a map."""
    rows = filtered(data, txn_type, where)
    cutoff = data.now - pd.Timedelta(weeks=recent_weeks)
    start = cutoff - pd.Timedelta(weeks=baseline_weeks)
    recent = rows[rows["created_at"] >= cutoff].groupby("site_id")["amount"].agg(["sum", "count"])
    before = rows[(rows["created_at"] >= start) & (rows["created_at"] < cutoff)].groupby("site_id")["amount"].sum()

    out = pd.DataFrame({
        "weekly_value": (recent["sum"] / recent_weeks).round(0),
        "weekly_count": (recent["count"] / recent_weeks).round(0),
        "earlier_weekly_value": (before / baseline_weeks).round(0),
    }).reset_index()
    out["change_pct"] = (100 * (out["weekly_value"] / out["earlier_weekly_value"] - 1)).round(1)
    sites = data.site[["site_id", "name", "planning_area", "lat", "lon"]]
    return sites.merge(out, on="site_id").dropna(subset=["lat"])


def capacity_ranking(data: TenantData, txn_type: str, resource_type: str, where: str | None = None,
                     weeks: int = 8, radius_km: float = 6.0) -> pd.DataFrame:
    """Demand per area vs how many workers are based nearby. Highest 'jobs per nearby worker' first.

    'Nearby' = the worker's home planning area centre is within radius_km of the area centre.
    Also shows how far workers actually travelled to jobs there (a symptom of thin coverage).
    """
    areas = area_summary(data, txn_type, where, weeks)
    workers = data.resource[data.resource["resource_type"] == resource_type]
    centres = load_planning_areas().set_index("planning_area")
    home = workers["home_area"].map(centres["lat"]), workers["home_area"].map(centres["lon"])

    areas["workers_nearby"] = [
        int((distance_km(a.lat, a.lon, home[0], home[1]) <= radius_km).sum()) for a in areas.itertuples()]
    # Fewer than one nearby worker still counts as 0.5, so the ratio stays finite but very high
    areas["per_week_per_worker"] = (areas["per_week"] / areas["workers_nearby"].clip(lower=0.5)).round(1)

    # Average travel distance: worker's home area centre -> job site
    rows = with_location(filtered(data, txn_type, where), data)
    rows = rows[rows["created_at"] >= data.now - pd.Timedelta(weeks=weeks)].dropna(subset=["lat"])
    worker_home = workers.set_index("resource_id")["home_area"]
    rows = rows.assign(home_lat=rows["resource_id"].map(worker_home).map(centres["lat"]),
                       home_lon=rows["resource_id"].map(worker_home).map(centres["lon"]))
    rows["travel_km"] = distance_km(rows["home_lat"], rows["home_lon"], rows["lat"], rows["lon"])
    areas["avg_travel_km"] = areas["planning_area"].map(rows.groupby("planning_area")["travel_km"].mean()).round(1)

    # Flag: workload per nearby worker well above typical AND a meaningful amount of demand
    areas["needs_capacity"] = ((areas["per_week_per_worker"] > 1.5 * areas["per_week_per_worker"].median())
                               & (areas["per_week"] >= areas["per_week"].median()))
    areas = areas.sort_values("per_week_per_worker", ascending=False).reset_index(drop=True)
    areas.insert(0, "rank", areas.index + 1)
    return areas
