"""PDPA masking (D4): personal data is masked before it reaches the screen.

Which fields count as personal is set per archetype in mapping.yaml
("personal_fields"); DEFAULT_PERSONAL applies when a mapping says nothing.
"""
import pandas as pd

DEFAULT_PERSONAL = {"customer": ["name", "phone", "email"], "resource": ["name"]}


def mask_name(name) -> str:
    """'Jun Hao Tan' -> 'J** H** T**'"""
    if pd.isna(name):
        return name
    return " ".join(word[0] + "*" * max(len(word) - 1, 2) for word in str(name).split())


def mask_phone(phone) -> str:
    """'91234567' -> '9***4567'"""
    if pd.isna(phone):
        return phone
    phone = str(phone)
    return phone[0] + "***" + phone[-4:]


def mask_email(email) -> str:
    """'jun.tan12@example.com' -> 'j***@example.com'"""
    if pd.isna(email) or "@" not in str(email):
        return email
    local, domain = str(email).split("@", 1)
    return local[0] + "***@" + domain


MASKERS = {"name": mask_name, "phone": mask_phone, "email": mask_email}


def mask_table(df: pd.DataFrame, table: str, personal_fields: dict | None = None) -> pd.DataFrame:
    """Return a copy of a customer/resource table with its personal columns masked."""
    fields = (personal_fields or DEFAULT_PERSONAL).get(table, [])
    df = df.copy()
    for column in fields:
        if column in df.columns:
            df[column] = df[column].map(MASKERS.get(column, mask_name))
    return df
