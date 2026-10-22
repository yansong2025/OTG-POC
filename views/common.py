"""Helpers shared by every dashboard page: the logged-in user, their data, and display formatting.

Data is cached per tenant_id, so one tenant's cached data can never be served
to another tenant's user.
"""
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import load_kpi_config, load_mapping
from core.data import TenantData, load_tenant_data
from core.db import read_table
from core.masking import DEFAULT_PERSONAL, mask_table
from core.rules import run_action

# Chart colours: a colour-blind-checked reference palette (first three categorical slots)
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]
MUTED = "#898781"
# KPI status -> (label, badge colour, icon). Always shown with a label, never colour alone.
STATUS = {
    "green": ("On target", "green", ":material/check_circle:"),
    "amber": ("Near target", "orange", ":material/warning:"),
    "red": ("Off target", "red", ":material/error:"),
    "grey": ("No data", "gray", ":material/help:"),
}


# ---------------------------------------------------------------- page layout

# Status tag shown on every page header (hover it for the full note)
STATUS_TAGS = {
    "prototype": ("Prototype · scope not final", "blue",
                  "Rough prototype on synthetic data, to help agree scope. Not final design or scope."),
    "illustrative": ("Illustrative mock-up", "orange",
                     "Shows the idea only so we can discuss it. Method, data and scope are still to be agreed."),
}


def page_header(title: str, subtitle: str = "", eyebrow: str = "", kind: str = "prototype"):
    """Consistent page top: small eyebrow (e.g. 'D3 · Owner view'), title, status tag, subtitle."""
    left, right = st.columns([5, 2], vertical_alignment="bottom")
    with left:
        if eyebrow:
            st.caption(f"**{eyebrow.upper()}**")
        st.title(title, anchor=False)
    label, colour, note = STATUS_TAGS[kind]
    with right:
        st.badge(label, icon=":material/construction:", color=colour, help=note)
    if subtitle:
        st.caption(subtitle)
    st.space("small")


def sidebar_profile(user: dict, on_logout):
    """Who is logged in, for which company, plus log out."""
    with st.sidebar:
        with st.container(border=True):
            st.markdown(f"**{user['tenant_name']}**")
            st.caption(archetype_config(user["archetype"])["label"])
            st.badge(f"{user['role'].title()} · {user['username']}", icon=":material/person:", color="gray")
        st.button("Log out", icon=":material/logout:", on_click=on_logout, width="stretch")


# ---------------------------------------------------------------- user and access

def current_user() -> dict:
    return st.session_state["user"]


def require_role(*roles: str):
    """Second line of defence: pages also check the role, not just the menu."""
    if current_user()["role"] not in roles:
        st.error("Your role does not have access to this page.")
        st.stop()


# ---------------------------------------------------------------- cached data (keyed by tenant)

@st.cache_data(show_spinner="Loading data...")
def tenant_data(tenant_id: str) -> TenantData:
    return load_tenant_data(tenant_id)


@st.cache_data
def tenant_table(table: str, tenant_id: str) -> pd.DataFrame:
    return read_table(table, tenant_id)


@st.cache_data
def archetype_config(archetype: str) -> dict:
    """kpis.yaml plus the label and personal-field list from mapping.yaml."""
    mapping = load_mapping(archetype)
    return {**load_kpi_config(archetype), "label": mapping.get("label", archetype),
            "personal_fields": mapping.get("personal_fields", DEFAULT_PERSONAL)}


@st.cache_data(show_spinner="Checking this week's actions...")
def action_result(tenant_id: str, archetype: str, action_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    action = next(a for a in archetype_config(archetype)["actions"] if a["id"] == action_id)
    return run_action(action, tenant_data(tenant_id))


def kpi_definitions(tenant_id: str) -> list[dict]:
    """KPI definitions from the database (kpi_definition table), as dicts the KPI engine understands."""
    defs = tenant_table("kpi_definition", tenant_id)
    order = {k["id"]: i for i, k in enumerate(archetype_config(current_user()["archetype"])["kpis"])}
    defs = defs.sort_values("kpi_id", key=lambda ids: ids.map(order))   # same order as kpis.yaml
    return [{"id": r.kpi_id, "name": r.name, "unit": r.unit, "direction": r.direction, "target": r.target,
             "amber_pct": r.amber_pct, **json.loads(r.formula)} for r in defs.itertuples()]


# ---------------------------------------------------------------- readable, masked tables

def _short(ids: pd.Series) -> pd.Series:
    """'tidewell:TECH02' -> 'TECH02'"""
    return ids.str.split(":").str[-1]


@st.cache_data
def id_labels(tenant_id: str, archetype: str) -> dict[str, dict]:
    """Readable (and PDPA-masked) names for every ID column."""
    data = tenant_data(tenant_id)
    personal = archetype_config(archetype)["personal_fields"]

    site = data.site
    unique = site["name"].is_unique
    site_names = site["name"] if unique else _short(site["site_id"]) + " · " + site["name"].fillna("")

    customer = mask_table(data.customer, "customer", personal)
    customer_names = customer["name"]
    if "name" in personal.get("customer", []):          # masked names aren't unique: add the ID
        customer_names = _short(customer["customer_id"]) + " · " + customer_names.fillna("")

    resource = mask_table(data.resource, "resource", personal)
    return {
        "site_id": dict(zip(site["site_id"], site_names)),
        "customer_id": dict(zip(customer["customer_id"], customer_names)),
        "resource_id": dict(zip(resource["resource_id"], _short(resource["resource_id"]) + " · " + resource["name"].fillna(""))),
        "product_id": dict(zip(data.product_service["product_id"], data.product_service["name"])),
    }


HIDDEN_COLUMNS = ["item", "tenant_id", "txn_id", "parent_txn_id", "extra_json"]


def readable(df: pd.DataFrame) -> pd.DataFrame:
    """Turn a rules/model output table into something a manager can read.

    IDs become (masked) names, columns get industry words ("Outlet", "Technician"),
    and empty or internal columns are hidden.
    """
    user = current_user()
    words = archetype_config(user["archetype"]).get("labels", {})
    out = df.drop(columns=[c for c in HIDDEN_COLUMNS if c in df.columns])
    out = out.dropna(axis=1, how="all")
    for column, names in id_labels(user["tenant_id"], user["archetype"]).items():
        if column in out.columns:
            out[column] = out[column].map(names).fillna(out[column])
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].dt.strftime("%Y-%m-%d %H:%M").str.replace(" 00:00", "")
    rename = {"site_id": words.get("site", "Site"), "customer_id": words.get("customer", "Customer"),
              "resource_id": words.get("resource", "Resource"), "product_id": "Product",
              "source_ref": "Ref", "amount": "Amount ($)"}
    return out.rename(columns=lambda c: rename.get(c, c.replace("_", " ").capitalize()))


# ---------------------------------------------------------------- formatting

def fmt(value, unit: str) -> str:
    if value is None or pd.isna(value):
        return "–"
    if unit == "SGD":
        if abs(value) >= 1_000_000:
            return f"${value / 1_000_000:.2f}M"
        if abs(value) >= 10_000:
            return f"${value / 1000:.1f}k"
        return f"${value:,.0f}" if abs(value) >= 100 else f"${value:.2f}"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "count":
        return f"{value:,.0f}"
    return f"{value:.2f}"


def md(text: str) -> str:
    """Escape '$' so Streamlit markdown doesn't treat '$9 ... $10' as a maths formula."""
    return text.replace("$", "\\$")


def plain(value) -> str:
    """Short display of one table cell inside a sentence."""
    if isinstance(value, float):
        return f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.1f}"
    return str(value)


def period_label(start: pd.Timestamp, grain: str) -> str:
    return f"week of {start:%d %b %Y}" if grain == "week" else f"{start:%B %Y}"


def style_chart(fig: go.Figure, height: int = 230) -> go.Figure:
    """Quiet, consistent chart chrome. Colours of grid/text follow Streamlit's light or dark theme."""
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=8, b=8), showlegend=False, hovermode="x unified")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(zeroline=False)
    return fig
