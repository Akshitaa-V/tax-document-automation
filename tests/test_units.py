from datetime import date
from types import SimpleNamespace

import pytest

from taxdoc.calendar import classify
from taxdoc.config import load_rules
from taxdoc.digest import build_digest, numbers_are_grounded
from taxdoc.extract import Extraction, azure_pairs_from_result, extract_azure, map_pairs
from taxdoc.normalize import parse_amount, parse_date, parse_rate
from taxdoc.validate import check_batch, check_certificate

RULES = load_rules()
AS_OF = date(2026, 10, 1)


def clean_fields(**overrides):
    fields = {
        "certificate_id": "WHT-1", "paying_agent": "Agent", "fund_entity": "Fund LU", "investee": "Co",
        "source_country": "DE", "residence_country": "LU", "payment_date": "2025-05-02", "currency": "EUR",
        "gross_amount": 100000.0, "wht_rate": 15.0, "wht_amount": 15000.0, "net_amount": 85000.0,
    }
    fields.update(overrides)
    return {k: v for k, v in fields.items() if v is not None}


def rules_of(findings):
    return sorted(f.rule for f in findings)


# ---------------------------------------------------------------- normalize
@pytest.mark.parametrize("text,value", [
    ("1,234,567.89", 1234567.89), ("1.234.567,89", 1234567.89), ("EUR 950.00", 950.0), ("12,5", 12.5),
])
def test_parse_amount_handles_both_number_styles(text, value):
    assert parse_amount(text) == value


def test_parse_rate_and_dates():
    assert parse_rate("26,375 %") == 26.375
    assert parse_date("02.05.2025") == date(2025, 5, 2)
    assert parse_date("02 May 2025") == date(2025, 5, 2)
    with pytest.raises(ValueError):
        parse_date("May the second")


# ---------------------------------------------------------------- validate
def test_clean_certificate_has_no_findings():
    assert check_certificate(Extraction("a.pdf", clean_fields()), RULES, AS_OF) == []


def test_each_error_rule_fires_alone():
    cases = {
        "NET_MISMATCH": clean_fields(net_amount=84000.0),
        "RATE_AMOUNT_MISMATCH": clean_fields(wht_amount=16000.0, net_amount=84000.0),
        "UNKNOWN_CURRENCY": clean_fields(currency="EUD"),
        "FUTURE_DATE": clean_fields(payment_date="2026-12-01"),
        "MISSING_FIELD": clean_fields(investee=None),
        "UNKNOWN_COUNTRY": clean_fields(source_country="XX"),
    }
    for rule, fields in cases.items():
        assert rules_of(check_certificate(Extraction("a.pdf", fields), RULES, AS_OF)) == [rule], rule


def test_unreadable_value_is_reported_not_guessed():
    doc = Extraction("a.pdf", clean_fields(gross_amount=None), unreadable={"gross_amount": "n/a"})
    assert rules_of(check_certificate(doc, RULES, AS_OF)) == ["UNREADABLE_FIELD"]


def test_reclaim_amount_and_deadline():
    fields = clean_fields(wht_rate=26.375, wht_amount=26375.0, net_amount=73625.0)
    findings = check_certificate(Extraction("a.pdf", fields), RULES, AS_OF)
    reclaim = next(f for f in findings if f.rule == "RECLAIM_OPPORTUNITY")
    assert reclaim.amount == 11375.0          # (26.375% - 15%) of 100,000
    assert reclaim.deadline == "2029-05-02"   # DE: 4 years after payment


def test_reclaim_deadline_states():
    expired = clean_fields(source_country="FR", payment_date="2023-01-10", wht_rate=25.0,
                           wht_amount=25000.0, net_amount=75000.0)
    soon = clean_fields(source_country="FR", payment_date="2024-11-15", wht_rate=25.0,
                        wht_amount=25000.0, net_amount=75000.0)
    assert "RECLAIM_EXPIRED" in rules_of(check_certificate(Extraction("a.pdf", expired), RULES, AS_OF))
    assert "RECLAIM_DUE_SOON" in rules_of(check_certificate(Extraction("b.pdf", soon), RULES, AS_OF))


def test_duplicate_ids_flag_both_documents():
    docs = [Extraction("a.pdf", clean_fields()), Extraction("b.pdf", clean_fields()),
            Extraction("c.pdf", clean_fields(certificate_id="WHT-2"))]
    dupes = [f.file_name for f in check_batch(docs, RULES, AS_OF) if f.rule == "DUPLICATE_ID"]
    assert sorted(dupes) == ["a.pdf", "b.pdf"]


# ---------------------------------------------------------------- extraction mapping
def test_label_synonyms_map_to_fields():
    doc = map_pairs([("Voucher ID", "V-9"), ("Gross dividend", "1.000,00"), ("Tax rate applied", "15 %"),
                     ("Unrelated label", "x")], "v.pdf", "local")
    assert doc.fields == {"certificate_id": "V-9", "gross_amount": 1000.0, "wht_rate": 15.0}


class FakePoller:
    def __init__(self, result):
        self._result = result

    def result(self):
        return self._result


class FakeAzureClient:
    """Stands in for DocumentIntelligenceClient and records the call."""

    def __init__(self, pairs):
        kv = [SimpleNamespace(key=SimpleNamespace(content=k), value=SimpleNamespace(content=v)) for k, v in pairs]
        self.result = SimpleNamespace(key_value_pairs=kv)
        self.calls = []

    def begin_analyze_document(self, model_id, body, features):
        self.calls.append((model_id, features))
        return FakePoller(self.result)


def test_azure_backend_maps_key_value_pairs(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    client = FakeAzureClient([("Reference:", "R-1"), ("Gross income", "2,000.00"), ("Date paid", "03 Mar 2025")])
    doc = extract_azure(pdf, client=client)
    assert doc.backend == "azure"
    assert doc.fields == {"certificate_id": "R-1", "gross_amount": 2000.0, "payment_date": "2025-03-03"}
    assert client.calls[0][0] == "prebuilt-layout"


def test_azure_pairs_skip_empty_values():
    result = SimpleNamespace(key_value_pairs=[SimpleNamespace(key=SimpleNamespace(content="Currency"), value=None)])
    assert azure_pairs_from_result(result) == []


# ---------------------------------------------------------------- calendar and digest
def test_calendar_states_and_order():
    rows = classify([
        {"filing": "a", "due_date": "2026-12-01", "status": "open"},
        {"filing": "b", "due_date": "2026-09-01", "status": "open"},
        {"filing": "c", "due_date": "2026-10-10", "status": "open"},
        {"filing": "d", "due_date": "2026-09-01", "status": "filed"},
    ], AS_OF)
    assert [(r["filing"], r["state"]) for r in rows] == [
        ("b", "overdue"), ("c", "due_soon"), ("a", "upcoming"), ("d", "filed")]


def test_digest_rejects_rewrites_with_invented_numbers():
    facts = {"certificates": 10, "clean": 8, "needs_review": 2, "errors_by_rule": {"NET_MISMATCH": 2},
             "reclaim_opportunities": 1, "reclaim_potential_eur": 500.0, "reclaims_due_soon": 0,
             "reclaims_expired": 0, "filings_overdue": 1, "filings_due_soon": 0, "overdue_items": []}
    _, source = build_digest(facts, "2026-10-01", use_llm=True, llm=lambda t: "12 certificates, all clean.")
    assert source == "template"
    text, source = build_digest(facts, "2026-10-01", use_llm=True,
                                llm=lambda t: "10 certificates: 8 clean, 2 to review.")
    assert source == "azure-openai" and text.startswith("10")
    assert numbers_are_grounded("EUR 500.00", "worth EUR 500.00")
