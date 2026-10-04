"""Weekly digest for the tax team: what needs attention, in plain language.

The digest is built from a fixed template by default. Optionally, Azure OpenAI
rewrites it into a shorter note; that text is only used if every number in it
also appears in the facts, otherwise the template version is kept.
"""

from __future__ import annotations

import os
import re
from collections import Counter

from .validate import Finding


def collect_facts(findings: list[Finding], calendar_rows: list[dict], n_docs: int,
                  reclaim_eur: float) -> dict:
    errors = [f for f in findings if f.severity == "error"]
    files_with_errors = {f.file_name for f in errors}
    states = Counter(r["state"] for r in calendar_rows)
    due_soon_reclaims = [f for f in findings if f.rule == "RECLAIM_DUE_SOON"]
    return {
        "certificates": n_docs,
        "clean": n_docs - len(files_with_errors),
        "needs_review": len(files_with_errors),
        "errors_by_rule": dict(Counter(f.rule for f in errors).most_common()),
        "reclaim_opportunities": sum(1 for f in findings if f.rule == "RECLAIM_OPPORTUNITY"),
        "reclaim_potential_eur": round(reclaim_eur, 2),
        "reclaims_due_soon": len(due_soon_reclaims),
        "reclaims_expired": sum(1 for f in findings if f.rule == "RECLAIM_EXPIRED"),
        "filings_overdue": states.get("overdue", 0),
        "filings_due_soon": states.get("due_soon", 0),
        "overdue_items": [f"{r['filing']} ({r['fund_entity']}, owner: {r['owner']})"
                          for r in calendar_rows if r["state"] == "overdue"][:5],
    }


def template_digest(facts: dict, as_of: str) -> str:
    lines = [
        f"# Tax document digest - {as_of}",
        "",
        f"- {facts['certificates']} certificates processed: {facts['clean']} clean, "
        f"{facts['needs_review']} need review.",
        f"- {facts['reclaim_opportunities']} reclaim opportunities worth about "
        f"EUR {facts['reclaim_potential_eur']:,.2f}; {facts['reclaims_due_soon']} due within 90 days, "
        f"{facts['reclaims_expired']} already past the deadline.",
        f"- Filing calendar: {facts['filings_overdue']} overdue, {facts['filings_due_soon']} due within 14 days.",
        "",
        "## Issues to fix",
    ]
    lines += [f"- {rule}: {count}" for rule, count in facts["errors_by_rule"].items()] or ["- none"]
    if facts["overdue_items"]:
        lines += ["", "## Overdue filings"] + [f"- {item}" for item in facts["overdue_items"]]
    return "\n".join(lines) + "\n"


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def numbers_are_grounded(text: str, reference: str) -> bool:
    """True if every number in ``text`` also appears in ``reference``."""
    return _numbers(text) <= _numbers(reference)


def azure_openai_digest(template: str, client=None) -> str | None:  # pragma: no cover - live service
    try:
        from openai import AzureOpenAI

        client = client or AzureOpenAI(
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_key=os.environ["AZURE_OPENAI_KEY"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
        response = client.chat.completions.create(
            model=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            temperature=0,
            messages=[
                {"role": "system", "content": "Rewrite the digest as a short note for a tax team. "
                 "Keep every number exactly as given. Do not add any facts."},
                {"role": "user", "content": template},
            ],
        )
        return response.choices[0].message.content
    except Exception:
        return None


def build_digest(facts: dict, as_of: str, use_llm: bool = False, llm=azure_openai_digest) -> tuple[str, str]:
    """Returns (text, source) where source is 'template' or 'azure-openai'."""
    template = template_digest(facts, as_of)
    if use_llm:
        rewritten = llm(template)
        if rewritten and numbers_are_grounded(rewritten, template):
            return rewritten, "azure-openai"
    return template, "template"
