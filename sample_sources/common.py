"""Shared helpers for the fake client systems.

Everything here is invented. Names are random combinations, emails use the
reserved example.com domain, phone numbers are random.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from core.config import load_planning_areas

# 52 weeks of data, Monday 20 Oct 2025 to Sunday 18 Oct 2026
START = pd.Timestamp("2025-10-20")
END = pd.Timestamp("2026-10-18")
DAYS = pd.date_range(START, END, freq="D")

FIRST_NAMES = ["Wei Ling", "Jun Hao", "Siti", "Arjun", "Mei Xin", "Hafiz", "Priya", "Kai Wen", "Nurul",
               "Ravi", "Hui Min", "Zhi Hao", "Aisyah", "Daniel", "Rachel", "Ming", "Farah", "Kumar",
               "Jasmine", "Bryan", "Shu Fen", "Imran", "Grace", "Vikram", "Li Ting", "Marcus"]
LAST_NAMES = ["Tan", "Lim", "Lee", "Ng", "Wong", "Goh", "Chua", "Teo", "Ong", "Koh", "Rahman", "Ismail",
              "Kumar", "Pillai", "Singh", "Yeo", "Chan", "Low", "Ho", "Sim"]


def person_name(rng) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def mobile(rng) -> str:
    return f"{rng.choice([8, 9])}{rng.integers(0, 10_000_000):07d}"


def email(name: str, rng) -> str:
    return f"{name.lower().replace(' ', '.')}{rng.integers(1, 99)}@example.com"


@lru_cache
def area_table() -> pd.DataFrame:
    return load_planning_areas().set_index("planning_area")


def postal_code(area: str, rng) -> str:
    """A made-up 6-digit postal code whose sector belongs to the given planning area."""
    sectors = area_table().loc[area, "postal_sectors"].split("|")
    return f"{rng.choice(sectors).zfill(2)}{rng.integers(0, 10_000):04d}"


def progress(day: pd.Timestamp) -> float:
    """0.0 at the start of the year of data, 1.0 at the end (for trends)."""
    return (day - START).days / (END - START).days


# ---------------------------------------------------------------- deliberate mess

def messy_case(values: pd.Series, rng, frac: float = 0.1) -> pd.Series:
    """Randomly UPPER / lower / add trailing spaces to a share of the values."""
    values = values.astype(str).copy()
    picks = rng.random(len(values)) < frac
    styles = rng.integers(0, 3, len(values))
    for i in np.flatnonzero(picks):
        v = values.iat[i]
        values.iat[i] = [v.upper(), v.lower(), v + "  "][styles[i]]
    return values


def add_duplicates(df: pd.DataFrame, rng, frac: float) -> pd.DataFrame:
    """Append exact copies of a share of rows (like a double export)."""
    dupes = df.sample(frac=frac, random_state=int(rng.integers(1_000_000)))
    return pd.concat([df, dupes]).sort_index(kind="stable").reset_index(drop=True)


def blank_out(df: pd.DataFrame, column: str, rng, frac: float) -> pd.DataFrame:
    """Empty a share of cells in one column."""
    df = df.copy()
    df[column] = df[column].astype(object)
    df.loc[rng.random(len(df)) < frac, column] = ""
    return df


def write(df: pd.DataFrame, out_dir: Path, filename: str):
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / filename, index=False)
