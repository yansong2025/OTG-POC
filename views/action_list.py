"""Manager action list (D3): what to act on this week, with drill-down and CSV export.

The list of actions comes from the "actions" section of the tenant's kpis.yaml;
each one is computed by a generic rule in core/rules.py.
"""
import pandas as pd
import streamlit as st

from core.db import log_event
from views.common import page_header, action_result, archetype_config, current_user, readable, require_role, tenant_data


def render():
    require_role("manager")
    user = current_user()
    cfg = archetype_config(user["archetype"])
    data = tenant_data(user["tenant_id"])
    actions = cfg.get("actions", [])
    results = {a["id"]: action_result(user["tenant_id"], user["archetype"], a["id"]) for a in actions}

    page_header("Action list this week", eyebrow="D3 · Manager view",
                subtitle=f"{user['tenant_name']} · week ending {data.last_day:%d %b %Y} · "
                         "pick a row to see the records behind it")

    # Headline counts + one CSV with everything
    for col, action in zip(st.columns(len(actions)), actions):
        col.metric(action["title"], len(results[action["id"]][0]), border=True)
    export = pd.concat([readable(results[a["id"]][0]).assign(Action=a["title"]) for a in actions], ignore_index=True)
    export = export[["Action"] + [c for c in export.columns if c != "Action"]]
    st.download_button("Export full action list (CSV)", export.to_csv(index=False), file_name="action_list.csv",
                       mime="text/csv", icon=":material/download:", on_click=log_export, args=("full action list",))

    tabs = st.tabs([f"{a['title']} ({len(results[a['id']][0])})" for a in actions])
    for tab, action in zip(tabs, actions):
        with tab:
            show_action(action, *results[action["id"]])


def show_action(action: dict, summary: pd.DataFrame, records: pd.DataFrame):
    st.caption(action["why"])
    if summary.empty:
        st.success("Nothing to act on.", icon=":material/check_circle:")
        return

    table = readable(summary)
    picked = st.dataframe(table, hide_index=True, width="stretch", height=320, on_select="rerun",
                          selection_mode="single-row", key=f"table_{action['id']}")
    st.download_button(f"Export this list (CSV)", table.to_csv(index=False), file_name=f"{action['id']}.csv",
                       mime="text/csv", key=f"csv_{action['id']}", on_click=log_export, args=(action["title"],))

    rows = picked.selection.rows
    if rows:
        item = summary.iloc[rows[0]]["item"]
        detail = records[records["item"] == item]
        st.markdown(f"**Records behind: {' · '.join(str(v) for v in table.iloc[rows[0]].values[:2])}** "
                    f"({len(detail)} rows)")
        st.dataframe(readable(detail), hide_index=True, width="stretch", key=f"detail_{action['id']}")
    else:
        st.caption(":material/touch_app: Select a row to drill down.")


def log_export(what: str):
    user = current_user()
    log_event(user["tenant_id"], user["user_id"], "export_csv", what)
