"""Fake job-management export for "Tidewell Aircon Services" (field service).

Patterns built in:
  * hot months (Mar-Jun) are busier; Sundays are quiet
  * demand in the West grows ~80% over the year, but only 1 of 12 technicians
    is based there                                   -> "area needs more capacity"
  * Tampines sites get many follow-up visits, worse when TECH02 did the job
                                                     -> "repeat-job hotspot"
  * ~4% of completed jobs are never invoiced         -> "unbilled work"
Mess built in: technician base areas in random casing, job status written
several ways, duplicate job rows, some missing postal codes and job values.
"""
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from core.geo import distance_km
from sample_sources.common import (DAYS, END, add_duplicates, area_table, blank_out, email, messy_case,
                                   mobile, person_name, postal_code, progress, write)

TECH_BASES = ["Tampines", "Tampines", "Bedok", "Bedok", "Pasir Ris", "Ang Mo Kio", "Ang Mo Kio",
              "Hougang", "Sengkang", "Toa Payoh", "Bishan", "Jurong East"]
HOTSPOT_AREA = "Tampines"
CARELESS_TECH = "TECH02"
# Relative number of customer sites per area (default 0.8)
SITE_WEIGHTS = {"Jurong West": 1.6, "Choa Chu Kang": 1.3, "Bukit Batok": 1.2, "Clementi": 1.0, "Jurong East": 1.1,
                "Tampines": 1.4, "Bedok": 1.2, "Downtown Core": 0.2}
# job type: (share of jobs, min value, max value)
JOB_TYPES = {"Servicing": (0.55, 60, 120), "Repair": (0.25, 150, 500),
             "Gas top-up": (0.12, 80, 150), "Installation": (0.08, 800, 2500)}


def generate(out_dir: Path, rng: np.random.Generator):
    areas = area_table()
    technicians = pd.DataFrame({
        "tech_code": [f"TECH{i:02d}" for i in range(1, 13)],
        "tech_name": [person_name(rng) for _ in range(12)],
        "base_area": TECH_BASES,
        "skill": rng.choice(["General", "Senior", "Installer"], 12, p=[0.6, 0.25, 0.15]),
    })
    customers, sites = make_customers_and_sites(areas, rng)
    jobs = make_jobs(sites, technicians, areas, rng)
    invoices, payments = make_billing(jobs, customers, rng)

    # Deliberate data-quality problems
    technicians["base_area"] = messy_case(technicians["base_area"], rng, 0.5)
    customers["cust_type"] = customers["cust_type"].map(
        lambda t: rng.choice(["Contract", "CONTRACT"]) if t == "Contract" else rng.choice(["Adhoc", "ADHOC", "Ad-hoc"]))
    sites = blank_out(sites, "address_postal", rng, 0.01)
    jobs["job_status"] = jobs["job_status"].map(
        lambda s: rng.choice(["Completed", "COMPLETED", "completed", "Done"], p=[0.7, 0.1, 0.1, 0.1]) if s == "Completed" else s)
    jobs = blank_out(jobs, "job_value", rng, 0.003)
    jobs = add_duplicates(jobs, rng, 0.005)
    payments = add_duplicates(payments, rng, 0.003)

    write(technicians, out_dir, "technicians.csv")
    write(customers, out_dir, "customers.csv")
    write(sites.drop(columns=["area", "weight"]), out_dir, "sites.csv")   # drop our helper columns
    write(jobs, out_dir, "jobs.csv")
    write(invoices, out_dir, "invoices.csv")
    write(payments, out_dir, "payments.csv")


def make_customers_and_sites(areas: pd.DataFrame, rng, n=3000):
    area_names = areas.index.to_numpy()
    weights = np.array([SITE_WEIGHTS.get(a, 0.8) for a in area_names])
    customers, sites = [], []
    for i in range(1, n + 1):
        contract = rng.random() < 0.15
        name = person_name(rng)
        cust_id = f"C{i:04d}"
        customers.append({"cust_id": cust_id, "cust_name": name, "contact_no": mobile(rng), "email_addr": email(name, rng),
                          "cust_type": "Contract" if contract else "Adhoc",
                          "since": (DAYS[0] - pd.Timedelta(days=int(rng.integers(-300, 1500)))).strftime("%Y-%m-%d")})
        home_area = rng.choice(area_names, p=weights / weights.sum())
        for _ in range(rng.integers(2, 5) if contract else 1):
            sites.append({"site_code": f"S{len(sites) + 1:05d}", "cust_id": cust_id,
                          "site_label": "Commercial unit" if contract else "Residential unit",
                          "address_postal": postal_code(home_area, rng), "area": home_area,
                          "weight": 3.0 if contract else 1.0})
    return pd.DataFrame(customers), pd.DataFrame(sites)


def make_jobs(sites: pd.DataFrame, technicians: pd.DataFrame, areas: pd.DataFrame, rng) -> pd.DataFrame:
    # Each area's 3 nearest technicians (by base area), used to assign jobs
    nearest = {}
    for area, row in areas.iterrows():
        dist = [distance_km(row.lat, row.lon, areas.at[b, "lat"], areas.at[b, "lon"]) for b in technicians["base_area"]]
        nearest[area] = technicians["tech_code"].to_numpy()[np.argsort(dist)[:3]]

    is_west = sites["area"].map(areas["region"]).eq("West").to_numpy()
    job_types = list(JOB_TYPES)
    type_share = [v[0] for v in JOB_TYPES.values()]

    jobs, follow_ups = [], defaultdict(list)   # follow_ups[day] = [(site row, job type), ...]
    for day in DAYS:
        season = 1.25 if day.month in (3, 4, 5, 6) else 1.0
        weekday = [1.1, 1.1, 1.1, 1.1, 1.1, 0.8, 0.3][day.dayofweek]
        weights = sites["weight"].to_numpy() * np.where(is_west, 1 + 0.8 * progress(day), 1.0)
        n = rng.poisson(24 * season * weekday)
        todays = [(s, rng.choice(job_types, p=type_share))
                  for s in rng.choice(len(sites), n, p=weights / weights.sum())]
        todays += follow_ups.pop(day, [])

        for s, job_type in todays:
            site = sites.iloc[s]
            tech = rng.choice(nearest[site["area"]], p=[0.6, 0.25, 0.15])
            _, low, high = JOB_TYPES[job_type]
            if day > END - pd.Timedelta(days=2):
                status = "Scheduled"
            else:
                status = "Cancelled" if rng.random() < 0.03 else "Completed"
            jobs.append({"job_no": f"J{len(jobs) + 1:06d}", "site_code": site["site_code"], "cust_id": site["cust_id"],
                         "tech_code": tech, "job_type": job_type, "job_status": status,
                         "job_date": day.strftime("%Y-%m-%d"),
                         "completed_on": day.strftime("%Y-%m-%d") if status == "Completed" else "",
                         "job_value": round(rng.uniform(low, high), 0)})

            # Did the fix hold? If not, the customer calls back within a few weeks.
            if job_type in ("Repair", "Gas top-up") and status == "Completed":
                p_repeat = 0.45 if site["area"] == HOTSPOT_AREA else 0.04
                if tech == CARELESS_TECH:
                    p_repeat += 0.15
                if rng.random() < p_repeat:
                    follow_ups[day + pd.Timedelta(days=int(rng.integers(5, 26)))].append((s, job_type))
    return pd.DataFrame(jobs)


def make_billing(jobs: pd.DataFrame, customers: pd.DataFrame, rng):
    contract = set(customers.loc[customers["cust_type"] == "Contract", "cust_id"])
    invoices, payments = [], []
    for job in jobs[jobs["job_status"] == "Completed"].itertuples():
        done = pd.Timestamp(job.completed_on)
        recent = (END - done).days < 21
        if rng.random() < (0.08 if recent else 0.04):
            continue                                          # forgotten: never invoiced
        inv_date = done + pd.Timedelta(days=int(rng.integers(0, 4)))
        if inv_date > END:
            continue
        inv_no = f"INV{len(invoices) + 1:06d}"
        invoices.append({"inv_no": inv_no, "job_no": job.job_no, "inv_date": inv_date.strftime("%Y-%m-%d"),
                         "inv_amount": job.job_value, "due_on": (inv_date + pd.Timedelta(days=30)).strftime("%Y-%m-%d")})

        if rng.random() < 0.02:
            continue                                          # never paid
        if job.cust_id in contract:
            delay = int(rng.integers(20, 61))
        else:
            delay = 0 if rng.random() < 0.65 else int(rng.integers(7, 51))
        paid = inv_date + pd.Timedelta(days=delay)
        if paid <= END:
            payments.append({"pay_ref": f"PAY{len(payments) + 1:06d}", "inv_no": inv_no,
                             "paid_date": paid.strftime("%Y-%m-%d"), "paid_amt": job.job_value})
    return pd.DataFrame(invoices), pd.DataFrame(payments)
