# Analytic PoC

A rough, clickable prototype of a **reusable analytics layer for SME operations**, built for the
SMU IS483 capstone. It shows one data model and one codebase serving different client industries,
with dashboards for owners and managers.

> **Status: scoping prototype.** Scope is not final. All data is synthetic and generated locally;
> no real company or customer data is used.

## What each deliverable looks like today

| Deliverable | Status | Where to see it |
|---|---|---|
| D2 Common data model | Working prototype | `core/schema.sql`, `config/archetypes/*/mapping.yaml`, [MAPPING_GUIDE.md](MAPPING_GUIDE.md), facts on the *Prototype tour* page |
| D3 Prototype dashboard | Working prototype | *Business overview* (owner), *Action list* (manager), *Location view* (both) |
| D4 Security & PDPA | Working, mock level | *Security & PDPA* page |
| D5 Predictive PoC | Illustrative mock-up | *Forecast & risk* page |
| UAT support, 4th-industry onboarding | Not built yet | |

The demo currently runs two fictional clients: **Tidewell Aircon Services** (field service) and
**Meridian Supply Co** (B2B distribution). An F&B client is also built but switched off in
`config/tenants.yaml`.

## Run it locally

Needs Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

On first start the app generates the demo data (about 20 seconds). To rebuild it yourself:
`python generate_data.py` (fresh fake data) or `python generate_data.py --skip-raw` (re-map the
existing raw files only).

Start Streamlit **from this folder** so it picks up the theme in `.streamlit/config.toml`.

## Demo logins

All passwords are `demo`. The login page also has one-click demo buttons.

| Company | Owner | Manager |
|---|---|---|
| Tidewell Aircon Services (field service) | `fs.owner` | `fs.manager` |
| Meridian Supply Co (B2B) | `b2b.owner` | `b2b.manager` |

Owners see the business overview; managers see the weekly action list. Both see the location,
forecast & risk and security pages. Use the sidebar to move between pages (refreshing the browser
logs you out, because the login is a mock).

## Deploy on Streamlit Community Cloud

1. On [share.streamlit.io](https://share.streamlit.io), choose **Create app**, pick this repo,
   branch `main`, main file `app.py`.
2. Under **Advanced settings**, choose Python **3.12**.
3. After deploy, open **Settings → Sharing** and make the app private / invite your team by email.

The map backgrounds load from CARTO's public tile server (no key needed, no data is sent).

## How it fits together

```
app.py                 login + role-based page menu
generate_data.py       fake raw data -> cleaning + mapping -> SQLite (data/otg.db)
config/
  tenants.yaml         demo clients and users
  planning_areas.csv   Singapore planning areas with approximate centres
  archetypes/<name>/
    mapping.yaml       client's raw columns -> common data model (D2)
    kpis.yaml          KPIs, action rules, map panels, forecast and risk settings
core/                  industry-neutral logic: schema, mapping, cleaning, KPIs, rules,
                       location, forecast, risk, masking, tenant-safe DB access
sample_sources/        the fake "client systems" that produce messy raw exports
views/                 one file per dashboard page, shared by every industry
```

Industry differences live in `config/archetypes/`, not in `if industry == ...` code. See
[MAPPING_GUIDE.md](MAPPING_GUIDE.md) for how a new client dataset is onboarded.
