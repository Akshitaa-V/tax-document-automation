"""Command line entry point.

    python -m taxdoc generate --out data --n 120
    python -m taxdoc run --data data --out out --as-of 2026-10-01 [--backend azure] [--llm]
    python -m taxdoc evaluate --data data --out out --as-of 2026-10-01
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .generate import generate
from .pipeline import evaluate, run


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="taxdoc", description="Withholding tax document automation")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="create a synthetic set of certificates")
    g.add_argument("--out", default="data")
    g.add_argument("--n", type=int, default=120)
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--as-of", default="2026-10-01")

    for name in ("run", "evaluate"):
        r = sub.add_parser(name)
        r.add_argument("--data", default="data")
        r.add_argument("--out", default="out")
        r.add_argument("--as-of", default="2026-10-01")
        r.add_argument("--backend", choices=["local", "azure"], default="local")
        r.add_argument("--llm", action="store_true", help="let Azure OpenAI rewrite the digest")

    args = parser.parse_args(argv)
    as_of = date.fromisoformat(args.as_of)
    if args.command == "generate":
        truth = generate(args.out, n=args.n, seed=args.seed, as_of=as_of)
        print(f"wrote {len(truth['certificates'])} certificates and "
              f"{len(truth['expected_errors'])} planted errors to {args.out}/")
        return

    data = Path(args.data)
    result = run(data / "certificates", data / "filing_obligations.csv", args.out, as_of,
                 backend=args.backend, use_llm=args.llm)
    if args.command == "run":
        print(result.digest)
        print(f"digest source: {result.digest_source} | {result.seconds:.2f} s | tables in {args.out}/powerbi/")
    else:
        report = evaluate(result, data / "ground_truth.json")
        Path(args.out, "evaluation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
