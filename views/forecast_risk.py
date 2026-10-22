"""D5 predictive proof of concept: ILLUSTRATIVE mock-up for scoping.

Uses deliberately simple methods (straight-line trend, points-based scorecard)
so the sponsor can react to the idea before the real approach is agreed.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.forecast import forecast_summary, linear_forecast, weekly_counts
from core.risk import credit_risk
from views.common import (SERIES, archetype_config, current_user, page_header, readable, style_chart,
                          tenant_data)

def render():
    user = current_user()
    cfg = archetype_config(user["archetype"])
    data = tenant_data(user["tenant_id"])

    page_header("Forecast & risk", eyebrow="D5 · Predictive proof of concept", kind="illustrative",
                subtitle=f"{user['tenant_name']} · simple, explainable methods to discuss what predictions would help")
    if "forecast" in cfg:
        forecast_section(cfg["forecast"], data)
    if "risk" in cfg:
        st.divider()
        risk_section(cfg["risk"], data)


def forecast_section(f, data):
    st.subheader(f["title"])
    counts = weekly_counts(data, f["txn_type"], f["group_by"], f.get("where"))
    summary = forecast_summary(counts)
    label = "Planning area" if f["group_by"] == "planning_area" else "Group"

    group = st.selectbox(label, summary["group"], format_func=lambda g: readable_group(g, f["group_by"]))
    result = linear_forecast(counts[group])
    st.plotly_chart(forecast_chart(result), config={"displayModeBar": False}, key="forecast_chart")
    st.caption("How it works: a straight line is fitted through the last 26 weeks and extended 4 weeks ahead. "
               "The shaded band shows the usual week-to-week variation. A real version would test better methods "
               "(seasonality, holidays, weather) and measure their accuracy before anyone relies on them.")

    st.markdown("**All groups: next 4 weeks vs last 4 weeks (weekly average)**")
    table = summary.assign(group=summary["group"].map(lambda g: readable_group(g, f["group_by"])))
    st.dataframe(table.rename(columns={"group": label, "last_4_weeks_avg": "Last 4 weeks (avg/wk)",
                                       "next_4_weeks_avg": "Next 4 weeks (forecast avg/wk)", "change_pct": "Change (%)"}),
                 hide_index=True, width="stretch")


def readable_group(group, group_by):
    if group_by.endswith("_id"):   # IDs (e.g. outlets) get their readable name
        return readable(pd.DataFrame({group_by: [group]})).iloc[0, 0]
    return group


def forecast_chart(result) -> go.Figure:
    fig = go.Figure()
    ahead = result.dropna(subset=["forecast"])
    fig.add_scatter(x=list(ahead.index) + list(ahead.index[::-1]), y=list(ahead["high"]) + list(ahead["low"][::-1]),
                    fill="toself", fillcolor="rgba(42,120,214,0.15)", mode="lines", line=dict(width=0),
                    hoverinfo="skip", name="Likely range")
    fig.add_scatter(x=result.index, y=result["actual"], mode="lines+markers", name="Actual",
                    line=dict(color=SERIES[0], width=2), marker=dict(size=8), hovertemplate="%{y:.0f}<extra>Actual</extra>")
    fig.add_scatter(x=result.index, y=result["trend"], mode="lines", name="Trend",
                    line=dict(color=SERIES[0], width=1.5, dash="dot"), hoverinfo="skip")
    fig.add_scatter(x=ahead.index, y=ahead["forecast"], mode="lines+markers", name="Forecast",
                    line=dict(color=SERIES[1], width=2, dash="dash"), marker=dict(size=8),
                    hovertemplate="%{y:.1f}<extra>Forecast</extra>")
    fig = style_chart(fig, height=320)
    fig.update_layout(showlegend=True, legend=dict(orientation="h", y=1.1, x=0))
    return fig


def risk_section(config, data):
    st.subheader("Customer credit-risk score")
    risk = credit_risk(data, config)
    counts = risk["level"].value_counts()
    for col, level in zip(st.columns(3), ["High", "Medium", "Low"]):
        col.metric(f"{level} risk customers", int(counts.get(level, 0)))

    shown = risk[risk["level"].isin(["High", "Medium"])].copy()
    shown["level"] = shown["level"].astype(str)
    table = readable(shown[["customer_id", "level", "score", "overdue_amount", "late_recent", "late_change", "reasons"]])
    st.dataframe(table.rename(columns={"Late recent": "Avg days late (90 d)", "Late change": "Change in days late",
                                       "Overdue amount": "Overdue ($)", "Reasons": "Why"}),
                 hide_index=True, width="stretch")

    with st.expander("How the score works (points from config)"):
        st.markdown("Each rule adds points when it applies; the reasons column shows which rules fired. "
                    f"High = {config['levels']['high']}+ points, Medium = {config['levels']['medium']}+.")
        st.table([{"Condition": r["when"], "Points": r["points"]} for r in config["rules"]])
