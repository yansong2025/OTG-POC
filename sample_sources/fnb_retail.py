"""Fake POS export for "Sunbird Kitchens" (F&B, 6 outlets).

Patterns built in (so the dashboard has something to find):
  * lunch (12-2pm) and dinner (6-8pm) peaks; the CBD outlet is quiet on weekends
  * Woodlands declines over the last 10 weeks            -> "outlet needs attention"
  * Punggol grows steadily (new estate)
  * promo BUNDLE25 discounts low-margin items             -> "promo not worth it"
  * Tampines and Raffles Place have no mid-shift on weekdays -> "understaffed at lunch"
Mess built in: inconsistent status/channel/tier casing, duplicate receipts and
lines, some missing receipt totals and member phone numbers.
"""
from pathlib import Path

import numpy as np
import pandas as pd

from sample_sources.common import (DAYS, END, add_duplicates, blank_out, email, messy_case,
                                   mobile, person_name, postal_code, progress, write)

# code, name, planning area, average receipts per weekday, weekend factor
OUTLETS = [
    ("OUT01", "Sunbird Tampines Hub", "Tampines", 70, 1.15),
    ("OUT02", "Sunbird Jurong West", "Jurong West", 62, 1.15),
    ("OUT03", "Sunbird Woodlands", "Woodlands", 60, 1.10),
    ("OUT04", "Sunbird Bishan", "Bishan", 55, 1.20),
    ("OUT05", "Sunbird Raffles Place", "Downtown Core", 78, 0.45),
    ("OUT06", "Sunbird Punggol", "Punggol", 45, 1.25),
]
UNDERSTAFFED = {"OUT01", "OUT05"}   # no weekday lunch mid-shift
DECLINING = "OUT03"                 # Woodlands
GROWING = "OUT06"                   # Punggol

# code, name, category, price, food cost, popularity
MENU = [
    ("M01", "Chicken Rice", "Mains", 5.5, 2.0, 10), ("M02", "Nasi Lemak", "Mains", 6.0, 2.2, 8),
    ("M03", "Laksa", "Mains", 6.5, 2.6, 6), ("M04", "Fried Rice", "Mains", 6.0, 2.0, 7),
    ("M05", "Fish Curry Set", "Mains", 8.5, 3.6, 4), ("M06", "Beef Hor Fun", "Mains", 7.5, 3.3, 4),
    ("M07", "Mee Goreng", "Mains", 5.8, 2.0, 5), ("M08", "Chicken Chop", "Mains", 9.5, 4.2, 3),
    ("S01", "Spring Rolls", "Sides", 3.5, 1.0, 4), ("S02", "Otah", "Sides", 3.0, 1.4, 3),
    ("S03", "Fried Wings", "Sides", 4.5, 1.8, 5),
    ("D01", "Kopi", "Drinks", 1.8, 0.4, 10), ("D02", "Teh", "Drinks", 1.8, 0.4, 9),
    ("D03", "Iced Lemon Tea", "Drinks", 2.5, 0.6, 7), ("D04", "Bandung", "Drinks", 2.5, 0.7, 3),
    ("D05", "Fresh Juice", "Drinks", 4.0, 1.9, 4), ("D06", "Bubble Tea", "Drinks", 4.5, 1.6, 5),
    ("E01", "Chendol", "Desserts", 3.5, 1.3, 4), ("E02", "Ice Kacang", "Desserts", 4.0, 1.5, 3),
    ("E03", "Pulut Hitam", "Desserts", 3.2, 1.2, 2), ("E04", "Durian Pengat", "Desserts", 6.5, 4.4, 1),
]
HOURS = np.arange(8, 22)
HOUR_WEIGHTS = np.array([3, 4, 4, 9, 16, 12, 5, 4, 4, 6, 12, 12, 7, 3], dtype=float)
CBD_HOUR_WEIGHTS = np.array([6, 5, 3, 10, 24, 16, 5, 3, 3, 5, 8, 6, 4, 2], dtype=float)

# start, end, staff on that shift
SHIFTS = [("07:30", "15:30", 3), ("11:00", "15:00", 2), ("14:30", "22:30", 3)]


def generate(out_dir: Path, rng: np.random.Generator):
    menu = pd.DataFrame(MENU, columns=["ItemCode", "ItemName", "Category", "Price", "FoodCost", "Popularity"])
    outlets = pd.DataFrame([(c, n, postal_code(a, rng)) for c, n, a, _, _ in OUTLETS],
                           columns=["OutletCode", "OutletName", "Postal"])
    members = make_members(rng)
    staff = make_staff(rng)
    roster = make_roster(staff, rng)
    receipts, lines = make_sales(menu, members, staff, rng)

    # Deliberate data-quality problems
    members["Tier"] = messy_case(members["Tier"], rng, 0.15)
    members = blank_out(members, "Mobile", rng, 0.02)
    receipts["Status"] = messy_case(receipts["Status"], rng, 0.2)
    receipts["Channel"] = messy_case(receipts["Channel"], rng, 0.1)
    receipts = blank_out(receipts, "ReceiptTotal", rng, 0.003)
    receipts = add_duplicates(receipts, rng, 0.004)
    lines = add_duplicates(lines, rng, 0.002)

    write(outlets, out_dir, "outlets.csv")
    write(menu.drop(columns="Popularity"), out_dir, "menu.csv")
    write(members, out_dir, "members.csv")
    write(staff, out_dir, "staff.csv")
    write(roster, out_dir, "roster.csv")
    write(receipts, out_dir, "pos_receipts.csv")
    write(lines, out_dir, "pos_receipt_lines.csv")


def make_members(rng, n=3000) -> pd.DataFrame:
    # 85% joined before our data starts, the rest during the year
    join = np.where(rng.random(n) < 0.85,
                    DAYS[0] - pd.to_timedelta(rng.integers(1, 2000, n), unit="D"),
                    DAYS[0] + pd.to_timedelta(rng.integers(0, len(DAYS), n), unit="D"))
    rows = []
    for i, joined in enumerate(sorted(join)):
        name = person_name(rng)
        rows.append({
            "MemberNo": f"MB{10001 + i}",
            "MemberName": name,
            "Mobile": mobile(rng),
            "Email": email(name, rng),
            "Tier": rng.choice(["Basic", "Silver", "Gold"], p=[0.7, 0.22, 0.08]),
            "JoinDate": pd.Timestamp(joined).strftime("%d/%m/%Y"),
        })
    return pd.DataFrame(rows)


def make_staff(rng) -> pd.DataFrame:
    rows = []
    for o, (code, *_rest) in enumerate(OUTLETS, start=1):
        for s in range(9):
            rows.append({"StaffNo": f"ST{o}{s + 1:02d}", "StaffName": person_name(rng),
                         "HomeOutlet": code, "Role": "Outlet manager" if s == 0 else "Crew"})
    return pd.DataFrame(rows)


def make_roster(staff: pd.DataFrame, rng) -> pd.DataFrame:
    rows = []
    for code, *_rest in OUTLETS:
        pool = staff.loc[staff["HomeOutlet"] == code, "StaffNo"].to_numpy()
        for day in DAYS:
            weekday = day.dayofweek < 5
            on_duty = iter(rng.permutation(pool))
            for start, end, needed in SHIFTS:
                if start == "11:00" and weekday and code in UNDERSTAFFED:
                    needed = 0  # the gap the dashboard should spot
                for _ in range(needed):
                    rows.append({"StaffNo": next(on_duty), "OutletCode": code, "ShiftDate": day.strftime("%d/%m/%Y"),
                                 "ShiftStart": start, "ShiftEnd": end})
    roster = pd.DataFrame(rows)
    roster.insert(0, "RosterId", [f"RS{i:06d}" for i in range(1, len(roster) + 1)])
    return roster


def daily_factor(code: str, day: pd.Timestamp, weekend_factor: float) -> float:
    factor = weekend_factor if day.dayofweek >= 5 else 1.0
    if day.month == 12 or pd.Timestamp("2026-02-14") <= day <= pd.Timestamp("2026-02-22"):
        factor *= 1.15                                   # December and Chinese New Year
    if code == GROWING:
        factor *= 1 + 0.4 * progress(day)
    if code == DECLINING:
        days_left = (END - day).days
        if days_left < 70:
            factor *= 1 - 0.4 * (70 - days_left) / 70   # down to 60% in the last 10 weeks
    return factor


def make_sales(menu, members, staff, rng):
    # Work with plain arrays of menu row numbers: much faster than pandas inside the loop
    code_of, category_of, price_of = menu["ItemCode"].to_numpy(), menu["Category"].to_numpy(), menu["Price"].to_numpy()
    mains = np.flatnonzero(category_of == "Mains")
    extras = np.flatnonzero(category_of != "Mains")
    bundle_items = np.flatnonzero(menu["ItemCode"].isin(["D05", "D06", "E04", "E02"]))
    popularity = menu["Popularity"].to_numpy(dtype=float)
    p_main = popularity[mains] / popularity[mains].sum()
    p_extra = popularity[extras] / popularity[extras].sum()
    member_join = pd.to_datetime(members["JoinDate"], format="%d/%m/%Y").to_numpy()

    receipts, lines = [], []
    for code, _name, _area, base, weekend_factor in OUTLETS:
        cashiers = staff.loc[staff["HomeOutlet"] == code, "StaffNo"].to_numpy()
        weights = CBD_HOUR_WEIGHTS if code == "OUT05" else HOUR_WEIGHTS
        for day in DAYS:
            n = rng.poisson(base * daily_factor(code, day, weekend_factor))
            hours = rng.choice(HOURS, n, p=weights / weights.sum())
            for hour in sorted(hours):
                when = day + pd.Timedelta(hours=int(hour), minutes=int(rng.integers(0, 60)))
                receipt_no = f"{code[-2:]}{len(receipts) + 1:07d}"

                # Basket: usually one main plus a few extras (smaller baskets at Woodlands)
                basket = []
                if rng.random() < 0.85:
                    basket.append(rng.choice(mains, p=p_main))
                basket += list(rng.choice(extras, rng.poisson(0.6 if code == DECLINING else 0.9), p=p_extra))

                # Loyalty member (only members who had joined by then; earlier members visit more)
                member = ""
                if rng.random() < 0.3:
                    eligible = np.searchsorted(member_join, np.datetime64(day), side="right")
                    if eligible:
                        member = members["MemberNo"].iat[int(eligible * rng.random() ** 2)]

                promo, disc = "", {}
                if day >= pd.Timestamp("2026-03-01") and rng.random() < 0.10:
                    promo = "BUNDLE25"   # adds two low-margin items, 25% off them
                    for item in rng.choice(bundle_items, 2, replace=False):
                        basket.append(item)
                        disc[len(basket) - 1] = 25
                elif day.dayofweek < 5 and 11 <= hour <= 13 and rng.random() < 0.18:
                    promo = "LUNCH10"    # 10% off mains at weekday lunch
                    disc = {i: 10 for i, item in enumerate(basket) if category_of[item] == "Mains"}
                elif member and rng.random() < 0.25:
                    promo = "MEMBER5"
                    disc = {i: 5 for i in range(len(basket))}
                if not basket:
                    basket.append(rng.choice(extras, p=p_extra))

                total = 0.0
                for i, item in enumerate(basket):
                    qty = 2 if rng.random() < 0.08 else 1
                    pct = disc.get(i, 0)
                    total += qty * price_of[item] * (1 - pct / 100)
                    lines.append({"LineId": f"{receipt_no}-{i + 1}", "ReceiptNo": receipt_no, "ItemCode": code_of[item],
                                  "Qty": qty, "UnitPrice": price_of[item], "LineDiscPct": pct or ""})

                receipts.append({
                    "ReceiptNo": receipt_no, "OutletCode": code, "MemberNo": member,
                    "CashierNo": rng.choice(cashiers), "TxnDateTime": when.strftime("%d/%m/%Y %H:%M"),
                    "Channel": rng.choice(["Dine-In", "Takeaway", "Delivery"], p=[0.6, 0.3, 0.1]),
                    "PromoCode": promo, "ReceiptTotal": round(total, 2),
                    "Status": "VOID" if rng.random() < 0.015 else "PAID",
                })
    return pd.DataFrame(receipts), pd.DataFrame(lines)
