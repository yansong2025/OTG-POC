"""Singapore location helpers: postal code -> planning area -> lat/lon."""
import zlib

import numpy as np
import pandas as pd

JITTER_DEG = 0.008  # about 900 m, so sites in the same area don't sit on one dot


def sector_lookup(areas: pd.DataFrame) -> dict[str, str]:
    """Map 2-digit postal sector -> planning area, e.g. '52' -> 'Tampines'."""
    lookup = {}
    for _, row in areas.iterrows():
        for sector in row["postal_sectors"].split("|"):
            lookup[sector.zfill(2)] = row["planning_area"]
    return lookup


def stable_jitter(key: str) -> tuple[float, float]:
    """Small random offset that is always the same for the same site."""
    rng = np.random.default_rng(zlib.crc32(key.encode()))
    return tuple(rng.uniform(-JITTER_DEG, JITTER_DEG, size=2))


def locate(sites: pd.DataFrame, areas: pd.DataFrame) -> pd.DataFrame:
    """Fill planning_area, lat and lon for each site from its postal code."""
    sites = sites.copy()
    lookup = sector_lookup(areas)
    postal = sites["postal_code"].astype("string").str.replace(r"\D", "", regex=True).str.zfill(6)
    sites["postal_code"] = postal.where(sites["postal_code"].notna())
    sites["planning_area"] = postal.str[:2].map(lookup)

    centroids = areas.set_index("planning_area")[["lat", "lon"]]
    sites["lat"] = sites["planning_area"].map(centroids["lat"])
    sites["lon"] = sites["planning_area"].map(centroids["lon"])
    offsets = np.array([stable_jitter(str(site_id)) for site_id in sites["site_id"]]).reshape(-1, 2)
    sites["lat"] += offsets[:, 0]
    sites["lon"] += offsets[:, 1]
    return sites


def distance_km(lat1, lon1, lat2, lon2):
    """Straight-line distance (haversine), good enough for Singapore."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))
