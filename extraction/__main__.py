"""Command line: python -m extraction {classify,ocr-page,convert,verify} ...

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

from .bronze import BronzeError, BronzeStore
from .convert import convert_folder
from .ocr import OcrConfigError, OcrError, engine_from_env
from .pdf import PdfError, find_pdfs
from .worker import PdfWorker

ROOT = Path(__file__).resolve().parent.parent
LANDING = ROOT / "factures" / "landing"
BRONZE = ROOT / "factures" / "bronze"


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="extraction", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    ocr = argparse.ArgumentParser(add_help=False)
    ocr.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ocr.add_argument("--max-side", type=positive_int, help="image size in pixels (default 1540)")
    ocr.add_argument("--image-format", choices=("png", "jpeg"), help="default png")

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
    return parser.parse_args(argv)


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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    try:
        if args.command != "verify":
            source = args.file if args.command == "ocr-page" else args.source
            if not source.exists():
                raise PdfError(f"{source} does not exist")
            if not find_pdfs(source):
                raise PdfError(f"no PDF in {source}")
        commands = {"classify": run_classify, "ocr-page": run_ocr_page,
                    "convert": run_convert, "verify": run_verify}
        return commands[args.command](args)
    except OcrError as exc:
        logging.error("OCR: %s", exc)
        return 1
    except (OcrConfigError, BronzeError, PdfError, OSError) as exc:
        logging.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
