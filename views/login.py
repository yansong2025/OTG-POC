"""Mock login page (D4). Demo users come from config/tenants.yaml; all use password 'demo'.

For demos, each user also has a one-click login button (it still goes through
the same password check, with the demo password).
"""
import streamlit as st

from core.auth import verify_password
from core.config import load_tenants
from core.db import find_user, log_event
from views.common import archetype_config

DEMO_PASSWORD = "demo"
FEATURES = [
    (":material/dashboard:", "Owner overview", "Performance vs target and what needs attention, weekly or monthly."),
    (":material/checklist:", "Manager action list", "This week's jobs to bill, quotes to chase and customers to call, with drill-down."),
    (":material/location_on:", "Location insights", "Demand, capacity gaps and risk across Singapore planning areas."),
    (":material/shield:", "Secure by design", "Strict client separation, role-based pages and masked personal data."),
]


def log_in(username: str, password: str) -> bool:
    user = find_user(username.strip())
    if user and verify_password(password, user["password_hash"]):
        user.pop("password_hash")
        st.session_state["user"] = user
        log_event(user["tenant_id"], user["user_id"], "login")
        return True
    st.session_state["login_error"] = True
    return False


def render():
    st.space("large")
    hero, _, card = st.columns([1.15, 0.1, 1])

    with hero:
        st.caption("**SME OPERATIONS ANALYTICS · CAPSTONE PROTOTYPE**")
        st.title("Analytic PoC", anchor=False)
        st.markdown("#### One analytics layer that turns orders, jobs and quotations into weekly decisions, "
                    "for any SME industry.")
        st.space("small")
        for icon, title, text in FEATURES:
            icon_col, text_col = st.columns([0.08, 1], vertical_alignment="top")
            icon_col.markdown(f"### {icon}")
            text_col.markdown(f"**{title}**  \n:gray[{text}]")
        st.caption("All data shown is synthetic. No real company or customer data is used.")

    with card:
        with st.container(border=True):
            st.subheader("Sign in", anchor=False)
            with st.form("login", border=False):
                username = st.text_input("Username", placeholder="e.g. fs.owner")
                password = st.text_input("Password", type="password")
                if st.form_submit_button("Sign in", type="primary", width="stretch"):
                    if log_in(username, password):
                        st.rerun()
            if st.session_state.pop("login_error", False):
                st.error("Unknown username or wrong password.", icon=":material/error:")

        with st.container(border=True):
            st.markdown("**Quick demo login**")
            st.caption("One click per role. Every demo account uses the password “demo”.")
            for tenant in load_tenants():
                st.markdown(f"{tenant['name']}  \n:gray[{archetype_config(tenant['archetype'])['label']}]")
                for col, u in zip(st.columns(len(tenant["users"])), tenant["users"]):
                    col.button(u["role"].title(), key=f"quick_{u['username']}", width="stretch",
                               icon=":material/person:" if u["role"] == "owner" else ":material/badge:",
                               on_click=log_in, args=(u["username"], DEMO_PASSWORD), help=u["username"])
