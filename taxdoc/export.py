"""Writes a star schema of CSV tables for Power BI (or Excel / Power Query).

fact_certificate   one row per certificate, amounts in document currency and EUR
fact_finding       one row per finding (errors, warnings, reclaim opportunities)
fact_obligation    filing calendar with state (overdue, due soon, upcoming, filed)
dim_entity         fund entities and their tax residence
dim_country        source countries with statutory and treaty rates
dim_date           calendar table for time intelligence in DAX
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

from .config import Rules
from .extract import Extraction
from .validate import Finding


def _write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_tables(out_dir: str | Path, docs: list[Extraction], findings: list[Finding],
                  obligations: list[dict], rules: Rules) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    errors_by_file: dict[str, int] = {}
    reclaim_by_file: dict[str, float] = {}
    for f in findings:
        if f.severity == "error":
            errors_by_file[f.file_name] = errors_by_file.get(f.file_name, 0) + 1
        if f.rule == "RECLAIM_OPPORTUNITY" and f.amount:
            reclaim_by_file[f.file_name] = f.amount

    cert_rows, entities = [], {}
    for d in docs:
        x = d.fields
        fx = rules.fx_to_eur.get(x.get("currency", ""), None)
        row = {k: x.get(k, "") for k in rules.required_fields} | {"file_name": d.file_name}
        row["error_count"] = errors_by_file.get(d.file_name, 0)
        row["status"] = "needs review" if row["error_count"] else "clean"
        row["reclaim_potential"] = reclaim_by_file.get(d.file_name, 0.0)
        for col in ("gross_amount", "wht_amount", "reclaim_potential"):
            value = row.get(col)
            row[f"{col}_eur"] = round(value * fx, 2) if fx is not None and isinstance(value, float) else ""
        cert_rows.append(row)
        if x.get("fund_entity"):
            entities[x["fund_entity"]] = x.get("residence_country", "")

    cert_fields = ["file_name", *rules.required_fields, "gross_amount_eur", "wht_amount_eur",
                   "reclaim_potential", "reclaim_potential_eur", "error_count", "status"]
    paths = [out / name for name in ("fact_certificate.csv", "fact_finding.csv", "fact_obligation.csv",
                                     "dim_entity.csv", "dim_country.csv", "dim_date.csv")]
    _write(paths[0], cert_rows, cert_fields)
    _write(paths[1], [f.as_dict() for f in findings],
           ["file_name", "certificate_id", "rule", "severity", "message", "amount", "deadline"])
    _write(paths[2], obligations, ["obligation_id", "fund_entity", "jurisdiction", "filing", "period", "owner",
                                   "due_date", "status", "days_to_due", "state"])
    _write(paths[3], [{"fund_entity": k, "residence_country": v} for k, v in sorted(entities.items())],
           ["fund_entity", "residence_country"])
    country_rows = []
    for code, c in rules.countries.items():
        for residence, rate in c["treaty_rate"].items():
            country_rows.append({"source_country": code, "country_name": c["name"], "residence_country": residence,
                                 "statutory_rate": c["statutory_rate"], "treaty_rate": rate,
                                 "reclaim_years": c["reclaim_years"]})
    _write(paths[4], country_rows, list(country_rows[0]))
    start, end = date(2021, 1, 1), date(2031, 12, 31)
    dates = []
    day = start
    while day <= end:
        dates.append({"date": day.isoformat(), "year": day.year, "quarter": f"Q{(day.month - 1) // 3 + 1}",
                      "month": day.month, "month_name": day.strftime("%b")})
        day += timedelta(days=1)
    _write(paths[5], dates, list(dates[0]))
    return paths
