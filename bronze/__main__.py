"""Command line: python -m bronze {pull,classify,ocr-page,convert,verify,tables} ...

Results go to stdout, logs to stderr.
Exit code: 0 = all good, 1 = some files failed, wait for OCR or are damaged,
2 = configuration or input error.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from paths import BRONZE, BRONZE_TABLES, ENV_FILE, LANDING

from .extraction.ocr import OcrConfigError, OcrError, engine_from_env
from .extraction.pdf import PdfError, find_pdfs
from .extraction.worker import PdfWorker
from .pipeline import convert_folder
from .storage.store import BronzeError, BronzeStore


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bronze", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ocr = argparse.ArgumentParser(add_help=False)
    ocr.add_argument("--env-file", type=Path, default=ENV_FILE)
    ocr.add_argument("--max-side", type=positive_int, help="image size in pixels (default 1540)")
    ocr.add_argument("--image-format", choices=("png", "jpeg"), help="default png")

    cmd = commands.add_parser("pull", help="download new invoices from S3")
    cmd.add_argument("--dest", type=Path, default=LANDING, help="landing directory")
    cmd.add_argument("--env-file", type=Path, default=ENV_FILE, help="settings file")
    cmd.add_argument("--prefix", default="", help="only pull keys with this prefix")
    cmd.add_argument("--limit", type=positive_int, help="pull at most N files")
    cmd.add_argument("--dry-run", action="store_true", help="list without downloading")

    cmd = commands.add_parser("classify", help="text or image, for each PDF")
    cmd.add_argument("source", type=Path, nargs="?", default=LANDING)
    cmd.add_argument("--json", action="store_true", help="include the measurements")

    cmd = commands.add_parser("ocr-page", parents=[ocr], help="OCR one page and print it")
    cmd.add_argument("file", type=Path)
    cmd.add_argument("--page", type=positive_int, default=1)

    cmd = commands.add_parser("convert", parents=[ocr], help="fill the bronze store")
    cmd.add_argument("source", type=Path, nargs="?", default=LANDING)
    cmd.add_argument("--out", type=Path, default=BRONZE, help="bronze store")
    cmd.add_argument("--limit", type=positive_int, help="convert at most N new files")
    cmd.add_argument("--no-ocr", action="store_true", help="only convert text PDFs")
    cmd.add_argument("--dry-run", action="store_true",
                     help="show what would be done, without writing or calling OCR")
    cmd.add_argument("--timeout", type=positive_int, default=120,
                     help="seconds allowed to parse one PDF (default 120)")
    cmd.add_argument("--max-pages", type=positive_int, default=100,
                     help="refuse longer PDFs (default 100)")

    cmd = commands.add_parser("verify", help="check that no bronze record changed or vanished")
    cmd.add_argument("store", type=Path, nargs="?", default=BRONZE)

    cmd = commands.add_parser("tables", help="write the bronze tables as Parquet")
    cmd.add_argument("store", type=Path, nargs="?", default=BRONZE)
    cmd.add_argument("--out", type=Path, default=BRONZE_TABLES, help="where to write them")
    return parser.parse_args(argv)


# boto3 and DuckDB are slow to load and each serves one command: imported there only.

def run_pull(args: argparse.Namespace) -> int:
    from .ingestion import pull

    return pull.run(args)


def run_classify(args: argparse.Namespace) -> int:
    failed = False
    with PdfWorker() as worker:
        for path in find_pdfs(args.source):
            kind, pages, error = "error", [], ""
            try:
                analysis = worker.analyse(path.read_bytes(), with_text=False)
                kind, pages = analysis["kind"], analysis["pages"]
            except (PdfError, OSError) as exc:
                error, failed = str(exc), True
            if args.json:
                print(json.dumps({"file": str(path), "kind": kind, "pages": pages,
                                  "error": error}, ensure_ascii=False))
            else:
                reasons = error or ", ".join(sorted({p["reason"] for p in pages}))
                print(f"{kind:<6} {path.name}  ({reasons})")
    return int(failed)


def run_ocr_page(args: argparse.Namespace) -> int:
    engine = engine_from_env(args.env_file, max_side=args.max_side,
                             image_format=args.image_format)
    with PdfWorker() as worker:
        image = worker.render_page(args.file.read_bytes(), engine.render_spec, args.page)
    result = engine.read_image(image)
    print(result.text)
    logging.info("%.2f s, usage: %s", result.seconds, result.raw.get("usage"))
    return 0


def run_convert(args: argparse.Namespace) -> int:
    engine = None
    if not args.no_ocr:
        engine = engine_from_env(args.env_file, max_side=args.max_side,
                                 image_format=args.image_format)
    summary = convert_folder(
        args.source, BronzeStore(args.out), engine, limit=args.limit,
        dry_run=args.dry_run, timeout=args.timeout, max_pages=args.max_pages,
    )
    print(json.dumps(summary, ensure_ascii=False))
    return int(any(summary[k] for k in ("failed", "pending_ocr", "damaged")))


def run_verify(args: argparse.Namespace) -> int:
    if not args.store.is_dir():
        raise BronzeError(f"no bronze store in {args.store}")
    intact, problems = BronzeStore(args.store).verify()
    for problem in problems:
        print(problem)
    print(f"{intact} intact record(s), {len(problems)} problem(s)")
    return int(bool(problems))


def run_tables(args: argparse.Namespace) -> int:
    import duckdb

    from .storage.tables import write_tables

    if not args.store.is_dir():
        raise BronzeError(f"no bronze store in {args.store}")
    try:
        counts, unusable = write_tables(args.store, args.out)
    except duckdb.Error as exc:
        raise BronzeError(f"cannot write the tables: {exc}") from exc
    for message in unusable:
        logging.error("unusable bronze record: %s", message)
    print(json.dumps({"rows": counts, "unusable": len(unusable)}))
    return int(bool(unusable))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    try:
        if args.command not in ("pull", "verify", "tables"):
            source = args.file if args.command == "ocr-page" else args.source
            if not source.exists():
                raise PdfError(f"{source} does not exist")
            if not find_pdfs(source):
                raise PdfError(f"no PDF in {source}")
        commands = {"pull": run_pull, "tables": run_tables, "classify": run_classify, "ocr-page": run_ocr_page,
                    "convert": run_convert, "verify": run_verify}
        return commands[args.command](args)
    except OcrError as exc:
        logging.error("OCR: %s", exc)
        return 1
    except (OcrConfigError, BronzeError, PdfError, OSError, RuntimeError) as exc:
        logging.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
