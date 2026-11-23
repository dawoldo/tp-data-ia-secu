"""Everything that parses a PDF. Runs inside the worker process (worker.py)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pymupdf

from . import text
from .classify import IMAGE, classify_page


class PdfError(Exception):
    """The PDF itself is unusable."""


@dataclass(frozen=True)
class RenderSpec:
    """How an OCR engine wants its page images."""

    max_side: int         # pixels, longest side
    image_format: str     # "png" or "jpeg"


def find_pdfs(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")


def open_pdf(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except (RuntimeError, ValueError) as exc:  # PyMuPDF errors derive from these
        raise PdfError(f"cannot open: {exc}") from exc
    if not doc.is_pdf:  # PyMuPDF also opens HTML, images... whatever the extension
        raise PdfError("not a PDF")
    if doc.needs_pass:
        raise PdfError("password protected")
    if not doc.page_count:
        raise PdfError("no pages")
    return doc


def render(page: pymupdf.Page, spec: RenderSpec) -> bytes:
    zoom = spec.max_side / max(page.rect.width, page.rect.height)
    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    if spec.image_format == "jpeg":
        return pixmap.tobytes("jpeg", jpg_quality=90)
    return pixmap.tobytes("png")


def analyse(
    data: bytes, spec: RenderSpec | None, with_text: bool, max_pages: int
) -> dict[str, Any]:
    """Classify every page and prepare its content.

    Text pages get "markdown" and "missing_words" if with_text is set; pages
    that need OCR get "image" if spec is given.
    """
    with open_pdf(data) as doc:
        if doc.page_count > max_pages:
            raise PdfError(f"{doc.page_count} pages, more than the limit of {max_pages}")
        pages = []
        for index, page in enumerate(doc):
            info = asdict(classify_page(page))
            if info["kind"] == IMAGE:
                if spec is not None:
                    info["image"] = render(page, spec)
            elif with_text:
                info["markdown"], info["missing_words"] = text.page_to_markdown(doc, index)
            pages.append(info)
        kind = IMAGE if any(p["kind"] == IMAGE for p in pages) else "text"
        return {"kind": kind, "repaired": doc.is_repaired, "pages": pages}


def render_page(data: bytes, spec: RenderSpec, number: int) -> bytes:
    """Image of one page (1-based), whatever its class."""
    with open_pdf(data) as doc:
        if not 1 <= number <= doc.page_count:
            raise PdfError(f"page {number} does not exist ({doc.page_count} page(s))")
        return render(doc[number - 1], spec)
