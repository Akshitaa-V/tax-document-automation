"""Creates a synthetic set of withholding tax certificates as PDFs.

Every certificate is fictional. The generator plants known problems (missing
fields, wrong arithmetic, duplicate IDs, ...) and writes a ground-truth file, so
the extraction and the checks can be measured instead of eyeballed.
"""

from __future__ import annotations

import csv
import json
import random
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from .config import Rules, load_rules

FUND_ENTITIES = {
    "Northbridge Infrastructure Fund I SCSp": "LU",
    "Northbridge Renewables Holding DAC": "IE",
    "Northbridge Private Debt GmbH & Co. KG": "DE",
}
PAYING_AGENTS = [
    "Hanseatic Paying Agent AG",
    "Alpine Custody SA",
    "Atlantic Trust Services Inc.",
    "Rhine Securities Services GmbH",
]
INVESTEES = {
    "DE": ["Elbtal Netze AG", "Isarwind Energie AG"],
    "FR": ["Rhone Mobilite SA", "Loire Fibre SAS"],
    "CH": ["Glarus Wasserkraft AG", "Ticino Data Centers SA"],
    "US": ["Prairie Midstream Inc.", "Cascade Towers Corp."],
    "NL": ["Polder Havens N.V.", "Delta Warmte B.V."],
    "ES": ["Meseta Solar S.A.", "Cantabria Puertos S.A."],
    "IT": ["Appennino Reti S.p.A.", "Laguna Energia S.p.A."],
    "GB": ["Pennine Water plc", "Thames Grid Ltd"],
}
BAD_CURRENCIES = ["EUD", "USS", "CHE", "ERU"]
PLANT_PLAN = {  # planted problem -> number of certificates
    "missing_field": 6,
    "net_mismatch": 5,
    "rate_amount_mismatch": 5,
    "duplicate_id": 4,
    "unknown_currency": 4,
    "future_date": 4,
}
MISSABLE_FIELDS = ["investee", "payment_date", "wht_rate", "residence_country", "wht_amount", "paying_agent"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@dataclass
class Certificate:
    certificate_id: str
    paying_agent: str
    fund_entity: str
    investee: str
    source_country: str
    residence_country: str
    payment_date: str  # ISO date
    currency: str
    gross_amount: float
    wht_rate: float
    wht_amount: float
    net_amount: float
    template: str
    file_name: str = ""


def _random_date(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _build_clean(rng: random.Random, rules: Rules, idx: int) -> Certificate:
    fund, residence = rng.choice(list(FUND_ENTITIES.items()))
    sources = [c for c in rules.countries if c != residence]
    source = rng.choice(sources)
    country = rules.countries[source]
    treaty = rules.treaty_rate(source, residence)
    rate = treaty if rng.random() < 0.55 else float(country["statutory_rate"])
    gross = round(rng.uniform(5_000, 2_500_000), 2)
    wht = round(gross * rate / 100, 2)
    return Certificate(
        certificate_id=f"WHT-{2021 + idx % 6}-{10000 + idx * 7}",
        paying_agent=rng.choice(PAYING_AGENTS),
        fund_entity=fund,
        investee=rng.choice(INVESTEES[source]),
        source_country=source,
        residence_country=residence,
        payment_date=_random_date(rng, date(2021, 6, 1), date(2026, 9, 15)).isoformat(),
        currency=country["currency"],
        gross_amount=gross,
        wht_rate=rate,
        wht_amount=wht,
        net_amount=round(gross - wht, 2),
        template=rng.choice(["A", "B", "C"]),
    )


# ---------------------------------------------------------------- rendering
def _fmt_amount(value: float, style: str) -> str:
    text = f"{value:,.2f}"
    if style == "de":  # 1.234.567,89
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return text


def _fmt_rate(value: float, style: str) -> str:
    text = f"{value:g}"
    return (text.replace(".", ",") if style == "de" else text) + " %"


def _fmt_date(iso: str, template: str) -> str:
    d = date.fromisoformat(iso)
    if template == "B":
        return d.strftime("%d.%m.%Y")
    if template == "C":
        return f"{d.day:02d} {MONTHS[d.month - 1]} {d.year}"
    return iso


TEMPLATES = {
    # template -> (title, number style, labels)
    "A": ("Withholding Tax Certificate", "en", {
        "certificate_id": "Certificate No.", "paying_agent": "Paying agent", "fund_entity": "Beneficial owner",
        "residence_country": "Country of residence", "investee": "Issuer of securities", "source_country": "Source country",
        "payment_date": "Payment date", "currency": "Currency", "gross_amount": "Gross amount",
        "wht_rate": "Withholding tax rate", "wht_amount": "Withholding tax amount", "net_amount": "Net amount"}),
    "B": ("Tax Voucher - Dividend Distribution", "de", {
        "certificate_id": "Voucher ID", "paying_agent": "Issued by", "fund_entity": "Recipient",
        "residence_country": "Recipient residence", "investee": "Distributing company", "source_country": "Country of source",
        "payment_date": "Value date", "currency": "Currency", "gross_amount": "Gross dividend",
        "wht_rate": "Tax rate applied", "wht_amount": "Tax withheld", "net_amount": "Net payment"}),
    "C": ("Statement of Tax Deducted at Source", "en", {
        "certificate_id": "Reference", "paying_agent": "Custodian", "fund_entity": "Account holder",
        "residence_country": "Tax residence", "investee": "Company", "source_country": "Source state",
        "payment_date": "Date paid", "currency": "Payment currency", "gross_amount": "Gross income",
        "wht_rate": "Rate of tax deducted", "wht_amount": "Tax deducted", "net_amount": "Amount credited"}),
}


def render_pdf(cert: Certificate, path: Path, omit: str | None = None) -> None:
    title, style, labels = TEMPLATES[cert.template]
    values = {
        "certificate_id": cert.certificate_id,
        "paying_agent": cert.paying_agent,
        "fund_entity": cert.fund_entity,
        "residence_country": cert.residence_country,
        "investee": cert.investee,
        "source_country": cert.source_country,
        "payment_date": _fmt_date(cert.payment_date, cert.template),
        "currency": cert.currency,
        "gross_amount": _fmt_amount(cert.gross_amount, style),
        "wht_rate": _fmt_rate(cert.wht_rate, style),
        "wht_amount": _fmt_amount(cert.wht_amount, style),
        "net_amount": _fmt_amount(cert.net_amount, style),
    }
    pdf = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(60, height - 70, title)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(60, height - 88, "This document confirms the tax withheld on the distribution below.")
    y = height - 125
    for field, label in labels.items():
        if field == omit:
            continue
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(60, y, f"{label}:")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(250, y, values[field])
        y -= 20
    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(60, 60, "Synthetic document created for testing. Not a real tax certificate.")
    pdf.save()


# ---------------------------------------------------------------- data set
def generate(out_dir: str | Path, n: int = 120, seed: int = 7, as_of: date = date(2026, 10, 1),
             rules: Rules | None = None) -> dict:
    rules = rules or load_rules()
    rng = random.Random(seed)
    out = Path(out_dir)
    pdf_dir = out / "certificates"
    pdf_dir.mkdir(parents=True, exist_ok=True)

    certs = [_build_clean(rng, rules, i) for i in range(n)]
    order = list(range(n))
    rng.shuffle(order)
    planted: dict[int, dict] = {}
    cursor = 0
    for problem, count in PLANT_PLAN.items():
        for _ in range(count):
            planted[order[cursor]] = {"problem": problem}
            cursor += 1

    omitted: dict[int, str] = {}
    expected_errors: list[dict] = []
    for i, info in planted.items():
        cert = certs[i]
        problem = info["problem"]
        if problem == "missing_field":
            field = rng.choice(MISSABLE_FIELDS)
            omitted[i] = field
            info["field"] = field
            expected_errors.append({"index": i, "rule": "MISSING_FIELD"})
        elif problem == "net_mismatch":
            cert.net_amount = round(cert.net_amount + rng.choice([-1, 1]) * rng.uniform(25, 900), 2)
            expected_errors.append({"index": i, "rule": "NET_MISMATCH"})
        elif problem == "rate_amount_mismatch":
            if cert.wht_amount == 0:  # 0% source country: tax withheld although none was due
                cert.wht_amount = round(cert.gross_amount * rng.uniform(0.01, 0.05), 2)
            else:
                cert.wht_amount = round(cert.wht_amount * rng.uniform(1.05, 1.25), 2)
            cert.net_amount = round(cert.gross_amount - cert.wht_amount, 2)  # net stays consistent
            expected_errors.append({"index": i, "rule": "RATE_AMOUNT_MISMATCH"})
        elif problem == "unknown_currency":
            cert.currency = rng.choice(BAD_CURRENCIES)
            expected_errors.append({"index": i, "rule": "UNKNOWN_CURRENCY"})
        elif problem == "future_date":
            cert.payment_date = _random_date(rng, as_of + timedelta(days=20), as_of + timedelta(days=180)).isoformat()
            expected_errors.append({"index": i, "rule": "FUTURE_DATE"})

    # duplicates: copy the ID of a clean certificate onto the planted one; both get flagged
    clean_pool = [i for i in range(n) if i not in planted]
    for i, info in planted.items():
        if info["problem"] == "duplicate_id":
            twin = clean_pool.pop(rng.randrange(len(clean_pool)))
            certs[i].certificate_id = certs[twin].certificate_id
            info["twin"] = twin
            expected_errors.append({"index": i, "rule": "DUPLICATE_ID"})
            expected_errors.append({"index": twin, "rule": "DUPLICATE_ID"})

    for i, cert in enumerate(certs):
        cert.file_name = f"cert_{i:03d}.pdf"
        render_pdf(cert, pdf_dir / cert.file_name, omit=omitted.get(i))

    truth = {
        "seed": seed,
        "as_of": as_of.isoformat(),
        "certificates": [asdict(c) | {"omitted_field": omitted.get(i)} for i, c in enumerate(certs)],
        "expected_errors": [{"file_name": certs[e["index"]].file_name, "rule": e["rule"]} for e in expected_errors],
    }
    (out / "ground_truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
    _write_obligations(out / "filing_obligations.csv", rng, as_of)
    return truth


def _write_obligations(path: Path, rng: random.Random, as_of: date) -> None:
    """Creates a filing calendar: annual returns, reclaim filings and reporting duties per entity."""
    filings = {
        "LU": ["Corporate income tax return", "Subscription tax return", "DAC6 reportability review"],
        "IE": ["Corporation tax return (CT1)", "Dividend WHT return", "FATCA/CRS report"],
        "DE": ["Separate and uniform determination return", "Trade tax return", "Capital gains tax registration"],
    }
    owners = ["Tax Compliance", "Fund Tax", "Transaction Tax", "Tax Reporting"]
    rows = []
    for fund, residence in FUND_ENTITIES.items():
        for name in filings[residence]:
            for year in (2025, 2026):
                due = as_of + timedelta(days=rng.randint(-60, 240) + (365 if year == 2026 else 0) - 365)
                status = "filed" if due < as_of and rng.random() < 0.75 else "open"
                rows.append({
                    "obligation_id": f"OBL-{len(rows) + 1:03d}",
                    "fund_entity": fund,
                    "jurisdiction": residence,
                    "filing": name,
                    "period": str(year - 1),
                    "owner": rng.choice(owners),
                    "due_date": due.isoformat(),
                    "status": status,
                })
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
