"""Command line: python -m silver {parse,build} ...

Exit code: 0 = all invoices usable, 1 = some are rejected, 2 = input error.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import duckdb

from paths import BRONZE, SILVER

from .parsing.parser import parse_invoice
from .reader import read_documents
from .tables import Silver, analyse, summary, write


def run_parse(args: argparse.Namespace) -> int:
    documents, unusable = read_documents(args.source)
    for bad in unusable:
        print(f"{bad.source}: unusable bronze record: {bad.reason}", file=sys.stderr)
    failed = bool(unusable)
    for markdown, record in documents:
        origin = {k: record[k] for k in ("source", "sha256", "kind")}
        result = parse_invoice(markdown)
        failed |= not result.complete
        if args.json:
            print(json.dumps(
                {**origin, "complete": result.complete, "facture": asdict(result.facture),
                 "issues": [asdict(i) for i in result.issues]},
                ensure_ascii=False, default=str,
            ))
        else:
            f = result.facture
            state = "ok" if not result.issues else "check" if result.complete else "ERROR"
            print(f"{state:<6}{origin['kind']:<6}{f.numero or '?':<14}{f.date_emission or '?'!s:<11} "
                  f"{f.fournisseur.nom or '?':<24}{len(f.lignes):>2} line(s) "
                  f"{f.total_ttc if f.total_ttc is not None else '?':>10}  {f.statut or '?'}")
            for issue in result.issues:
                print(f"      {issue.severity}: {issue.field}: {issue.message}")
    return int(failed)


def _report(silver: Silver) -> None:
    for doc in silver.documents:
        if doc.anomalies:
            state = "REJETEE" if doc.rejete else "signalee"
            print(f"{state:<9}{doc.facture.numero or '?':<14}{doc.record['source']}",
                  file=sys.stderr)
            for a in doc.anomalies:
                print(f"    {a.code} ({a.champ}) : {a.message}", file=sys.stderr)
    for bad in silver.unusable:
        print(f"REJETEE  {bad.source}\n    bronze_inutilisable : {bad.reason}", file=sys.stderr)


def run_build(args: argparse.Namespace) -> int:
    silver = analyse(args.source)
    _report(silver)
    result = summary(silver)
    if not args.dry_run:
        result["tables"] = write(silver, args.out)
    print(json.dumps(result, ensure_ascii=False))
    return int(result["rejetees"] > 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="silver", description="Silver layer.")
    commands = parser.add_subparsers(dest="command", required=True)

    cmd = commands.add_parser("parse", help="parse bronze Markdown and print the result")
    cmd.add_argument("source", type=Path, nargs="?", default=BRONZE, help=".md file or folder")
    cmd.add_argument("--json", action="store_true", help="one JSON line per invoice")
    cmd.set_defaults(run=run_parse)

    cmd = commands.add_parser("build", help="check every invoice and write the silver tables")
    cmd.add_argument("source", type=Path, nargs="?", default=BRONZE, help="bronze store")
    cmd.add_argument("--out", type=Path, default=SILVER, help="where to write the tables")
    cmd.add_argument("--dry-run", action="store_true", help="check only, write nothing")
    cmd.set_defaults(run=run_build)

    args = parser.parse_args(argv)
    try:
        documents, unusable = read_documents(args.source) if args.source.exists() else ([], [])
        if not documents and not unusable:
            print(f"no bronze Markdown in {args.source}", file=sys.stderr)
            return 2
        return args.run(args)
    except (OSError, duckdb.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
