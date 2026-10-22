"""Prototype tour: one card per deliverable, its status, and links to the pages that show it.
Meant as the starting point for scoping conversations with the sponsor."""
import streamlit as st

from core.data import TABLES
from core.model import MODEL
from views.common import archetype_config, current_user, page_header, tenant_data, tenant_table

# (deliverable, icon, status label, badge colour, what it is, page keys that show it)
DELIVERABLES = [
    ("D2 · Common data model", ":material/schema:", "Working prototype", "blue",
     "One set of tables for every industry. Each client's own export is mapped in with a config file, "
     "so a new industry is onboarded by adding config, not by changing code.", []),
    ("D3 · Prototype dashboard", ":material/dashboard:", "Working prototype", "green",
     "Owner: performance vs target and what needs attention. Manager: this week's action list with "
     "drill-down and CSV export. Location view: demand, capacity gaps and risk on a map.",
     ["overview", "actions", "location"]),
    ("D4 · Security & PDPA", ":material/shield:", "Working, mock level", "green",
     "Role-based pages, strict client separation in every query, masked personal data and an audit log. "
     "Production needs are listed on the page.", ["security"]),
    ("D5 · Predictive proof of concept", ":material/trending_up:", "Illustrative mock-up", "orange",
     "A simple 4-week forecast and an explainable credit-risk score, to discuss which predictions would help.",
     ["forecast"]),
    ("UAT support", ":material/fact_check:", "Not shown yet", "gray",
     "Decision tasks with computed answers, plus an Excel baseline to compare speed and accuracy.", []),
    ("4th-industry onboarding", ":material/add_business:", "Not shown yet", "gray",
     "Onboard a new industry (e.g. a tuition centre) with config files only, and count the lines changed.", []),
]


def render(pages: dict, allowed: list[str]):
    user = current_user()
    cfg = archetype_config(user["archetype"])
    data = tenant_data(user["tenant_id"])

    page_header("Prototype tour", eyebrow="Start here",
                subtitle=f"Viewing {user['tenant_name']} ({cfg['label']}) as {user['role']}. "
                         "Sign in as the other company to see the same pages and code serve a different industry.")

    # D2 has no page of its own, so show its key facts here
    rows = sum(len(getattr(data, t)) for t in TABLES)
    fixes = int(tenant_table("data_quality_log", user["tenant_id"])["rows_affected"].sum())
    a, b, c = st.columns(3)
    a.metric("Common tables (all industries)", len(MODEL), border=True)
    b.metric("Records for this client", f"{rows:,}", border=True)
    c.metric("Rows auto-cleaned", f"{fixes:,}", border=True)

    for start in range(0, len(DELIVERABLES), 2):
        for col, (title, icon, status, colour, what, page_keys) in zip(st.columns(2), DELIVERABLES[start:start + 2]):
            with col.container(border=True, height="stretch"):
                st.markdown(f"#### {icon} {title}")
                st.badge(status, color=colour)
                st.markdown(f":gray[{what}]")
                for key in page_keys:
                    if key in allowed:
                        st.page_link(pages[key], icon=":material/arrow_forward:")
                    else:
                        other = "manager" if user["role"] == "owner" else "owner"
                        st.caption(f":material/lock: {pages[key].title}: sign in as {other}")
