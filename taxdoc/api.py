"""HTTP API so a Power Automate flow (or any other tool) can send a certificate and get the checks back.

    uvicorn taxdoc.api:app --port 8000

POST /certificates          JSON {file_name, content_base64}  (what the Power Automate flow sends)
POST /certificates/upload   multipart file upload (for testing in the browser at /docs)
GET  /health
"""

from __future__ import annotations

import base64
import binascii
import os
import tempfile
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

from .config import load_rules
from .extract import extract
from .validate import Finding, check_certificate

app = FastAPI(title="Tax Document Automation", version="0.1.0")
RULES = load_rules()
BACKEND = os.environ.get("TAXDOC_BACKEND", "local")
_seen_ids: dict[str, str] = {}  # certificate_id -> first file name (in-memory; use a database in production)


class CertificateIn(BaseModel):
    file_name: str
    content_base64: str
    as_of: date | None = None


def _process(file_name: str, content: bytes, as_of: date | None) -> dict:
    if not content.startswith(b"%PDF"):
        raise HTTPException(status_code=415, detail="only PDF documents are accepted")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file_name).name
        path.write_bytes(content)
        doc = extract(path, backend=BACKEND)
    findings = check_certificate(doc, RULES, as_of or date.today())
    cid = doc.fields.get("certificate_id")
    if cid:
        first = _seen_ids.setdefault(cid, doc.file_name)
        if first != doc.file_name:
            findings.append(Finding(doc.file_name, cid, "DUPLICATE_ID", "error",
                                    f"certificate ID {cid} was already received in {first}"))
    errors = [f for f in findings if f.severity == "error"]
    return {
        "file_name": doc.file_name,
        "status": "needs review" if errors else "clean",
        "fields": doc.fields,
        "findings": [f.as_dict() for f in findings],
        "error_count": len(errors),
        "reclaim_potential": sum(f.amount or 0 for f in findings if f.rule == "RECLAIM_OPPORTUNITY"),
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "backend": BACKEND}


@app.post("/certificates")
def process_json(body: CertificateIn) -> dict:
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="content_base64 is not valid base64")
    return _process(body.file_name, content, body.as_of)


@app.post("/certificates/upload")
async def process_upload(file: UploadFile, as_of: date | None = None) -> dict:
    return _process(file.filename or "upload.pdf", await file.read(), as_of)
