"""Compliance calendar: which filings are overdue or due soon, and who owns them."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path


def load_obligations(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def classify(obligations: list[dict], as_of: date, due_soon_days: int = 14) -> list[dict]:
    rows = []
    for ob in obligations:
        due = date.fromisoformat(ob["due_date"])
        days = (due - as_of).days
        if ob["status"] == "filed":
            state = "filed"
        elif days < 0:
            state = "overdue"
        elif days <= due_soon_days:
            state = "due_soon"
        else:
            state = "upcoming"
        rows.append(ob | {"days_to_due": days, "state": state})
    order = {"overdue": 0, "due_soon": 1, "upcoming": 2, "filed": 3}
    return sorted(rows, key=lambda r: (order[r["state"]], r["days_to_due"]))
