"""Location-based operations view (D3, Smart City track).

The panels shown come from the "location" section of the tenant's kpis.yaml.
Each panel type below is generic; config picks which ones and what to colour by.
Base map tiles come from CARTO's public tile server (no API key, no data sent).
"""
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from core.config import load_planning_areas
from core.location import area_summary, capacity_ranking, site_summary
from core.risk import credit_risk
from views.common import archetype_config, current_user, page_header, readable, tenant_data

SG_CENTRE = {"lat": 1.3521, "lon": 103.8198}
SEQUENTIAL = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]                      # one hue, light -> dark
DIVERGING = [[0, "#e34948"], [0.5, "#f0efec"], [1, "#2a78d6"]]                              # red = down, blue = up
RISK_COLOURS = {"Low": "#0ca30c", "Medium": "#fab219", "High": "#d03b3b"}


def render():
    user = current_user()
    cfg = archetype_config(user["archetype"])
    data = tenant_data(user["tenant_id"])

    page_header("Location view", eyebrow="D3 · Smart City operations",
                subtitle=f"{user['tenant_name']} · Singapore planning areas · data up to {data.last_day:%d %b %Y}")

    for panel in cfg.get("location", []):
        with st.container(border=True):
            st.subheader(panel["title"], anchor=False)
            st.caption(panel.get("why", ""))
            PANELS[panel["panel"]](panel, data, cfg)


def sequential() -> list[str]:
    """More = darker on a light map, more = brighter on a dark map, so big values always stand out."""
    return SEQUENTIAL[::-1] if st.context.theme.type == "dark" else SEQUENTIAL


def base_map(fig: go.Figure, height: int = 460) -> go.Figure:
    style = "carto-darkmatter" if st.context.theme.type == "dark" else "carto-positron"
    fig.update_layout(map_style=style, map_center=SG_CENTRE, map_zoom=10.4, height=height,
                      margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation="h", y=1.02, x=0))
    return fig


def show_map(fig: go.Figure, key: str):
    st.plotly_chart(base_map(fig), config={"displayModeBar": False, "scrollZoom": True}, key=key)


# ---------------------------------------------------------------- panel types

def capacity_panel(panel, data, cfg):
    """Demand per area vs workers based nearby, plus a 'needs more capacity' ranking."""
    ranking = capacity_ranking(data, panel["txn_type"], panel["resource_type"], panel.get("where"),
                               radius_km=panel.get("radius_km", 6))
    worker = cfg.get("labels", {}).get("resource", "Worker").lower()

    fig = px.scatter_map(ranking, lat="lat", lon="lon", size="per_week", color="per_week_per_worker",
                         color_continuous_scale=sequential(), size_max=38, hover_name="planning_area",
                         hover_data={"per_week": True, "workers_nearby": True, "per_week_per_worker": True,
                                     "avg_travel_km": True, "lat": False, "lon": False},
                         labels={"per_week": "Jobs per week", "workers_nearby": f"{worker}s within {panel.get('radius_km', 6)} km",
                                 "per_week_per_worker": f"Jobs per week per nearby {worker}", "avg_travel_km": "Avg travel (km)"})
    # Where the workers are based
    centres = load_planning_areas().set_index("planning_area")
    homes = data.resource[data.resource["resource_type"] == panel["resource_type"]]["home_area"].value_counts()
    fig.add_trace(go.Scattermap(lat=homes.index.map(centres["lat"]), lon=homes.index.map(centres["lon"]),
                                mode="markers", marker=dict(size=[8 + 4 * n for n in homes], color="#eb6834"),
                                text=[f"{area}: {n} {worker}{'s' if n > 1 else ''} based here" for area, n in homes.items()],
                                name=f"{worker.title()} base (size = how many)", hovertemplate="%{text}<extra></extra>"))
    fig.update_layout(coloraxis_colorbar=dict(title="Jobs/wk per<br>nearby " + worker))
    show_map(fig, f"map_{panel['title']}")

    st.markdown(f"**Areas needing more {worker} capacity**")
    table = ranking[["rank", "planning_area", "region", "per_week", "growth_pct", "workers_nearby",
                     "per_week_per_worker", "avg_travel_km", "needs_capacity"]].head(10)
    table = table.assign(needs_capacity=table["needs_capacity"].map({True: "Yes", False: ""}))
    st.dataframe(readable(table).rename(columns={"Per week": "Jobs per week", "Growth pct": "Growth vs previous 8 wks (%)",
                                                 "Workers nearby": f"{worker.title()}s nearby",
                                                 "Per week per worker": f"Jobs/wk per nearby {worker}",
                                                 "Avg travel km": "Avg travel (km)",
                                                 "Needs capacity": "Needs more capacity"}),
                 hide_index=True, width="stretch")


def area_bubbles_panel(panel, data, cfg):
    """Bubble per planning area: size = volume, colour = growth or repeat share."""
    areas = area_summary(data, panel["txn_type"], panel.get("where"))
    colour = panel.get("colour_by", "growth_pct")
    names = {"growth_pct": "Growth vs previous 8 wks (%)", "repeat_pct": "Repeat visits (%)", "count": "Jobs (8 wks)"}
    scale = dict(color_continuous_scale=DIVERGING, color_continuous_midpoint=0) if colour == "growth_pct" \
        else dict(color_continuous_scale=sequential())
    fig = px.scatter_map(areas, lat="lat", lon="lon", size="count", color=colour, size_max=38, hover_name="planning_area",
                         hover_data={"count": True, "growth_pct": True, "repeats": True, "repeat_pct": True,
                                     "lat": False, "lon": False},
                         labels={**names, "repeats": "Repeat visits"}, **scale)
    show_map(fig, f"map_{panel['title']}")
    top = areas.sort_values(colour, ascending=False).head(5)
    st.markdown("**Top 5 areas:** " + ", ".join(f"{r.planning_area} ({getattr(r, colour):.0f}%)" for r in top.itertuples()))


def site_points_panel(panel, data, cfg):
    """Each site (e.g. outlet): size = weekly value, colour = change vs before."""
    sites = site_summary(data, panel["txn_type"], panel.get("where"))
    fig = px.scatter_map(sites, lat="lat", lon="lon", size="weekly_value", color="change_pct", size_max=40,
                         hover_name="name", color_continuous_scale=DIVERGING, color_continuous_midpoint=0,
                         hover_data={"planning_area": True, "weekly_value": ":,.0f", "change_pct": True, "lat": False, "lon": False},
                         labels={"weekly_value": "Weekly revenue ($)", "change_pct": "Change vs previous 8 wks (%)"})
    show_map(fig, f"map_{panel['title']}")
    st.dataframe(readable(sites.drop(columns=["lat", "lon"])), hide_index=True, width="stretch")


def customer_risk_panel(panel, data, cfg):
    """One dot per customer site, coloured by credit-risk level (from the D5 scorecard)."""
    risk = credit_risk(data, cfg["risk"]).set_index("customer_id")
    sites = data.site[data.site["customer_id"].isin(risk.index)].dropna(subset=["lat"]).copy()
    sites["level"] = sites["customer_id"].map(risk["level"]).astype(str)
    sites["score"] = sites["customer_id"].map(risk["score"])
    sites["overdue"] = sites["customer_id"].map(risk["overdue_amount"])
    fig = px.scatter_map(sites, lat="lat", lon="lon", color="level", color_discrete_map=RISK_COLOURS,
                         category_orders={"level": ["Low", "Medium", "High"]}, hover_name="name",
                         hover_data={"planning_area": True, "score": True, "overdue": ":,.0f", "lat": False, "lon": False},
                         labels={"level": "Credit risk", "score": "Risk score", "overdue": "Overdue ($)"})
    fig.update_traces(marker=dict(size=11))
    show_map(fig, f"map_{panel['title']}")

    by_area = sites.pivot_table(index="planning_area", columns="level", values="site_id", aggfunc="count", fill_value=0)
    by_area = by_area.reindex(columns=["High", "Medium", "Low"], fill_value=0).sort_values(["High", "Medium"], ascending=False)
    st.markdown("**Customers by area and risk level**")
    st.dataframe(by_area.head(10).reset_index().rename(columns={"planning_area": "Planning area"}), hide_index=True, width="stretch")


PANELS = {
    "capacity": capacity_panel,
    "area_bubbles": area_bubbles_panel,
    "site_points": site_points_panel,
    "customer_risk": customer_risk_panel,
}
