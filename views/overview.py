"""Owner overview (D3): KPI cards vs previous period and target, what needs attention, trends.

Which KPIs appear comes entirely from the tenant's kpi_definition rows
(loaded from kpis.yaml), so this one page serves every archetype.
"""
import plotly.graph_objects as go
import streamlit as st

from core.kpis import status, target_for
from views.common import (MUTED, SERIES, STATUS, action_result, archetype_config, current_user, fmt,
                          kpi_definitions, md, page_header, period_label, plain, readable, require_role,
                          style_chart, tenant_data, tenant_table)


def render():
    require_role("owner")
    user = current_user()
    cfg = archetype_config(user["archetype"])
    data = tenant_data(user["tenant_id"])
    kpis = kpi_definitions(user["tenant_id"])
    snapshots = tenant_table("kpi_snapshot", user["tenant_id"])

    page_header("Business overview", eyebrow="D3 · Owner view",
                subtitle=f"{user['tenant_name']} · {cfg['label']} · data up to {data.last_day:%d %b %Y}")

    grain = st.segmented_control("Period", ["week", "month"], default="month", label_visibility="collapsed",
                                 format_func=lambda g: f"Last full {g}") or "month"
    series = snapshots[snapshots["grain"] == grain].pivot(index="period_start", columns="kpi_id", values="value").sort_index()
    current, previous = series.index[-1], series.index[-2]
    n_periods = 26 if grain == "week" else 12
    recent = series.tail(n_periods)

    # ---------------- KPI cards
    st.subheader(f"Key numbers · {period_label(current, grain)}", anchor=False)
    results = []
    for row_start in range(0, len(kpis), 3):
        for col, kpi in zip(st.columns(3), kpis[row_start:row_start + 3]):
            value, before = series.at[current, kpi["id"]], series.at[previous, kpi["id"]]
            state = status(value, kpi, grain)
            results.append((kpi, value, state))
            if kpi["unit"] == "%":
                delta = f"{value - before:+.1f} pts"
            else:
                delta = f"{100 * (value / before - 1):+.1f}%" if before else None
            with col.container(border=True):
                st.metric(kpi["name"], fmt(value, kpi["unit"]), delta,
                          delta_color="normal" if kpi["direction"] == "up" else "inverse",
                          delta_description=f"vs previous {grain}",
                          chart_data=recent[kpi["id"]].round(2).tolist(), chart_type="area")
                label, colour, icon = STATUS[state]
                left, right = st.columns(2, vertical_alignment="center")
                left.badge(label, icon=icon, color=colour)
                right.caption(md(f"Target **{fmt(target_for(kpi, grain), kpi['unit'])}**"))

    # ---------------- Attention needed
    st.subheader("Needs your attention", anchor=False)
    kpi_col, ops_col = st.columns(2)
    with kpi_col.container(border=True, height="stretch"):
        st.markdown("**KPIs off target**")
        flagged = [r for r in sorted(results, key=lambda r: r[2] != "red") if r[2] in ("red", "amber")]
        for kpi, value, state in flagged:
            _, _, icon = STATUS[state]
            st.markdown(md(f"{icon} **{kpi['name']}**: {fmt(value, kpi['unit'])} "
                           f":gray[(target {fmt(target_for(kpi, grain), kpi['unit'])})]"))
        if not flagged:
            st.markdown(":material/check_circle: All KPIs on target.")

    with ops_col.container(border=True, height="stretch"):
        st.markdown("**Operational issues this week**")
        for action in cfg.get("actions", []):
            summary, _ = action_result(user["tenant_id"], user["archetype"], action["id"])
            if summary.empty:
                continue
            top = readable(summary.head(1)).iloc[0]
            example = " · ".join(f"{k}: {plain(v)}" for k, v in list(top.items())[:3])
            st.markdown(md(f":material/flag: **{action['title']}** :blue-badge[{len(summary)}]  \n"
                           f":gray[Top: {example}]"))
        st.caption("Managers see each item, with drill-down, on their Action list.")

    # ---------------- Trend
    st.subheader(f"Trend · last {n_periods} {grain}s", anchor=False)
    names = {k["id"]: k["name"] for k in kpis}
    chosen = st.pills("KPI", list(names), default=kpis[0]["id"], format_func=names.get,
                      label_visibility="collapsed") or kpis[0]["id"]
    kpi = next(k for k in kpis if k["id"] == chosen)
    with st.container(border=True):
        st.plotly_chart(trend_chart(recent[chosen], target_for(kpi, grain), kpi["unit"]),
                        config={"displayModeBar": False}, key="trend_chart")


def trend_chart(values, target: float, unit: str) -> go.Figure:
    hover_format = {"SGD": "$%{y:,.0f}", "%": "%{y:.1f}%", "count": "%{y:,.0f}"}.get(unit, "%{y:.2f}")
    fig = go.Figure()
    fig.add_scatter(x=values.index, y=values.values, mode="lines+markers", name="Actual",
                    line=dict(color=SERIES[0], width=2.5), marker=dict(size=8),
                    hovertemplate=hover_format + "<extra>Actual</extra>")
    fig.add_hline(y=target, line=dict(color=MUTED, width=1.5, dash="dash"),
                  annotation_text="Target", annotation_position="top left", annotation_font_color=MUTED)
    return style_chart(fig, height=320)
