"""Fake ERP export for "Meridian Supply Co" (B2B distributor of consumables).

Patterns built in:
  * sales rep SP03's discounts creep from ~5% to ~20% over the year
                                                  -> "discounts eroding margin"
  * 4 customers pay later and later, and recent invoices are unpaid
                                                  -> "becoming a credit risk"
  * 15 customers are steadily (but stably) slow payers
  * recent quotations are still open; a few old ones were never closed
                                                  -> "quotations to chase"
Mess built in: company names in random casing, quote status written several
ways, duplicate quote lines, some missing postcodes and quote totals.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from sample_sources.common import (DAYS, END, add_duplicates, area_table, blank_out, email, messy_case,
                                   person_name, postal_code, progress, write)

REPS = {"SP01": 5, "SP02": 6, "SP03": 5, "SP04": 8, "SP05": 4}   # usual discount %
CREEPING_REP = "SP03"
AREA_WEIGHTS = {"Jurong East": 1.5, "Jurong West": 1.3, "Woodlands": 1.3, "Kallang": 1.4, "Bukit Merah": 1.3,
                "Geylang": 1.2, "Downtown Core": 1.0, "Ang Mo Kio": 1.0}   # default 0.6
NAME_WORDS = ["Golden", "Harbour", "Evergreen", "Summit", "Pioneer", "Orchid", "Sunrise", "Bayfront", "Northstar",
              "Jade", "Crescent", "Tembusu", "Silverleaf", "Redhill", "Kingfisher", "Banyan", "Coral", "Peak",
              "Lotus", "Meadow", "Riverside", "Starling", "Willow", "Amber", "Cedar", "Horizon", "Lantern"]
NAME_TYPES = ["Trading", "Foods", "Hospitality", "Facilities", "Catering", "Engineering", "Supplies", "Kitchens"]
GROUPS = ["F&B", "Hospitality", "Facilities", "Retail", "Healthcare"]
# category: (products, min list price, max list price)
CATALOGUE = {
    "Packaging": (["Takeaway Box", "Paper Bag", "Cling Wrap", "Foil Tray", "Carton Box"], 8, 60),
    "Cleaning": (["Floor Cleaner 5L", "Dish Detergent", "Hand Soap", "Trash Bags", "Microfibre Cloth"], 5, 45),
    "Safety": (["Nitrile Gloves", "Face Masks", "Safety Shoes", "First Aid Kit", "Hi-Vis Vest"], 6, 120),
    "Office": (["A4 Paper", "Toner Cartridge", "Ballpoint Pens", "Folders", "Label Roll"], 3, 150),
    "F&B Supplies": (["Paper Cups", "Straws", "Napkins", "Disposable Cutlery", "Sauce Containers"], 4, 40),
}


def generate(out_dir: Path, rng: np.random.Generator):
    customers, behaviour = make_customers(rng)
    items = make_items(rng)
    reps = pd.DataFrame({"SP_CODE": list(REPS), "SP_NAME": [person_name(rng) for _ in REPS]})
    docs = make_documents(customers, behaviour, items, rng)

    # Deliberate data-quality problems
    customers["CUSTNAME"] = messy_case(customers["CUSTNAME"], rng, 0.2)
    customers = blank_out(customers, "POSTCODE", rng, 0.02)
    docs["QUOTE_HDR"]["QUOTE_STATUS"] = messy_case(docs["QUOTE_HDR"]["QUOTE_STATUS"], rng, 0.3)
    docs["QUOTE_HDR"] = blank_out(docs["QUOTE_HDR"], "TOTAL_AMT", rng, 0.01)
    docs["QUOTE_LINE"] = add_duplicates(docs["QUOTE_LINE"], rng, 0.005)

    write(customers, out_dir, "CUSTOMER_MASTER.csv")
    write(items, out_dir, "ITEM_MASTER.csv")
    write(reps, out_dir, "SALESPERSON.csv")
    for name, df in docs.items():
        write(df, out_dir, f"{name}.csv")


def make_customers(rng, n=150):
    areas = area_table().index.to_numpy()
    weights = np.array([AREA_WEIGHTS.get(a, 0.6) for a in areas])
    names = set()
    while len(names) < n:
        names.add(f"{rng.choice(NAME_WORDS)} {rng.choice(NAME_TYPES)} Pte Ltd")
    customers, behaviour = [], []
    for i, name in enumerate(sorted(names)):
        contact = person_name(rng)
        cust_no = f"C{1001 + i}"
        customers.append({
            "CUSTNO": cust_no, "CUSTNAME": name, "CONTACT_PERSON": contact,
            "TEL": f"6{rng.integers(0, 10_000_000):07d}", "EMAIL": email(contact, rng),
            "POSTCODE": postal_code(rng.choice(areas, p=weights / weights.sum()), rng),
            "CREDIT_LIMIT": int(rng.integers(2, 31)) * 5000, "CUST_GROUP": rng.choice(GROUPS),
            "OPEN_DATE": (DAYS[0] - pd.Timedelta(days=int(rng.integers(30, 3000)))).strftime("%Y%m%d"),
            "TERMS_DAYS": int(rng.choice([30, 60], p=[0.7, 0.3])),
        })
        # Hidden behaviour that drives the patterns (not exported)
        behaviour.append({"CUSTNO": cust_no, "rep": rng.choice(list(REPS)), "activity": rng.lognormal(0, 0.7),
                          "affinity": rng.uniform(-0.1, 0.2), "payer": "normal"})
    behaviour = pd.DataFrame(behaviour).set_index("CUSTNO")
    # The 4 worsening payers are reasonably active customers, so it matters
    worsening = behaviour.sort_values("activity", ascending=False).index[1:9:2]
    slow = behaviour.drop(worsening).sample(15, random_state=int(rng.integers(1_000_000))).index
    behaviour.loc[worsening, "payer"] = "worsening"
    behaviour.loc[slow, "payer"] = "slow"
    return pd.DataFrame(customers), behaviour


def make_items(rng) -> pd.DataFrame:
    rows = []
    for category, (products, low, high) in CATALOGUE.items():
        for product in products:
            for size in ["S", "M", "L"]:
                price = round(rng.uniform(low, high), 2)
                rows.append({"ITEMNO": f"IT{len(rows) + 1:04d}", "DESCRIPTION": f"{product} ({size})",
                             "ITEM_CAT": category, "LIST_PRICE": price,
                             "STD_COST": round(price * rng.uniform(0.60, 0.75), 2)})
    return pd.DataFrame(rows)


def rep_discount(rep: str, day: pd.Timestamp) -> float:
    if rep == CREEPING_REP:
        return 5 + 15 * progress(day)
    return REPS[rep]


def payment_date(payer: str, inv_date: pd.Timestamp, due: pd.Timestamp, rng) -> pd.Timestamp | None:
    """When (if ever) this customer pays this invoice."""
    if rng.random() < 0.01:
        return None
    if payer == "worsening":
        if (END - inv_date).days < 120 and rng.random() < 0.8:
            return None
        late = 90 * progress(inv_date) ** 2 + rng.normal(0, 5)
    elif payer == "slow":
        late = rng.uniform(5, 25)
    else:
        late = rng.normal(-3, 6)
    return max(inv_date, due + pd.Timedelta(days=int(late)))


def make_documents(customers, behaviour, items, rng) -> dict[str, pd.DataFrame]:
    terms = customers.set_index("CUSTNO")["TERMS_DAYS"]
    p_customer = (behaviour["activity"] / behaviour["activity"].sum()).to_numpy()
    enquiries, quotes, quote_lines, orders, invoices, receipts = [], [], [], [], [], []

    for day in DAYS[DAYS.dayofweek < 5]:
        for cust in rng.choice(behaviour.index, rng.poisson(15), p=p_customer):
            b = behaviour.loc[cust]
            enq_no = f"E{len(enquiries) + 1:06d}"
            enquiries.append({"ENQ_NO": enq_no, "CUSTNO": cust, "ENQ_DATE": day.strftime("%Y%m%d"), "SP_CODE": b["rep"],
                              "CHANNEL": rng.choice(["Email", "Phone", "WhatsApp", "Walk-in"], p=[0.5, 0.25, 0.2, 0.05])})

            quote_date = day + pd.Timedelta(days=int(rng.integers(0, 4)))
            if rng.random() > 0.9 or quote_date > END:
                continue
            quote_no = f"Q{len(quotes) + 1:06d}"
            disc = float(np.clip(rep_discount(b["rep"], quote_date) + rng.normal(0, 2), 0, 30))
            total = 0.0
            for line, item in enumerate(items.sample(int(rng.integers(2, 8)), random_state=int(rng.integers(1e9))).itertuples(), 1):
                qty = int(rng.choice([10, 20, 50, 100, 200]))
                total += qty * item.LIST_PRICE * (1 - disc / 100)
                quote_lines.append({"QUOTE_NO": quote_no, "LINE": line, "ITEMNO": item.ITEMNO, "QTY": qty,
                                    "UNIT_PRICE": item.LIST_PRICE, "DISC_PCT": round(disc, 1)})

            # Outcome: decided 3-21 days later (if that is still in the future, the quote is open)
            decided = quote_date + pd.Timedelta(days=int(rng.integers(3, 22)))
            if decided > END or rng.random() < 0.04:
                status = "OPEN"
            elif rng.random() < 0.30 + 0.01 * disc + b["affinity"]:
                status = "WON"
            else:
                status = rng.choice(["LOST", "EXPIRED"], p=[0.7, 0.3])
            quotes.append({"QUOTE_NO": quote_no, "ENQ_NO": enq_no, "CUSTNO": cust, "SP_CODE": b["rep"],
                           "QUOTE_DATE": quote_date.strftime("%Y%m%d"),
                           "VALID_UNTIL": (quote_date + pd.Timedelta(days=30)).strftime("%Y%m%d"),
                           "QUOTE_STATUS": status, "TOTAL_AMT": round(total, 2), "DISC_PCT": round(disc, 1)})
            if status != "WON":
                continue

            so_no = f"SO{len(orders) + 1:06d}"
            orders.append({"SO_NO": so_no, "QUOTE_NO": quote_no, "CUSTNO": cust,
                           "SO_DATE": decided.strftime("%Y%m%d"), "SO_AMT": round(total, 2)})
            inv_date = decided + pd.Timedelta(days=int(rng.integers(2, 8)))
            if inv_date > END:
                continue
            inv_no = f"INV{len(invoices) + 1:06d}"
            due = inv_date + pd.Timedelta(days=int(terms[cust]))
            invoices.append({"INV_NO": inv_no, "SO_NO": so_no, "CUSTNO": cust, "INV_DATE": inv_date.strftime("%Y%m%d"),
                             "DUE_DATE": due.strftime("%Y%m%d"), "INV_AMT": round(total, 2)})
            paid = payment_date(b["payer"], inv_date, due, rng)
            if paid is not None and paid <= END:
                receipts.append({"RCPT_NO": f"R{len(receipts) + 1:06d}", "INV_NO": inv_no,
                                 "RCPT_DATE": paid.strftime("%Y%m%d"), "RCPT_AMT": round(total, 2)})

    return {"ENQUIRY": pd.DataFrame(enquiries), "QUOTE_HDR": pd.DataFrame(quotes), "QUOTE_LINE": pd.DataFrame(quote_lines),
            "SO_HDR": pd.DataFrame(orders), "INVOICE": pd.DataFrame(invoices), "RECEIPT": pd.DataFrame(receipts)}
