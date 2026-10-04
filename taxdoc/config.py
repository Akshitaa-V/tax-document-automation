"""Loads the tax rules file so every module reads the same settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import os

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RULES = ROOT / "config" / "tax_rules.yaml"


def load_env_file(path: Path = ROOT / ".env") -> None:
    """Reads KEY=value lines from .env into the environment (existing variables win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()


@dataclass(frozen=True)
class Rules:
    countries: dict
    allowed_currencies: list[str]
    required_fields: list[str]
    amount_tolerance: float
    reclaim_due_soon_days: int
    filing_due_soon_days: int
    fx_to_eur: dict

    def treaty_rate(self, source: str, residence: str) -> float | None:
        country = self.countries.get(source)
        if not country:
            return None
        return country["treaty_rate"].get(residence)

    def statutory_rate(self, source: str) -> float | None:
        country = self.countries.get(source)
        return None if country is None else float(country["statutory_rate"])

    def reclaim_years(self, source: str) -> int:
        return int(self.countries.get(source, {}).get("reclaim_years", 0))


def load_rules(path: str | Path = DEFAULT_RULES) -> Rules:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    checks = data["checks"]
    return Rules(
        countries=data["source_countries"],
        allowed_currencies=list(data["allowed_currencies"]),
        required_fields=list(data["required_fields"]),
        amount_tolerance=float(checks["amount_tolerance"]),
        reclaim_due_soon_days=int(checks["reclaim_due_soon_days"]),
        filing_due_soon_days=int(checks["filing_due_soon_days"]),
        fx_to_eur={k: float(v) for k, v in data.get("fx_to_eur", {}).items()},
    )
