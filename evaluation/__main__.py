"""Command line: python -m evaluation run

Prepares the scans, calls the OCR for what is missing, compares with the ground
truth, prints the tables and writes them to evaluation/resultats.md.
Exit code: 0 = complete, 1 = some pages are waiting for the OCR, 2 = input error.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from bronze.extraction.ocr import OcrConfigError, engine_from_env
from bronze.pipeline import convert_folder
from bronze.storage.store import BronzeError, BronzeStore
from paths import BRONZE, ENV_FILE, LANDING
from paths import EVALUATION as WORK
from silver.models import Facture, LigneFacture, Partie, TotalTva
from silver.parsing.parser import parse_invoice
from silver.reader import read_documents
from silver.tables import analyse

from .compare import Score
from .report import render
from .synth import pick, prepare

TRUTH = Path(__file__).parent / "verite" / "scans_reels.json"
RESULTS = Path(__file__).parent / "resultats.md"
DEFAULT_SIDE = 1540                  # the size the pipeline uses

log = logging.getLogger("evaluation")


class EvaluationError(Exception):
    """The evaluation cannot run."""


def _facture(raw: dict[str, Any]) -> Facture:
    amounts = {k: Decimal(raw[k]) for k in ("total_ht", "total_tva", "total_ttc")}
    dates = {k: date.fromisoformat(raw[k]) for k in ("date_emission", "date_echeance")}
    texts = {k: raw[k] for k in ("numero", "categorie", "statut", "mode_paiement", "iban")}
    return Facture(
        **texts, **dates, **amounts,
        detail_tva=[TotalTva(Decimal(t), Decimal(m)) for t, m in raw["detail_tva"]],
        fournisseur=Partie(**raw["fournisseur"]), client=Partie(**raw["client"]),
        lignes=[LigneFacture(i, d, Decimal(q), Decimal(u), Decimal(t), Decimal(h))
                for i, (d, q, u, t, h) in enumerate(raw["lignes"], 1)],
    )


def real_truth() -> dict[str, Facture]:
    raw = json.loads(TRUTH.read_text(encoding="utf-8"))["factures"]
    return {name: _facture(f) for name, f in raw.items()}


def synthetic_truth(count: int) -> dict[str, Facture]:
    """Truth of the synthetic scans: the text layer of the PDFs they come from."""
    native = {r["source"]: md for md, r in read_documents(BRONZE)[0] if r["kind"] == "text"}
    scans = prepare(LANDING, pick(list(native), count), WORK / "synthetique")
    truth = {}
    for scan, source in scans.items():
        result = parse_invoice(native[source])
        if result.issues:
            raise EvaluationError(f"{source} cannot serve as truth: {result.issues}")
        truth[scan] = result.facture
    return truth


def _copy_real(names: list[str]) -> Path:
    folder = WORK / "reel"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        if not (folder / name).exists():
            shutil.copyfile(LANDING / name, folder / name)
    return folder


def evaluate(
    series: str, truth: dict[str, Facture], side: int, env_file: Path, use_ocr: bool
) -> tuple[Score, list[str]]:
    """Score one series at one image size, and the scans still waiting for OCR."""
    if series == "reel" and side == DEFAULT_SIDE:
        store, failed, pending = BRONZE, set(), set()  # the real silver input, no OCR call
    else:
        folder = _copy_real(list(truth)) if series == "reel" else WORK / "synthetique"
        store = WORK / "bronze" / f"{series}-{side}"
        engine = engine_from_env(env_file, max_side=side) if use_ocr else None
        summary = convert_folder(folder, BronzeStore(store), engine)
        failed, pending = set(summary["failed"]), set(summary["pending_ocr"])
        if summary["damaged"]:
            raise EvaluationError(f"damaged records in {store}: {summary['damaged']}")
    silver = analyse(store)
    found = {}
    for d in silver.documents:
        if d.record["kind"] == "image" and d.record["settings"]["ocr"]["max_side"] == side:
            found[d.record["source"]] = d
    score = Score()
    for name, expected in sorted(truth.items()):
        doc = found.get(name)
        if doc is None:
            if name in failed:
                score.add(name, expected, None, "illisible")
            else:
                pending.add(name)
            continue
        state = "rejetee" if doc.rejete else "signalee" if doc.anomalies else "valide"
        score.add(name, expected, doc.facture, state)
        score.seconds += [p["seconds"] for p in doc.record["pages"] if p["method"] == "ocr"]
    return score, sorted(pending & truth.keys())


def run(args: argparse.Namespace) -> int:
    truths = {"reel": real_truth(), "synth.": synthetic_truth(args.synthetic)}
    scores, waiting = {}, []
    for series, truth in truths.items():
        key = "synthetique" if series == "synth." else series
        for side in args.sides:
            scores[series, side], pending = evaluate(
                key, truth, side, args.env_file, not args.no_ocr)
            waiting += [f"{series} {side} px: {name}" for name in pending]
    text = render(scores)
    print(text)
    if waiting:
        log.error("%d scan(s) wait for the OCR; incomplete results are not saved. First: %s",
                  len(waiting), waiting[0])
        return 1
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="evaluation", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    cmd = commands.add_parser("run", help="measure the OCR against the ground truth")
    cmd.add_argument("--sides", type=int, nargs="+", default=[650, 800, 1540, 2339],
                     help="image sizes to compare, in pixels (default: 650 800 1540 2339)")
    cmd.add_argument("--synthetic", type=int, default=20, help="synthetic scans (default 20)")
    cmd.add_argument("--no-ocr", action="store_true", help="only use results already there")
    cmd.add_argument("--env-file", type=Path, default=ENV_FILE)
    cmd.add_argument("--out", type=Path, default=RESULTS, help="where to save the tables")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s")
    try:
        return run(args)
    except (EvaluationError, BronzeError, OcrConfigError, OSError, ValueError, KeyError) as exc:
        log.error("%s", exc or repr(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
