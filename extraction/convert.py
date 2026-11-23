"""Fill the bronze store from a folder of PDFs.

Known PDFs are skipped, whatever their name; failures are retried next time.
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
from typing import Any

from . import text_to_md
from .bronze import BronzeError, BronzeStore, DamagedRecord, now, sha256
from .classify import IMAGE
from .ocr import OcrEngine, OcrError, OcrUnavailable
from .pdf import PdfError, find_pdfs
from .worker import PdfWorker

log = logging.getLogger(__name__)

MAX_CONSECUTIVE_OUTAGES = 3
MANIFEST_NAME = "manifest.json"


class Landing:
    """Where PDFs come from, according to the manifest of pull-factures.py."""

    def __init__(self, source: Path) -> None:
        source = source.resolve()
        self.root = source.parent if source.is_file() else source
        self._entries: dict[str, dict[str, Any]] = {}
        if (self.root / MANIFEST_NAME).is_file():
            self._entries = self._read(self.root / MANIFEST_NAME)
            return
        # Part of a landing zone? Only trust a manifest that knows these files.
        for folder in self.root.parents:
            if (folder / MANIFEST_NAME).is_file():
                with contextlib.suppress(BronzeError):
                    entries = self._read(folder / MANIFEST_NAME)
                    if any((folder / name).is_relative_to(source) for name in entries):
                        self.root, self._entries = folder, entries
                        return

    @staticmethod
    def _read(path: Path) -> dict[str, dict[str, Any]]:
        entries = {}
        try:
            for key, versions in json.loads(path.read_text(encoding="utf-8")).items():
                for v in versions:
                    entries[v["path"]] = {
                        "s3_key": key, "sha256": v["sha256"],
                        **{k: v[k] for k in ("etag", "last_modified", "pulled_at")},
                    }
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise BronzeError(f"unreadable manifest {path}: {exc!r}") from exc
        return entries

    def name(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()

    def origin(self, name: str, digest: str) -> dict[str, Any] | None:
        entry = self._entries.get(name)
        if entry is None:
            return None
        if entry["sha256"] != digest:
            raise PdfError("differs from what was downloaded; run pull-factures.py again")
        return {k: v for k, v in entry.items() if k != "sha256"}


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
            settings["text"] = text_to_md.SETTINGS
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
    current = {"text": text_to_md.SETTINGS, "ocr": engine.settings if engine else None}

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
