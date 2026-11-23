"""Fill the bronze store from a folder of PDFs.

Known PDFs are skipped, whatever their name; failures are retried next time.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import Any

from .extraction import text
from .extraction.classify import IMAGE
from .extraction.ocr import OcrEngine, OcrError, OcrUnavailable
from .extraction.pdf import PdfError, find_pdfs
from .extraction.worker import PdfWorker
from .ingestion.manifest import Landing
from .storage.store import BronzeStore, DamagedRecord, now, sha256

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_OUTAGES = 3


def extract(
    data: bytes, worker: PdfWorker, engine: OcrEngine | None
) -> tuple[str, dict[str, Any]]:
    """Return the Markdown of one PDF and the facts about its extraction."""
    if engine is None and worker.analyse(data, with_text=False)["kind"] == IMAGE:
        raise OcrUnavailable("OCR is switched off for this run")
    analysis = worker.analyse(data, engine.render_spec if engine else None)
    parts: list[str] = []
    pages: list[dict[str, Any]] = []
    settings: dict[str, Any] = {}
    for info in analysis["pages"]:
        if info["kind"] == IMAGE:
            assert engine is not None
            image = info.pop("image")
            result = engine.read_image(image)
            markdown = result.text
            info.update(method="ocr", seconds=round(result.seconds, 2),
                        image_sha256=sha256(image), ocr_response=result.raw)
            settings["ocr"] = engine.settings
        else:
            markdown = info.pop("markdown")
            info["method"] = "text"
            settings["text"] = text.SETTINGS
        # Text that imitates our page marker must not create a fake page.
        markdown = markdown.replace("<!-- page:", "<!-- page :")
        parts.append(f"<!-- page: {info['page']} -->\n\n{markdown}\n")
        pages.append(info)
    return "\n".join(parts), {
        "kind": analysis["kind"], "page_count": len(pages),
        "repaired": analysis["repaired"], "settings": settings,
        "converted_at": now(), "pages": pages,
    }


def convert_folder(
    source: Path,
    store: BronzeStore,
    engine: OcrEngine | None,
    limit: int | None = None,
    dry_run: bool = False,
    timeout: float = 120,
    max_pages: int = 100,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "text": 0, "image": 0, "skipped": 0, "duplicates": [], "repaired": [],
        "pending_ocr": [], "damaged": [], "failed": {}, "ocr_calls": 0, "dry_run": dry_run,
    }
    current = {"text": text.SETTINGS, "ocr": engine.settings if engine else None}

    def accept(settings: dict[str, Any]) -> bool:
        return all(current[m] is None or current[m] == s for m, s in settings.items())

    def fail(name: str, exc: Exception) -> None:
        log.error("%s: %s", name, exc)
        if not dry_run:
            store.log_error(name, exc)

    landing = Landing(source)
    converted = outages = 0
    planned: set[str] = set()  # dry run: PDFs counted once, whatever their names
    lock = contextlib.nullcontext() if dry_run else store.locked()
    with lock, PdfWorker(timeout, max_pages) as worker:
        for path in find_pdfs(source):
            name = landing.name(path)
            try:
                data = path.read_bytes()
                digest = sha256(data)
                origin = landing.origin(name, digest)
                known = store.find(digest, accept)
                if known or digest in planned:
                    if known and known["source"] == name:
                        summary["skipped"] += 1
                    else:
                        summary["duplicates"].append(name)
                    if not dry_run:
                        store.note_source(digest, name, origin)
                    continue
                if limit is not None and converted >= limit:
                    break
                if dry_run:
                    analysis = worker.analyse(data, with_text=False)
                    kind, repaired = analysis["kind"], analysis["repaired"]
                    calls = sum(p["kind"] == IMAGE for p in analysis["pages"])
                    if calls and engine is None:
                        raise OcrUnavailable("OCR is switched off for this run")
                    planned.add(digest)
                else:
                    markdown, facts = extract(data, worker, engine)
                    store.add(path.name, markdown, {
                        "source": name, "origin": origin, "sha256": digest,
                        "size": len(data), **facts,
                    })
                    store.note_source(digest, name, origin)
                    if origin is None:
                        log.warning("%s: not in a download manifest, S3 origin unknown", name)
                    kind, repaired = facts["kind"], facts["repaired"]
                    calls = sum(p["method"] == "ocr" for p in facts["pages"])
                    for page in facts["pages"]:
                        if page.get("missing_words"):
                            log.warning("%s page %d: %d word(s) missing from the Markdown",
                                        name, page["page"], len(page["missing_words"]))
            except DamagedRecord as exc:
                summary["damaged"].append(name)
                fail(name, exc)
            except OcrUnavailable as exc:
                summary["pending_ocr"].append(name)
                if engine is not None:  # a deliberate skip is not an error
                    fail(name, exc)
                    outages += 1
                    if outages >= MAX_CONSECUTIVE_OUTAGES:
                        log.error("OCR unavailable %d times in a row: scans wait for "
                                  "the next run, text PDFs continue", outages)
                        engine = None
            except (OcrError, PdfError, OSError) as exc:
                summary["failed"][name] = str(exc)
                fail(name, exc)
            else:
                converted += 1
                summary[kind] += 1
                summary["ocr_calls"] += calls
                if calls:
                    outages = 0
                if repaired:
                    log.warning("%s: damaged PDF, repaired on opening; content may be "
                                "missing", name)
                    summary["repaired"].append(name)
                log.info("%s: %s", name, kind)
    return summary
