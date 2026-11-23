"""Decide, page by page, whether a PDF has a usable text layer or needs OCR.

The decision uses the page content, never the file name.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

TEXT = "text"
IMAGE = "image"

MIN_CHARS = 50            # fewer visible characters is suspicious on a page with graphics
MAX_UNREADABLE = 0.10     # share of characters with no usable Unicode value
FULL_PAGE_IMAGE = 0.80    # share of the page covered by images
INVISIBLE = 3             # PDF text render mode used by hidden OCR layers


@dataclass(frozen=True)
class PageClass:
    page: int             # 1-based
    kind: str             # TEXT or IMAGE
    reason: str
    visible_chars: int
    hidden_chars: int
    unreadable_ratio: float
    image_coverage: float


def _is_unreadable(code: int) -> bool:
    return code in (0, 0xFFFD) or 0xE000 <= code <= 0xF8FF


def classify_page(page: pymupdf.Page) -> PageClass:
    visible = hidden = unreadable = 0
    for span in page.get_texttrace():
        codes = [c[0] for c in span["chars"] if not chr(c[0]).isspace()]
        if span["type"] == INVISIBLE or span["opacity"] == 0:
            hidden += len(codes)
        else:
            visible += len(codes)
            unreadable += sum(map(_is_unreadable, codes))

    images = [pymupdf.Rect(i["bbox"]) & page.rect for i in page.get_image_info()]
    area = sum(r.get_area() for r in images if not r.is_empty)
    coverage = min(1.0, area / page.rect.get_area())  # scans may come in strips
    ratio = unreadable / visible if visible else 0.0

    if coverage >= FULL_PAGE_IMAGE:
        # Any text here is a stamp or unverified OCR, so it cannot be trusted.
        kind, reason = IMAGE, "full-page image"
    elif ratio > MAX_UNREADABLE:
        kind, reason = IMAGE, "unreadable text layer"
    elif visible < MIN_CHARS and (images or page.get_drawings()):
        kind, reason = IMAGE, "too little text for a page with graphics"
    else:
        kind, reason = TEXT, "text layer" if visible else "blank page"

    return PageClass(
        page.number + 1, kind, reason, visible, hidden,
        round(ratio, 3), round(coverage, 3),
    )


def classify_document(doc: pymupdf.Document) -> tuple[str, list[PageClass]]:
    """A document is IMAGE as soon as one of its pages needs OCR."""
    pages = [classify_page(page) for page in doc]
    kind = IMAGE if any(p.kind == IMAGE for p in pages) else TEXT
    return kind, pages
