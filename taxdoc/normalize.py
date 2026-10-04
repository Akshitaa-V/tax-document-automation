"""Turns raw text values from different document layouts into clean, typed values."""

from __future__ import annotations

import re
from datetime import date, datetime

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

AMOUNT_FIELDS = {"gross_amount", "wht_amount", "net_amount"}


def parse_amount(text: str) -> float:
    """Reads 1,234.56 and 1.234,56 alike: the last separator is the decimal mark."""
    cleaned = re.sub(r"[^\d,.\-]", "", text)
    if not cleaned or not re.search(r"\d", cleaned):
        raise ValueError(f"no number in {text!r}")
    last_dot, last_comma = cleaned.rfind("."), cleaned.rfind(",")
    if last_comma > last_dot:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    return round(float(cleaned), 2)


def parse_rate(text: str) -> float:
    cleaned = text.replace("%", "").strip().replace(",", ".")
    return float(cleaned)


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", text)
    if match and match.group(2).lower() in MONTHS:
        return date(int(match.group(3)), MONTHS[match.group(2).lower()], int(match.group(1)))
    raise ValueError(f"unknown date format {text!r}")


def normalize_field(field: str, raw: str):
    """Returns the typed value for one field; raises ValueError if it cannot be read."""
    raw = raw.strip()
    if field in AMOUNT_FIELDS:
        return parse_amount(raw)
    if field == "wht_rate":
        return parse_rate(raw)
    if field == "payment_date":
        return parse_date(raw).isoformat()
    if field in {"currency", "source_country", "residence_country"}:
        return raw.upper()
    return raw
