"""Aggregate every extraction into Parquet tables, ready for the warehouse.

    python -m warehouse.export_parquet

Refreshes the silver tables where they already are (factures/silver) and adds the
bronze tables (factures/warehouse), so that each table exists once.

The tables are derived data: they are rebuilt from bronze every time. The bronze
ones are read back and compared before they replace the previous ones.
Exit code: 0 = done, 1 = done, but some bronze records are unusable, 2 = failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

import duckdb

from silver.build import analyse, write

ROOT = Path(__file__).resolve().parent.parent
BRONZE = ROOT / "factures" / "bronze"
SILVER = ROOT / "factures" / "silver"
OUT = ROOT / "factures" / "warehouse"

log = logging.getLogger("export")

# Every extraction ever made, all versions included; silver uses the newest only.
TABLES = {
    "bronze_extractions": """
        document_id VARCHAR NOT NULL, version VARCHAR NOT NULL, source VARCHAR NOT NULL,
        s3_key VARCHAR, etag VARCHAR, s3_last_modified TIMESTAMPTZ, pulled_at TIMESTAMPTZ,
        converted_at TIMESTAMPTZ NOT NULL, type_document VARCHAR NOT NULL,
        taille_octets BIGINT, nb_pages INTEGER NOT NULL, pdf_repare BOOLEAN NOT NULL,
        ocr_moteur VARCHAR, ocr_modele VARCHAR, ocr_max_side INTEGER,
        ocr_format_image VARCHAR, texte_moteur VARCHAR, texte_version VARCHAR,
        markdown_sha256 VARCHAR NOT NULL, PRIMARY KEY (document_id, version)""",
    "bronze_pages": """
        document_id VARCHAR NOT NULL, version VARCHAR NOT NULL, page INTEGER NOT NULL,
        type_page VARCHAR NOT NULL, motif VARCHAR NOT NULL, methode VARCHAR NOT NULL,
        ocr_secondes DECIMAL(10,2), ocr_tokens INTEGER, markdown VARCHAR NOT NULL,
        PRIMARY KEY (document_id, version, page)""",
}

def split_pages(markdown: str) -> list[str]:
    """Text of each page, without the page markers of bronze."""
    return [p.strip() for p in re.split(r"<!-- page: \d+ -->", markdown)[1:]]


def bronze_rows(store: Path) -> tuple[dict[str, list[tuple]], list[str]]:
    rows: dict[str, list[tuple]] = {name: [] for name in TABLES}
    unusable = []
    for path in sorted(store.glob("*/*/*.json")):
        if path.parent.parent.name.startswith("."):
            continue
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
            data = path.with_suffix(".md").read_bytes()
            if hashlib.sha256(data).hexdigest() != r["markdown_sha256"]:
                raise ValueError("Markdown modified since its extraction")
            texts = split_pages(data.decode("utf-8"))
            if len(texts) != r["page_count"] or len(r["pages"]) != r["page_count"]:
                raise ValueError("page count does not match")
            version, origin = path.parent.name, r.get("origin") or {}
            ocr, text = r["settings"].get("ocr") or {}, r["settings"].get("text") or {}
            extraction = (
                r["sha256"], version, r["source"], origin.get("s3_key"), origin.get("etag"),
                origin.get("last_modified"), origin.get("pulled_at"), r["converted_at"],
                r["kind"], r.get("size"), r["page_count"], r["repaired"],
                ocr.get("engine"), ocr.get("model"), ocr.get("max_side"),
                ocr.get("image_format"), text.get("engine"), text.get("version"),
                r["markdown_sha256"])
            pages = [
                (r["sha256"], version, p["page"], p["kind"], p["reason"], p["method"],
                 p.get("seconds"), _tokens(p), texts[i])
                for i, p in enumerate(r["pages"])]
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            unusable.append(f"{path}: {exc!r}")
            continue
        rows["bronze_extractions"].append(extraction)
        rows["bronze_pages"] += pages
    return rows, unusable


def _tokens(page: dict[str, Any]) -> int | None:
    usage = (page.get("ocr_response") or {}).get("usage") or {}
    return usage.get("completion_tokens")


def _quote(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def _write_files(rows: dict[str, list[tuple]], folder: Path) -> None:
    with duckdb.connect() as db:
        db.execute("SET threads = 1")       # same data, same bytes
        db.execute("SET TimeZone = 'UTC'")
        for name, definition in TABLES.items():
            db.execute(f"CREATE TABLE {name} ({definition})")
            if rows[name]:
                marks = ", ".join("?" * len(rows[name][0]))
                db.executemany(f"INSERT INTO {name} VALUES ({marks})", rows[name])
            path = _quote(folder / f"{name}.parquet")
            query = f"SELECT * FROM {name} ORDER BY ALL"
            db.execute(f"COPY ({query}) TO {path} (FORMAT parquet)")
            written = db.execute(f"SELECT * FROM {path} ORDER BY ALL").fetchall()
            if written != db.execute(query).fetchall():
                raise RuntimeError(f"{name}.parquet does not read back identically")


def export(store: Path, silver: Path, out: Path) -> tuple[dict[str, int], list[str]]:
    """Write every table; return the rows per table and the unusable records."""
    rows, unusable = bronze_rows(store)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".tmp-{uuid.uuid4().hex}"
    tmp.mkdir()
    try:
        _write_files(rows, tmp)
        silver_counts = write(analyse(store), silver)
        for path in sorted(tmp.iterdir()):
            os.replace(path, out / path.name)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {name: len(r) for name, r in rows.items()} | silver_counts, unusable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="warehouse.export_parquet",
        description="Aggregate every extraction into Parquet tables.")
    parser.add_argument("source", type=Path, nargs="?", default=BRONZE, help="bronze store")
    parser.add_argument("--out", type=Path, default=OUT, help="where to write the bronze tables")
    parser.add_argument("--silver", type=Path, default=SILVER,
                        help="where the silver tables are refreshed")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    if not args.source.is_dir():
        log.error("no bronze store in %s", args.source)
        return 2
    try:
        counts, unusable = export(args.source, args.silver, args.out)
    except (OSError, ValueError, RuntimeError, duckdb.Error) as exc:
        log.error("%s", exc)
        return 2
    for message in unusable:
        log.error("unusable bronze record: %s", message)
    print(json.dumps({"rows": counts, "unusable": len(unusable)}))
    return int(bool(unusable))


if __name__ == "__main__":
    sys.exit(main())
