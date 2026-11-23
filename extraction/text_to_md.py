"""Markdown from a native text layer, using PyMuPDF.

The layout model is off on purpose: on these invoices it merged the supplier
and client columns into one paragraph and dropped the line breaks.
"""

from __future__ import annotations

import re

import pymupdf

pymupdf.use_layout(False)

SETTINGS = {"engine": "pymupdf", "version": pymupdf.__version__, "layout": False}


def _bare(text: str) -> str:
    """Text without whitespace or Markdown/HTML markup, for comparison."""
    return re.sub(r"</?\w+>|[\s|*#_\\`~-]", "", text)


def page_to_markdown(doc: pymupdf.Document, index: int) -> tuple[str, list[str]]:
    """Return the Markdown of one page (0-based) and the words it lost, if any."""
    markdown = doc.to_markdown(pages=[index], show_progress=False)
    bare = _bare(markdown)
    words = (_bare(w) for w in doc[index].get_text().split())
    return markdown.strip(), [w for w in words if w and w not in bare]
