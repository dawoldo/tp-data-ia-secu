"""Command line: python -m warehouse {refresh,build,query} ...

Exit code: 0 = done, 1 = done, but some documents are rejected or unusable, 2 = failed.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import duckdb

from bronze.storage.tables import write_tables
from paths import BRONZE, BRONZE_TABLES, SILVER
from silver.tables import analyse, summary, write

from .db import VIEWS, build, connect


def run_refresh(_: argparse.Namespace) -> int:
    """Rebuild every table from the bronze store."""
    if not BRONZE.is_dir():
        raise FileNotFoundError(f"no bronze store in {BRONZE}")
    counts, unusable = write_tables(BRONZE, BRONZE_TABLES)
    for message in unusable:
        logging.error("unusable bronze record: %s", message)
    silver = analyse(BRONZE)
    counts |= write(silver, SILVER)
    rejected = summary(silver)["rejetees"]
    print(json.dumps({"rows": counts, "unusable": len(unusable), "rejetees": rejected}))
    return int(bool(unusable or rejected))


def run_build(_: argparse.Namespace) -> int:
    print(f"{build()}: {len(VIEWS)} views")
    return 0


def run_query(args: argparse.Namespace) -> int:
    with connect() as db:
        result = db.sql(args.sql)
        if result is not None:
            print(result)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="warehouse", description="SQL access to the tables.")
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("refresh", help="rebuild the bronze and silver tables")
    cmd.set_defaults(run=run_refresh)
    cmd = commands.add_parser("build", help="create the database for graphical tools")
    cmd.set_defaults(run=run_build)
    cmd = commands.add_parser("query", help="run one query and print the result")
    cmd.add_argument("sql")
    cmd.set_defaults(run=run_query)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    try:
        return args.run(args)
    except (OSError, ValueError, RuntimeError, duckdb.Error) as exc:
        logging.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
