# Tax Document Automation

Withholding tax certificates arrive as PDFs from many paying agents and custodians, each with its own layout, labels and number format. This project turns them into checked, structured data: it extracts the fields, checks the arithmetic and rates, finds tax that can be reclaimed under a double tax treaty and tracks the reclaim deadline, keeps a filing calendar, and writes star-schema tables for a Power BI dashboard. A Power Automate flow connects it to SharePoint, Excel and Microsoft Teams.

```
SharePoint inbox --> Power Automate --> /certificates API --> extraction (local or Azure AI Document Intelligence)
                                                               --> checks + reclaim detection
                                                               --> Excel log, Teams alert
batch run --> Power BI tables (fact_certificate, fact_finding, fact_obligation, dims) --> weekly digest
```

## Results on the synthetic test set

120 fictional certificates in 3 layouts (English and German number and date formats), with 32 planted problems:

| Measure | Result |
|---|---|
| Fields extracted correctly | 1,434 of 1,434 |
| Planted errors found | 32 of 32, no false alarms |
| Reclaim opportunities found | 32 of 32, every amount exact to the cent |
| Reclaim potential identified | about EUR 4.25 million (9 already past the deadline, 2 due within 90 days) |
| Run time, 120 PDFs end to end | about 2 seconds |
| Tests | 19 passing |

The same scores hold across 12 different random seeds. The data is synthetic and generated with known answers, so these numbers show that the checks are correct, not how the extraction handles messy real-world scans. That is what the Azure backend is for.

## What it checks

| Rule | Meaning |
|---|---|
| `MISSING_FIELD`, `UNREADABLE_FIELD` | A required value is missing or could not be read. Values are never guessed. |
| `NET_MISMATCH` | Gross - tax withheld is not equal to the net amount. |
| `RATE_AMOUNT_MISMATCH` | Tax withheld does not equal rate x gross. |
| `DUPLICATE_ID` | The same certificate ID appears on more than one document. |
| `UNKNOWN_CURRENCY`, `UNKNOWN_COUNTRY`, `FUTURE_DATE` | Values that cannot be booked as they are. |
| `RECLAIM_OPPORTUNITY` | More tax was withheld than the treaty rate allows; shows the reclaimable amount and deadline. |
| `RECLAIM_DUE_SOON`, `RECLAIM_EXPIRED` | Reclaim deadline within 90 days, or already passed. |

Rates, treaty rates, reclaim periods and tolerances live in [`config/tax_rules.yaml`](config/tax_rules.yaml), so they can be changed without touching code. **The values in that file are simplified and illustrative, not tax advice.**

New document layouts usually need only new label synonyms in [`config/field_labels.yaml`](config/field_labels.yaml).

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m taxdoc generate --out data --n 120            # synthetic certificates + ground truth
python -m taxdoc run --data data --out out              # digest + Power BI tables in out/powerbi/
python -m taxdoc evaluate --data data --out out         # scores against the ground truth
pytest -q
```

### API

```bash
uvicorn taxdoc.api:app --port 8000
# open http://localhost:8000/docs and try POST /certificates/upload with a PDF from data/certificates/
```

`POST /certificates` takes `{"file_name": ..., "content_base64": ...}`, which is what the Power Automate flow sends.

### Azure AI Document Intelligence and Azure OpenAI

Copy `.env.example` to `.env`, fill in your endpoints and keys, then:

```bash
python -m taxdoc run --data data --out out --backend azure   # prebuilt-layout model with key-value pairs
python -m taxdoc run --data data --out out --llm             # Azure OpenAI rewrites the weekly digest
```

The Azure backend maps the key-value pairs returned by the prebuilt-layout model through the same label list, so the checks are identical for both backends. The free F0 tier of Document Intelligence is enough for the test set.

When `--llm` is set, the rewritten digest is used only if every number in it also appears in the template version; otherwise the template text is kept.

## Power Platform

- [`power_automate/`](power_automate/): cloud flow (SharePoint trigger, HTTP call to the API, Excel log, Teams alert) and how to build it.
- [`powerbi/`](powerbi/): DAX measures and the star-schema model with suggested report pages.

## Project layout

```
taxdoc/
  generate.py   synthetic certificates, planted problems, filing calendar
  normalize.py  amounts (1,234.56 and 1.234,56), rates and dates in several formats
  extract.py    local (pdfplumber) and Azure AI Document Intelligence backends
  validate.py   checks and reclaim detection
  calendar.py   filing obligations: overdue, due soon, upcoming, filed
  export.py     Power BI star schema as CSV
  digest.py     weekly digest, optional Azure OpenAI wording with a number check
  pipeline.py   end-to-end run and evaluation
  api.py        FastAPI service for Power Automate
config/         tax rules and label synonyms
docs/           outline for a know-how session with a tax team
```

## License

MIT
