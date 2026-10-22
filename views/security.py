"""D4 Security & PDPA: shows, live, the controls the prototype has (mock level),
and lists what a production version would need."""
import pandas as pd
import streamlit as st

from core.auth import ROLE_PAGES
from core.db import connect, read_table, tenant_query
from core.masking import mask_email, mask_name, mask_phone
from views.common import archetype_config, current_user, page_header

PAGE_NAMES = {"tour": "Prototype tour", "overview": "Business overview", "actions": "Action list",
              "location": "Location view", "forecast": "Forecast & risk", "security": "Security & PDPA"}

PRODUCTION_GAPS = [
    ("Login", "Demo users, one shared password, salted PBKDF2 hashes",
     "Company SSO or strong passwords + 2FA, lockout after failed attempts, bcrypt/argon2"),
    ("Access control", "Two roles, checked in the menu and on each page",
     "Role/permission table per client, admin screen to manage users, regular access reviews"),
    ("Tenant separation", "Every query goes through one helper that adds tenant_id",
     "Also enforce in the database (row-level security or one database/schema per client), automated tests"),
    ("Personal data (PDPA)", "Masked on screen; unneeded fields not imported",
     "Encrypt or pseudonymise personal fields at rest; consent and purpose recorded per field"),
    ("Encryption", "None (local SQLite file, local web server)",
     "HTTPS (TLS) in transit; encrypted database and backups at rest; managed secrets"),
    ("Audit trail", "Logins, logouts and CSV exports logged",
     "Tamper-proof, retained audit log incl. data views; alerts on unusual exports"),
    ("Retention", "Not handled (12 months of synthetic data)",
     "PDPA retention schedule per data type, automatic deletion/anonymisation, access/correction requests"),
]


def render():
    user = current_user()
    cfg = archetype_config(user["archetype"])

    page_header("Security & PDPA", eyebrow="D4 · Security and data protection",
                subtitle="What this prototype does today (mock level), shown live, and what a production version would need.")

    # ---------------- 1. Role-based access
    st.subheader("1. Role-based access")
    matrix = pd.DataFrame({role.title(): {PAGE_NAMES[p]: "✓" for p in pages} for role, pages in ROLE_PAGES.items()})
    st.dataframe(matrix.reindex(PAGE_NAMES.values()).fillna("—"), width=520)
    st.caption(f"You are signed in as **{user['username']}** ({user['role']}). The menu only lists your pages, "
               "and each page checks the role again, so typing another page's address is refused.")

    # ---------------- 2. Tenant separation
    st.subheader("2. Client (tenant) separation")
    conn = connect()
    companies = conn.execute("SELECT COUNT(*) FROM tenant").fetchone()[0]
    conn.close()
    mine = len(read_table("txn", user["tenant_id"]))
    c1, c2 = st.columns(2)
    c1.metric("Client companies in this database", companies)
    c2.metric(f"Transactions visible to you ({user['tenant_name']})", f"{mine:,}")
    st.markdown("Every read goes through one helper that always adds the client filter:")
    st.code('read_table("txn", tenant_id)\n#  ->  SELECT * FROM txn WHERE tenant_id = :tenant_id', language="python")
    try:
        tenant_query("SELECT COUNT(*) FROM txn", user["tenant_id"])
    except ValueError as blocked:
        st.success(f"Live check: a query without the client filter was refused: “{blocked}”.", icon=":material/shield:")

    # ---------------- 3. PDPA masking
    st.subheader("3. Personal data (PDPA)")
    fields = cfg["personal_fields"]
    st.markdown("Personal fields masked on screen for this client: " +
                "; ".join(f"**{table}**: {', '.join(cols)}" for table, cols in fields.items()))
    example = pd.DataFrame({
        "Field": ["Name", "Phone", "Email"],
        "Stored (made-up example)": ["Jun Hao Tan", "91234567", "jun.tan12@example.com"],
        "Shown on screen": [mask_name("Jun Hao Tan"), mask_phone("91234567"), mask_email("jun.tan12@example.com")],
    })
    st.dataframe(example, hide_index=True, width=620)
    st.caption("Data minimisation: the mapping file decides which source columns are imported at all; "
               "columns not needed for a decision (e.g. a B2B contact person) are simply not loaded.")

    # ---------------- 4. Passwords and audit log
    st.subheader("4. Passwords and audit log")
    users = read_table("app_user", user["tenant_id"])
    users["password_hash"] = users["password_hash"].str[:28] + "…"
    st.dataframe(users[["username", "role", "password_hash"]].rename(columns=str.capitalize),
                 hide_index=True, width=620)
    st.caption("Passwords are stored only as salted PBKDF2 hashes; the password itself is never saved.")
    log = tenant_query("SELECT at, user_id, action, detail FROM audit_log WHERE tenant_id = :tenant_id "
                       "ORDER BY at DESC LIMIT 15", user["tenant_id"])
    log["user_id"] = log["user_id"].str.split(":").str[-1]
    st.markdown("**Latest audit events for your company**")
    st.dataframe(log.rename(columns={"at": "When (UTC)", "user_id": "User", "action": "Action", "detail": "Detail"}),
                 hide_index=True, width="stretch")

    # ---------------- 5. Mock vs production
    st.subheader("5. Mocked today vs needed in production")
    st.dataframe(pd.DataFrame(PRODUCTION_GAPS, columns=["Area", "Prototype (today)", "Production would need"]),
                 hide_index=True, width="stretch")
