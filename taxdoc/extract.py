"""Document extraction with two interchangeable backends.

- ``local``: reads the PDF text layer with pdfplumber and maps labels to fields.
  Runs offline and is what the tests and the default pipeline use.
- ``azure``: sends the PDF to Azure AI Document Intelligence (prebuilt-layout
  model with key-value pairs) and maps the returned keys with the same label list.

Both return the same ``Extraction`` object, so validation does not care where
the data came from.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
import yaml

from .config import ROOT
from .normalize import normalize_field

LABELS_FILE = ROOT / "config" / "field_labels.yaml"


@dataclass
class Extraction:
    file_name: str
    fields: dict = field(default_factory=dict)
    unreadable: dict = field(default_factory=dict)  # field -> raw text that failed to parse
    backend: str = "local"


def load_label_map(path: Path = LABELS_FILE) -> dict[str, str]:
    """Returns {lower-case label: field name}."""
    synonyms = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {label.lower(): name for name, labels in synonyms.items() for label in labels}


def map_pairs(pairs: list[tuple[str, str]], file_name: str, backend: str,
              label_map: dict[str, str] | None = None) -> Extraction:
    """Maps (label, value) pairs from any backend onto the field schema."""
    label_map = label_map or load_label_map()
    result = Extraction(file_name=file_name, backend=backend)
    for label, raw in pairs:
        name = label_map.get(label.strip().rstrip(":").strip().lower())
        if name is None or name in result.fields:
            continue
        try:
            result.fields[name] = normalize_field(name, raw)
        except ValueError:
            result.unreadable[name] = raw
    return result


# ---------------------------------------------------------------- local backend
def extract_local(pdf_path: str | Path, label_map: dict[str, str] | None = None) -> Extraction:
    pdf_path = Path(pdf_path)
    pairs = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for line in (page.extract_text() or "").splitlines():
                if ":" in line:
                    label, _, value = line.partition(":")
                    pairs.append((label, value))
    return map_pairs(pairs, pdf_path.name, "local", label_map)


# ---------------------------------------------------------------- Azure backend
def azure_pairs_from_result(result) -> list[tuple[str, str]]:
    """Reads key-value pairs from an Azure Document Intelligence AnalyzeResult."""
    pairs = []
    for kv in getattr(result, "key_value_pairs", None) or []:
        key = getattr(kv.key, "content", "") if kv.key else ""
        value = getattr(kv.value, "content", "") if kv.value else ""
        if key and value:
            pairs.append((key, value))
    return pairs


def make_azure_client():  # pragma: no cover - needs a live Azure resource
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    endpoint = os.environ["AZURE_DOCINTEL_ENDPOINT"]
    key = os.environ["AZURE_DOCINTEL_KEY"]
    return DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))


def extract_azure(pdf_path: str | Path, client=None, label_map: dict[str, str] | None = None) -> Extraction:
    """Analyzes one PDF with the prebuilt-layout model and the key-value pairs feature."""
    from azure.ai.documentintelligence.models import DocumentAnalysisFeature

    pdf_path = Path(pdf_path)
    client = client or make_azure_client()
    with pdf_path.open("rb") as fh:
        poller = client.begin_analyze_document(
            "prebuilt-layout", body=fh, features=[DocumentAnalysisFeature.KEY_VALUE_PAIRS])
    return map_pairs(azure_pairs_from_result(poller.result()), pdf_path.name, "azure", label_map)


def extract(pdf_path: str | Path, backend: str = "local", **kwargs) -> Extraction:
    if backend == "azure":
        return extract_azure(pdf_path, **kwargs)
    return extract_local(pdf_path, **kwargs)
