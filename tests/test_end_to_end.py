import base64
from datetime import date

import pytest
from fastapi.testclient import TestClient

from taxdoc import api
from taxdoc.generate import generate
from taxdoc.pipeline import evaluate, run

AS_OF = date(2026, 10, 1)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("data")
    generate(root, n=60, seed=11, as_of=AS_OF)
    return root


def test_pipeline_finds_every_planted_error(dataset, tmp_path):
    result = run(dataset / "certificates", dataset / "filing_obligations.csv", tmp_path, AS_OF)
    report = evaluate(result, dataset / "ground_truth.json")
    assert report["field_accuracy"] == 1.0
    assert report["error_recall"] == 1.0 and report["false_alarms"] == 0
    assert report["reclaims_found"] == report["reclaims_expected"]
    assert report["reclaim_amounts_exact"] == report["reclaims_expected"]
    for name in ("fact_certificate", "fact_finding", "fact_obligation", "dim_entity", "dim_country", "dim_date"):
        assert (tmp_path / "powerbi" / f"{name}.csv").exists()
    assert (tmp_path / "digest.md").read_text().startswith("# Tax document digest")


def test_api_accepts_power_automate_payload_and_flags_duplicates(dataset):
    api._seen_ids.clear()
    client = TestClient(api.app)
    pdf = sorted((dataset / "certificates").glob("*.pdf"))[0]
    payload = {"file_name": pdf.name, "content_base64": base64.b64encode(pdf.read_bytes()).decode(),
               "as_of": AS_OF.isoformat()}
    first = client.post("/certificates", json=payload).json()
    assert first["fields"]["certificate_id"]
    payload["file_name"] = "copy_" + pdf.name
    second = client.post("/certificates", json=payload).json()
    assert any(f["rule"] == "DUPLICATE_ID" for f in second["findings"])
    assert second["status"] == "needs review"


def test_api_rejects_non_pdf_and_bad_base64():
    client = TestClient(api.app)
    bad_type = {"file_name": "a.txt", "content_base64": base64.b64encode(b"hello").decode()}
    assert client.post("/certificates", json=bad_type).status_code == 415
    assert client.post("/certificates", json={"file_name": "a.pdf", "content_base64": "%%%"}).status_code == 400
    assert client.get("/health").json()["status"] == "ok"
