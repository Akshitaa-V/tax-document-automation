"""End-to-end run: extract -> check -> calendar -> Power BI tables -> digest."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .calendar import classify, load_obligations
from .config import Rules, load_rules
from .digest import build_digest, collect_facts
from .export import export_tables
from .extract import Extraction, extract
from .validate import Finding, check_batch


@dataclass
class RunResult:
    docs: list[Extraction]
    findings: list[Finding]
    calendar: list[dict]
    digest: str
    digest_source: str
    seconds: float


def run(pdf_dir: str | Path, obligations_csv: str | Path, out_dir: str | Path, as_of: date,
        backend: str = "local", use_llm: bool = False, rules: Rules | None = None) -> RunResult:
    rules = rules or load_rules()
    start = time.perf_counter()
    docs = [extract(p, backend=backend) for p in sorted(Path(pdf_dir).glob("*.pdf"))]
    findings = check_batch(docs, rules, as_of)
    calendar = classify(load_obligations(obligations_csv), as_of, rules.filing_due_soon_days)
    export_tables(Path(out_dir) / "powerbi", docs, findings, calendar, rules)

    reclaim_eur = 0.0
    for f in findings:
        if f.rule == "RECLAIM_OPPORTUNITY" and f.amount:
            doc = next(d for d in docs if d.file_name == f.file_name)
            reclaim_eur += f.amount * rules.fx_to_eur.get(doc.fields.get("currency", ""), 0.0)
    facts = collect_facts(findings, calendar, len(docs), reclaim_eur)
    text, source = build_digest(facts, as_of.isoformat(), use_llm=use_llm)
    out = Path(out_dir)
    (out / "digest.md").write_text(text, encoding="utf-8")
    (out / "findings.json").write_text(json.dumps([f.as_dict() for f in findings], indent=2), encoding="utf-8")
    return RunResult(docs, findings, calendar, text, source, time.perf_counter() - start)


def evaluate(result: RunResult, truth_path: str | Path, rules: Rules | None = None) -> dict:
    """Compares the run with the generator's ground truth."""
    rules = rules or load_rules()
    truth = json.loads(Path(truth_path).read_text(encoding="utf-8"))
    by_file = {c["file_name"]: c for c in truth["certificates"]}

    # 1. field extraction accuracy (fields that are printed on the document)
    checked = correct = 0
    for doc in result.docs:
        t = by_file[doc.file_name]
        for name in rules.required_fields:
            if name == t["omitted_field"]:
                continue
            checked += 1
            got, want = doc.fields.get(name), t[name]
            if isinstance(want, float):
                correct += got is not None and abs(got - want) < 0.005
            else:
                correct += got == want

    # 2. error detection: (file, rule) pairs
    expected = {(e["file_name"], e["rule"]) for e in truth["expected_errors"]}
    found = {(f.file_name, f.rule) for f in result.findings if f.severity == "error"}
    tp = len(expected & found)

    # 3. reclaim detection: rate above treaty rate, judged on the true values
    exp_reclaim = {}
    for c in truth["certificates"]:
        if c["omitted_field"] in {"wht_rate", "residence_country"}:
            continue
        treaty = rules.treaty_rate(c["source_country"], c["residence_country"])
        if treaty is not None and c["wht_rate"] > treaty + 1e-9:
            exp_reclaim[c["file_name"]] = round(c["gross_amount"] * (c["wht_rate"] - treaty) / 100, 2)
    got_reclaim = {f.file_name: f.amount for f in result.findings if f.rule == "RECLAIM_OPPORTUNITY"}
    reclaim_tp = len(exp_reclaim.keys() & got_reclaim.keys())
    amounts_ok = sum(abs(exp_reclaim[k] - got_reclaim[k]) < 0.01 for k in exp_reclaim.keys() & got_reclaim.keys())

    return {
        "certificates": len(result.docs),
        "field_accuracy": round(correct / checked, 4) if checked else 0.0,
        "fields_checked": checked,
        "planted_errors": len(expected),
        "errors_found": tp,
        "false_alarms": len(found - expected),
        "error_recall": round(tp / len(expected), 4) if expected else 1.0,
        "error_precision": round(tp / len(found), 4) if found else 1.0,
        "reclaims_expected": len(exp_reclaim),
        "reclaims_found": reclaim_tp,
        "reclaim_false_alarms": len(got_reclaim.keys() - exp_reclaim.keys()),
        "reclaim_amounts_exact": amounts_ok,
        "seconds": round(result.seconds, 2),
    }
