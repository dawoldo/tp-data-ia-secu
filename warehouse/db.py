"""SQL access to the bronze and silver tables, with DuckDB.

    python -m warehouse.db build            # (re)create the database for DBeaver
    python -m warehouse.db query "SQL"      # run a query from a terminal

The data stays in the Parquet files; the database only holds views on them. Programs
call connect(), which needs no database file: whoever has entrepot.duckdb open, in
whatever mode, cannot block them.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from pathlib import Path

import duckdb

# Where the data is, whatever the machine or container.
DATA = Path(os.environ.get("FACTURES_DIR") or Path(__file__).resolve().parent.parent / "factures")
DATABASE = "warehouse/entrepot.duckdb"

# view -> (Parquet file, description)
VIEWS = {
    "silver.factures": (
        "silver/factures.parquet",
        "Une ligne par facture exploitable. Filtrer statut_qualite = 'valide' pour des totaux "
        "fiables ; 'signalee' = douteuse, voir silver.anomalies."),
    "silver.lignes_facture": (
        "silver/lignes_facture.parquet", "Lignes des factures, liées par facture_id."),
    "silver.tva_facture": (
        "silver/tva_facture.parquet", "Montant de TVA par taux, lié par facture_id."),
    "silver.anomalies": (
        "silver/anomalies.parquet", "Problèmes relevés par les contrôles qualité."),
    "silver.rejets": (
        "silver/rejets.parquet", "Quarantaine : documents écartés, avec le motif."),
    "bronze.extractions": (
        "warehouse/bronze_extractions.parquet",
        "Toutes les extractions : origine S3, réglages, empreintes. "
        "document_id + version = silver.factures.facture_id + bronze_version."),
    "bronze.pages": (
        "warehouse/bronze_pages.parquet", "Texte brut extrait de chaque page."),
}


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def create_views(db: duckdb.DuckDBPyConnection, data: Path) -> None:
    for schema in sorted({name.split(".")[0] for name in VIEWS}):
        db.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    for name, (file, description) in VIEWS.items():
        path = data.resolve() / file
        if not path.is_file():
            raise FileNotFoundError(f"{path} is missing: run python -m warehouse.export_parquet")
        db.execute(f"CREATE VIEW {name} AS SELECT * FROM read_parquet({_literal(str(path))})")
        db.execute(f"COMMENT ON VIEW {name} IS {_literal(description)}")


def connect(data: Path = DATA) -> duckdb.DuckDBPyConnection:
    """An in-memory connection with every view; nothing is shared with other processes."""
    db = duckdb.connect()
    try:
        create_views(db, data)
    except Exception:
        db.close()
        raise
    return db


def build(data: Path = DATA) -> Path:
    """Create the database file for graphical tools. Replaces it in one go.

    The views hold absolute paths, because a tool may open the file from anywhere:
    build it again on each machine instead of copying it.
    """
    target = data / DATABASE
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{uuid.uuid4().hex}.duckdb")
    try:
        with duckdb.connect(str(tmp)) as db:
            create_views(db, data)
            db.execute("CHECKPOINT")
        os.replace(tmp, target)
    finally:
        for leftover in (tmp, tmp.with_name(tmp.name + ".wal")):
            leftover.unlink(missing_ok=True)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="warehouse.db", description="SQL access to the tables.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("build", help="create the database for graphical tools")
    cmd = commands.add_parser("query", help="run one query and print the result")
    cmd.add_argument("sql")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            path = build()
            print(f"{path}: {len(VIEWS)} views")
        else:
            with connect() as db:
                result = db.sql(args.sql)
                if result is not None:
                    print(result)
    except (OSError, duckdb.Error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
