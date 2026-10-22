-- =====================================================================
-- D2 Common data model
-- One schema for every client archetype (F&B, field service, B2B, ...).
--
-- Rules:
--   * Every table carries tenant_id (planning_area is the only exception:
--     it is shared public reference data, not client data).
--   * IDs are text and always prefixed with the tenant, e.g. "tidewell:J00042",
--     so records from two clients can never collide.
--   * Dates are ISO text "YYYY-MM-DD HH:MM:SS".
--   * Columns that only apply to some archetypes are nullable.
-- =====================================================================

-- Reference data: Singapore planning areas (shared, read-only)
CREATE TABLE planning_area (
    planning_area   TEXT PRIMARY KEY,   -- e.g. "Tampines"
    region          TEXT,               -- North / East / West / Central / North-East
    lat             REAL,               -- approximate centroid
    lon             REAL,
    postal_sectors  TEXT                -- first 2 digits of postal codes, "|"-separated
);

-- A client of OTG Lab, and which archetype config it uses
CREATE TABLE tenant (
    tenant_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    archetype   TEXT NOT NULL           -- matches a folder in config/archetypes/
);

-- Dashboard users (mock login; see SECURITY_NOTES.md)
CREATE TABLE app_user (
    user_id        TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenant(tenant_id),
    username       TEXT NOT NULL UNIQUE,
    role           TEXT NOT NULL,       -- owner | manager
    display_name   TEXT,
    password_hash  TEXT                 -- salted PBKDF2, never plain text
);

-- Any physical location: an outlet, a customer's site, a learning centre...
CREATE TABLE site (
    site_id        TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenant(tenant_id),
    name           TEXT,
    site_type      TEXT,                -- outlet | customer_site | centre
    customer_id    TEXT,                -- set when the site belongs to a customer
    postal_code    TEXT,
    planning_area  TEXT,                -- derived from postal_code
    lat            REAL,                -- derived from planning_area (+ small jitter)
    lon            REAL
);

-- End customers of our client (members, households, companies, students...)
-- name / phone / email are personal data: masked in the UI (core/masking.py)
CREATE TABLE customer (
    customer_id   TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenant(tenant_id),
    name          TEXT,
    phone         TEXT,
    email         TEXT,
    segment       TEXT,                 -- e.g. member tier, contract / ad-hoc, customer group
    first_seen    TEXT,
    credit_limit  REAL                  -- B2B only
);

-- People who do the work: technicians, outlet staff, sales reps, tutors
CREATE TABLE resource (
    resource_id    TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenant(tenant_id),
    resource_type  TEXT,                -- technician | staff | sales_rep | tutor
    name           TEXT,
    site_id        TEXT,                -- home outlet / centre, if any
    home_area      TEXT,                -- planning area they are based in, if any
    skill          TEXT
);

-- Rosters: who is working where and when
CREATE TABLE shift (
    shift_id     TEXT PRIMARY KEY,
    tenant_id    TEXT NOT NULL REFERENCES tenant(tenant_id),
    site_id      TEXT,
    resource_id  TEXT,
    start_at     TEXT,
    end_at       TEXT
);

-- What the client sells: menu items, services, SKUs, classes
CREATE TABLE product_service (
    product_id  TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL REFERENCES tenant(tenant_id),
    name        TEXT,
    category    TEXT,
    unit_price  REAL,
    unit_cost   REAL
);

-- The core table ("Transaction" in the design; named txn because
-- TRANSACTION is an SQL keyword).
-- Business documents form chains through parent_txn_id:
--   field service : job -> invoice -> payment
--   B2B           : enquiry -> quotation -> sales_order -> invoice -> payment
--   F&B           : order (stand-alone, with line items)
CREATE TABLE txn (
    txn_id         TEXT PRIMARY KEY,
    tenant_id      TEXT NOT NULL REFERENCES tenant(tenant_id),
    type           TEXT NOT NULL,       -- order | job | enquiry | quotation | sales_order | invoice | payment | booking
    parent_txn_id  TEXT,                -- the document this one follows from
    source_ref     TEXT,                -- original document number in the client's system
    site_id        TEXT,
    customer_id    TEXT,
    resource_id    TEXT,                -- technician / cashier / sales rep / tutor
    product_id     TEXT,                -- for single-item documents (e.g. a class booking)
    category       TEXT,                -- job type, channel, etc.
    amount         REAL,
    status         TEXT,                -- normalised: open | scheduled | completed | cancelled | won | lost | ...
    created_at     TEXT,
    completed_at   TEXT,
    due_date       TEXT,                -- invoices, quotation validity
    paid_at        TEXT,                -- filled from the linked payment
    discount_pct   REAL,
    promo_code     TEXT,
    is_repeat      INTEGER DEFAULT 0,   -- derived by the mapping layer (see mapping.yaml "derive")
    extra_json     TEXT                 -- anything archetype-specific that has no column
);

CREATE TABLE line_item (
    line_id       TEXT PRIMARY KEY,
    tenant_id     TEXT NOT NULL REFERENCES tenant(tenant_id),
    txn_id        TEXT NOT NULL,
    product_id    TEXT,
    qty           REAL,
    unit_price    REAL,
    unit_cost     REAL,
    discount_pct  REAL,
    line_amount   REAL                  -- qty * unit_price * (1 - discount_pct/100)
);

-- KPI definitions are loaded from config/archetypes/<archetype>/kpis.yaml,
-- one copy per tenant so each client can have its own targets.
CREATE TABLE kpi_definition (
    tenant_id   TEXT NOT NULL REFERENCES tenant(tenant_id),
    kpi_id      TEXT NOT NULL,
    archetype   TEXT,
    name        TEXT,
    formula     TEXT,                   -- the calculation spec from kpis.yaml, as JSON
    unit        TEXT,
    direction   TEXT,                   -- up = higher is better, down = lower is better
    target      REAL,                   -- monthly target
    amber_pct   REAL,                   -- how far from target still counts as amber
    PRIMARY KEY (tenant_id, kpi_id)
);

-- Pre-computed KPI values per week and month (for trends and comparisons)
CREATE TABLE kpi_snapshot (
    tenant_id     TEXT NOT NULL REFERENCES tenant(tenant_id),
    kpi_id        TEXT NOT NULL,
    grain         TEXT NOT NULL,        -- week | month
    period_start  TEXT NOT NULL,
    value         REAL,
    PRIMARY KEY (tenant_id, kpi_id, grain, period_start)
);

-- What the cleaning step found and fixed (shown on the Data & onboarding page)
CREATE TABLE data_quality_log (
    tenant_id      TEXT NOT NULL,
    source_file    TEXT,
    issue          TEXT,
    rows_affected  INTEGER,
    action         TEXT
);

-- Mock audit trail: logins and data exports
CREATE TABLE audit_log (
    tenant_id  TEXT NOT NULL,
    user_id    TEXT,
    action     TEXT,
    detail     TEXT,
    at         TEXT
);

CREATE INDEX idx_txn_tenant_type ON txn (tenant_id, type, created_at);
CREATE INDEX idx_txn_parent      ON txn (tenant_id, parent_txn_id);
CREATE INDEX idx_line_txn        ON line_item (tenant_id, txn_id);
CREATE INDEX idx_shift_site      ON shift (tenant_id, site_id, start_at);
