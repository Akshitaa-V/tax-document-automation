"""Checks extracted certificates and finds refund (reclaim) opportunities.

Errors block a certificate from being booked until someone fixes it.
Reclaim findings are not errors: they show where more tax was withheld than the
treaty rate allows, how much could be claimed back, and by when.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date

from .config import Rules
from .extract import Extraction

SEVERITY = {
    "MISSING_FIELD": "error",
    "UNREADABLE_FIELD": "error",
    "NET_MISMATCH": "error",
    "RATE_AMOUNT_MISMATCH": "error",
    "DUPLICATE_ID": "error",
    "UNKNOWN_CURRENCY": "error",
    "FUTURE_DATE": "error",
    "UNKNOWN_COUNTRY": "error",
    "RECLAIM_OPPORTUNITY": "info",
    "RECLAIM_DUE_SOON": "warning",
    "RECLAIM_EXPIRED": "warning",
}


@dataclass
class Finding:
    file_name: str
    certificate_id: str
    rule: str
    severity: str
    message: str
    amount: float | None = None  # reclaim potential in document currency
    deadline: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28)


def check_certificate(doc: Extraction, rules: Rules, as_of: date) -> list[Finding]:
    f = doc.fields
    cid = f.get("certificate_id", "?")
    out: list[Finding] = []

    def add(rule: str, message: str, **extra) -> None:
        out.append(Finding(doc.file_name, cid, rule, SEVERITY[rule], message, **extra))

    for name, raw in doc.unreadable.items():
        add("UNREADABLE_FIELD", f"{name} could not be read: {raw!r}")
    for name in rules.required_fields:
        if name not in f and name not in doc.unreadable:
            add("MISSING_FIELD", f"{name} is missing on the certificate")

    tol = rules.amount_tolerance
    if {"gross_amount", "wht_amount", "net_amount"} <= f.keys():
        diff = round(f["gross_amount"] - f["wht_amount"] - f["net_amount"], 2)
        if abs(diff) > tol:
            add("NET_MISMATCH", f"gross - tax - net = {diff:,.2f}, expected 0")
    if {"gross_amount", "wht_rate", "wht_amount"} <= f.keys():
        expected = round(f["gross_amount"] * f["wht_rate"] / 100, 2)
        if abs(expected - f["wht_amount"]) > tol:
            add("RATE_AMOUNT_MISMATCH",
                f"tax {f['wht_amount']:,.2f} does not match {f['wht_rate']}% of gross ({expected:,.2f})")
    if "currency" in f and f["currency"] not in rules.allowed_currencies:
        add("UNKNOWN_CURRENCY", f"currency {f['currency']!r} is not an accepted ISO code")

    pay_date = date.fromisoformat(f["payment_date"]) if "payment_date" in f else None
    if pay_date and pay_date > as_of:
        add("FUTURE_DATE", f"payment date {pay_date} lies after the reporting date {as_of}")

    source, residence = f.get("source_country"), f.get("residence_country")
    if source and source not in rules.countries:
        add("UNKNOWN_COUNTRY", f"no tax rules configured for source country {source!r}")
        return out

    treaty = rules.treaty_rate(source, residence) if source and residence else None
    if treaty is not None and {"wht_rate", "gross_amount"} <= f.keys() and f["wht_rate"] > treaty + 1e-9:
        potential = round(f["gross_amount"] * (f["wht_rate"] - treaty) / 100, 2)
        deadline = _add_years(pay_date, rules.reclaim_years(source)) if pay_date else None
        add("RECLAIM_OPPORTUNITY",
            f"{f['wht_rate']}% withheld, treaty rate {treaty}%: {potential:,.2f} {f.get('currency', '')} reclaimable",
            amount=potential, deadline=deadline.isoformat() if deadline else None)
        if deadline:
            days_left = (deadline - as_of).days
            if days_left < 0:
                add("RECLAIM_EXPIRED", f"reclaim deadline {deadline} has passed", amount=potential,
                    deadline=deadline.isoformat())
            elif days_left <= rules.reclaim_due_soon_days:
                add("RECLAIM_DUE_SOON", f"reclaim must be filed within {days_left} days (by {deadline})",
                    amount=potential, deadline=deadline.isoformat())
    return out


def check_batch(docs: list[Extraction], rules: Rules, as_of: date) -> list[Finding]:
    findings: list[Finding] = []
    for doc in docs:
        findings.extend(check_certificate(doc, rules, as_of))
    counts = Counter(d.fields.get("certificate_id") for d in docs if d.fields.get("certificate_id"))
    for doc in docs:
        cid = doc.fields.get("certificate_id")
        if cid and counts[cid] > 1:
            findings.append(Finding(doc.file_name, cid, "DUPLICATE_ID", "error",
                                    f"certificate ID {cid} appears on {counts[cid]} documents"))
    return findings
