"""Analytic PoC prototype.  Run:  streamlit run app.py

Not logged in -> login page only.
Logged in     -> the pages allowed for the user's role (core/auth.py ROLE_PAGES).
Every page works for every archetype; differences come from config/archetypes/.
"""
import subprocess
import sys

import streamlit as st

from core.auth import ROLE_PAGES
from core.config import DB_PATH, ROOT
from core.db import log_event
from views import action_list, forecast_risk, location, login, overview, security, tour
from views.common import sidebar_profile

st.set_page_config(page_title="Analytic PoC", page_icon=str(ROOT / "assets/mark.svg"), layout="wide")
st.logo(str(ROOT / "assets/logo.svg"), icon_image=str(ROOT / "assets/mark.svg"), size="large")


@st.cache_resource(show_spinner="First start: generating the synthetic demo data (about 20 seconds)...")
def ensure_demo_data():
    """data/ is not in git. On a fresh checkout or a cloud deploy, build it once."""
    if not DB_PATH.exists():
        subprocess.run([sys.executable, "generate_data.py"], cwd=ROOT, check=True)
    return True


ensure_demo_data()


def log_out():
    user = st.session_state["user"]
    log_event(user["tenant_id"], user["user_id"], "logout")
    st.session_state.clear()


user = st.session_state.get("user")
if user is None:
    page = st.navigation([st.Page(login.render, title="Log in", icon=":material/login:")], position="hidden")
else:
    allowed = ROLE_PAGES[user["role"]]
    PAGES = {
        "tour": st.Page(lambda: tour.render(PAGES, allowed), title="Prototype tour", icon=":material/map:", url_path="tour"),
        "overview": st.Page(overview.render, title="Business overview", icon=":material/dashboard:", url_path="overview"),
        "actions": st.Page(action_list.render, title="Action list", icon=":material/checklist:", url_path="actions"),
        "location": st.Page(location.render, title="Location view", icon=":material/location_on:", url_path="location"),
        "forecast": st.Page(forecast_risk.render, title="Forecast & risk", icon=":material/trending_up:", url_path="forecast"),
        "security": st.Page(security.render, title="Security & PDPA", icon=":material/shield:", url_path="security"),
    }
    page = st.navigation([PAGES[key] for key in allowed])
    sidebar_profile(user, log_out)

page.run()
