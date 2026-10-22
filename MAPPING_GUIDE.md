# Mapping guide: onboarding a new client dataset

Every client exports data in its own format. The mapping layer translates each
export into **one common data model** (`core/schema.sql`), so the dashboards,
KPIs and models never need to know where the data came from.

```
data/raw/<tenant_id>/*.csv  ──►  mapping.yaml  ──►  core/mapping.py  ──►  data/otg.db
   (client's own columns)       (what maps where)   (generic engine)      (common model)
```

**You onboard a client by writing config, not code.**

---

## 1. Steps to onboard a new client

1. **Get the export.** Put the client's CSV files in `data/raw/<tenant_id>/`.
   Use one file per business document type (customers, jobs, invoices...).
2. **Pick or create an archetype.**
   - If the client is like an existing one (e.g. another aircon company), reuse
     `config/archetypes/field_service/`. If their column names differ, copy the
     folder under a new name and edit `mapping.yaml`.
   - For a new industry, create `config/archetypes/<new_archetype>/` with a
     `mapping.yaml` (this guide) and a `kpis.yaml` (KPIs, action rules, map settings).
3. **Register the tenant** in `config/tenants.yaml` (id, name, archetype, demo
   users). Leave out `sample_source`: that is only for the fake demo data.
4. **Run** `python generate_data.py --skip-raw` (this maps the files already in
   `data/raw/` and generates nothing new).
5. **Check** the *Data & onboarding* page, or the `data_quality_log` table, for
   what the cleaning step found. Fix the mapping and run again until it is clean.

---

## 2. The common model: the tables you can map into

| Table | One row per | Key columns you'll usually map |
|---|---|---|
| `site` | outlet / customer site / centre | `site_id`, `name`, `postal_code`, `site_type` |
| `customer` | end customer | `customer_id`, `name`, `phone`, `email`, `segment`, `first_seen` |
| `resource` | worker (technician, staff, rep, tutor) | `resource_id`, `name`, `home_area` or `site_id` |
| `shift` | rostered shift | `shift_id`, `resource_id`, `site_id`, `start_at`, `end_at` |
| `product_service` | menu item / service / SKU | `product_id`, `name`, `category`, `unit_price`, `unit_cost` |
| `txn` | business document | `txn_id`, `type`, `parent_txn_id`, `amount`, `status`, `created_at` ... |
| `line_item` | line on an order or quote | `line_id`, `txn_id`, `product_id`, `qty`, `unit_price` |

`txn.type` is one of: `order`, `job`, `enquiry`, `quotation`, `sales_order`,
`invoice`, `payment`, `booking`. Link documents into chains with
`parent_txn_id` (for example, an invoice's parent is the job it bills). The
"unbilled work" and "unpaid bookings" checks rely on these links.

You never set `tenant_id` yourself. The engine adds it, and puts the tenant in
front of every ID (`J00042` → `tidewell:J00042`).

`site.planning_area`, `lat` and `lon` are also filled in for you, from
`postal_code`.

---

## 3. `mapping.yaml` reference

```yaml
archetype: field_service          # must match the folder name
label: Field service              # shown in the dashboard

personal_fields:                  # optional: what to mask in the UI (PDPA)
  customer: [name, phone, email]  # default if left out
  resource: [name]

tables:                           # one entry per (source file -> target table)
  - source: jobs.csv              # file in data/raw/<tenant_id>/
    target: txn                   # table in the common model
    columns:                      # common column: raw column
      txn_id: job_no
      site_id: site_code
      status: job_status
      created_at: job_date
      start_at: [ShiftDate, ShiftStart]   # a list joins several raw columns
    join_with: " "                # separator for those joins (default: space)
    constants:                    # same value on every row
      type: job
    values:                       # standardise codes (matched in lower case)
      status: {done: completed, "in progress": scheduled}
    defaults:                     # fill blanks
      discount_pct: 0
    text_case:                    # tidy capitalisation: title | upper | lower
      name: title
    date_formats:                 # Python strptime format, if not obvious
      created_at: "%d/%m/%Y %H:%M"

derive:                           # optional, generic derived fields
  inherit_from_parent: [site_id, customer_id]   # copy down job -> invoice -> payment
  paid_at_from_child: {parent_type: invoice, child_type: payment}
  repeat: {type: job, key: [site_id, category], window_days: 30, categories: [Repair]}
```

Notes:
- The **same source file can be listed twice** with different targets. For
  example, a B2B customer master gives us both `customer` and `site` rows.
- If a source has **no single ID column**, build one from several columns:
  `line_id: [QUOTE_NO, LINE]` with `join_with: "-"`.
- **Don't map fields you don't need**, especially personal data. The B2B mapping
  deliberately leaves out `CONTACT_PERSON` (PDPA data minimisation).
- Columns are typed automatically from `schema.sql`: names ending in `_at` or
  `_date` become dates, and `REAL`/`INTEGER` columns become numbers.

---

## 4. What the engine cleans automatically

These steps run for every archetype (`core/cleaning.py`), and each fix is logged:

| Problem | What happens |
|---|---|
| Leading/trailing spaces, empty strings | Trimmed; empty becomes missing |
| Exact duplicate rows (double export) | Removed |
| Two rows with the same ID | First kept |
| Missing ID | Row removed |
| `COMPLETED` / `Completed ` / `done` | Normalised through `values:` |
| `TAMPINES ` vs `Tampines` in area names | Matched to the planning-area list |
| Unreadable numbers or dates | Set to missing |
| Missing document total | Rebuilt from its line items, if it has any |
| Missing line price/cost | Taken from the product list |
| Missing or unknown postal code | Kept, but left off the maps |
| Links to records that don't exist | Logged (orphan line items are removed) |

---

## 5. Worked example: the 4th archetype

`config/archetypes/education/` onboards a tuition centre (centres, tutors,
students, class bookings, fee payments) **with config only**. The README
records how many lines of config and core code that took.
