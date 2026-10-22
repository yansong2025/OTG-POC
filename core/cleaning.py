"""Generic data-cleaning steps, used by the mapping layer for every archetype.

Each function fixes one kind of problem and writes what it did to a
QualityLog, so the dashboard can show exactly what was cleaned.
"""
import pandas as pd


class QualityLog:
    """Collects data-quality findings: one row per (file, issue)."""

    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.rows = []

    def add(self, source_file: str, issue: str, rows_affected: int, action: str):
        if rows_affected > 0:
            self.rows.append({
                "tenant_id": self.tenant_id,
                "source_file": source_file,
                "issue": issue,
                "rows_affected": int(rows_affected),
                "action": action,
            })

    def to_frame(self) -> pd.DataFrame:
        # drop_duplicates: a file mapped into two tables would otherwise be reported twice
        return pd.DataFrame(self.rows, columns=["tenant_id", "source_file", "issue", "rows_affected", "action"]).drop_duplicates()


def strip_text(df: pd.DataFrame) -> pd.DataFrame:
    """Trim spaces in every cell and turn empty strings into missing values.

    (Raw files are always read as text, so every column is a text column here.)
    """
    df = df.copy()
    for col in df.columns:
        df[col] = df[col].str.strip().replace("", pd.NA)
    return df


def drop_exact_duplicates(df: pd.DataFrame, log: QualityLog, source: str) -> pd.DataFrame:
    """Remove rows that are identical in every column (e.g. a double export)."""
    before = len(df)
    df = df.drop_duplicates()
    log.add(source, "exact duplicate rows", before - len(df), "removed")
    return df


def drop_duplicate_ids(df: pd.DataFrame, id_col: str, log: QualityLog, source: str) -> pd.DataFrame:
    """Keep only the first row for each ID."""
    dupes = df[id_col].duplicated(keep="first")
    log.add(source, f"duplicate {id_col}", dupes.sum(), "kept first occurrence")
    return df[~dupes]


def drop_missing(df: pd.DataFrame, col: str, log: QualityLog, source: str) -> pd.DataFrame:
    """Drop rows where a required field (usually the ID) is empty."""
    missing = df[col].isna()
    log.add(source, f"missing {col}", missing.sum(), "row removed")
    return df[~missing]


def normalise_values(series: pd.Series, value_map: dict, log: QualityLog, source: str, col: str) -> pd.Series:
    """Fix inconsistent casing/spelling, e.g. 'COMPLETED', 'Completed ', 'done' -> 'completed'.

    Values are lower-cased first, then looked up in value_map.
    Values not in the map are kept (lower-cased).
    """
    lowered = series.str.strip().str.lower()
    cleaned = lowered.map(value_map).fillna(lowered)
    # "Inconsistent" = not written the way most rows write that same code
    usual_spelling = series.groupby(cleaned).agg(lambda s: s.mode().iat[0])
    inconsistent = series.notna() & (series != cleaned.map(usual_spelling))
    log.add(source, f"inconsistent spelling/casing of {col}", inconsistent.sum(), "normalised to standard codes")
    return cleaned


def to_number(series: pd.Series, log: QualityLog, source: str, col: str) -> pd.Series:
    """Parse numbers; anything unreadable becomes missing (and is logged)."""
    cleaned = pd.to_numeric(series.astype(str).str.replace(",", "").str.replace("$", ""), errors="coerce")
    log.add(source, f"unreadable number in {col}", (series.notna() & cleaned.isna()).sum(), "set to missing")
    log.add(source, f"missing {col}", series.isna().sum(), "left missing (filled later if possible)")
    return cleaned


def to_datetime(series: pd.Series, fmt: str | None, log: QualityLog, source: str, col: str) -> pd.Series:
    """Parse dates with the format given in mapping.yaml (or let pandas infer it)."""
    if fmt:
        parsed = pd.to_datetime(series, format=fmt, errors="coerce")
    else:
        # No format given: expect ISO dates (2026-10-18). Other formats must be set in mapping.yaml,
        # because guessing would read 05/03 as either 5 March or 3 May.
        parsed = pd.to_datetime(series, format="ISO8601", errors="coerce")
    log.add(source, f"unreadable date in {col}", (series.notna() & parsed.isna()).sum(), "set to missing")
    return parsed


def match_names(series: pd.Series, valid_names: list[str], log: QualityLog, source: str, col: str) -> pd.Series:
    """Match free-text names to a reference list ignoring case, e.g. 'TAMPINES ' -> 'Tampines'."""
    lookup = {name.lower(): name for name in valid_names}
    cleaned = series.str.strip().str.lower().map(lookup)
    log.add(source, f"inconsistent {col} spelling", (series.notna() & (series != cleaned)).sum(), "matched to reference list")
    return cleaned
