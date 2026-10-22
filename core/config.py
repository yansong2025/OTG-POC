"""Project paths and config-file loaders.

Everything that differs between client industries lives in config/ as YAML.
This module is the only place that knows where those files are.
"""
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
ARCHETYPE_DIR = CONFIG_DIR / "archetypes"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "otg.db"
EXCEL_PATH = DATA_DIR / "baseline_excel.xlsx"
SCHEMA_PATH = ROOT / "core" / "schema.sql"


def _read_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_tenants() -> list[dict]:
    """List of tenants (with their demo users) from config/tenants.yaml."""
    return _read_yaml(CONFIG_DIR / "tenants.yaml")["tenants"]


def load_mapping(archetype: str) -> dict:
    """The raw-columns -> common-model mapping for one archetype."""
    return _read_yaml(ARCHETYPE_DIR / archetype / "mapping.yaml")


def load_kpi_config(archetype: str) -> dict:
    """KPIs, action rules, map settings and decision tasks for one archetype."""
    path = ARCHETYPE_DIR / archetype / "kpis.yaml"
    return _read_yaml(path) if path.exists() else {}


def load_planning_areas() -> pd.DataFrame:
    """~20 Singapore planning areas with approximate centroids."""
    return pd.read_csv(CONFIG_DIR / "planning_areas.csv", dtype={"postal_sectors": str})
