"""Reduce any bronze Markdown to plain text lines and table rows, in order.

Text PDFs and OCR differ in bold, headings, separators, pipe or HTML tables.
All of that presentation is removed here, so the parser sees a single form.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser


@dataclass
class Table:
    rows: list[list[str]]


Block = str | Table

_HTML_TABLE = re.compile(r"<table\b.*?</table\s*>", re.S | re.I)
_PIPE_RULE = re.compile(r"\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?")
_SEPARATOR = re.compile(r"[-*_=\s]{3,}")


def fold(text: str) -> str:
    """Lower case without accents, same length as the input."""
    out = []
    for char in text:
        base = unicodedata.normalize("NFD", char)[0].lower()
        out.append(base if len(base) == 1 else char)
    return "".join(out).replace("’", "'").replace("`", "'")


def clean(text: str) -> str:
    """Remove inline markup and unify spaces."""
    text = unescape(text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)                # image placeholder
    text = re.sub(r"</?(?:u|b|i|em|strong|sup|sub|span|p|div)\b[^>]*>", "", text, flags=re.I)
    text = re.sub(r"\*\*|__|~~|`", "", text)
    text = re.sub(r"(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", text)      # *italic*
    text = re.sub(r"\\([\\*_#|~.()\[\]{}+\-!])", r"\1", text)        # escapes
    text = unicodedata.normalize("NFC", text).replace("​", "")
    return re.sub(r"\s+", " ", text).strip()                         # covers NBSP


class _TableReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None
        self._span = 1
        self._open = False  # inside a row; a cell outside one starts a new row

    def _end_cell(self) -> None:
        if self._cell is not None and self.rows:
            self.rows[-1] += ["".join(self._cell).strip()] + [""] * (self._span - 1)
        self._cell = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._end_cell()
            self.rows.append([])
            self._open = True
        elif tag in ("td", "th"):
            self._end_cell()
            if not self._open:
                self.rows.append([])
                self._open = True
            span = dict(attrs).get("colspan") or "1"
            self._span = min(int(span), 20) if span.isdigit() and int(span) else 1
            self._cell = []
        elif tag == "br" and self._cell is not None:
            self._cell.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th", "tr", "table"):
            self._end_cell()
        if tag in ("tr", "table"):
            self._open = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(re.sub(r"\s+", " ", data))


def _html_rows(html: str) -> list[list[str]]:
    reader = _TableReader()
    reader.feed(html)
    reader.close()
    return [row for row in reader.rows if any(row)]


def _pipe_cells(line: str) -> list[str]:
    inner = line.strip().removeprefix("|")
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    cells = re.split(r"(?<!\\)\|", inner)
    return [re.sub(r"<br\s*/?>", "\n", c, flags=re.I).strip() for c in cells]


def _text_blocks(text: str) -> list[Block]:
    blocks: list[Block] = []
    for line in re.sub(r"<br\s*/?>(?![^\n]*\|)", "\n", text, flags=re.I).splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            if _PIPE_RULE.fullmatch(stripped):
                continue
            cells = _pipe_cells(stripped)
            if blocks and isinstance(blocks[-1], Table):
                blocks[-1].rows.append(cells)
            else:
                blocks.append(Table([cells]))
            continue
        if not stripped:
            # A blank line ends a pipe table.
            blocks.append("")
            continue
        if _SEPARATOR.fullmatch(stripped):
            blocks.append("")
            continue
        stripped = re.sub(r"^#{1,6}\s+", "", stripped)
        stripped = re.sub(r"^(?:[-+•]|\*(?!\*))\s+", "", stripped)
        blocks.append(clean(stripped))
    return blocks


def read_blocks(markdown: str) -> list[Block]:
    """Non-empty text lines and tables, in document order."""
    text = re.sub(r"<!--.*?-->", "\n", markdown, flags=re.S)
    blocks: list[Block] = []
    position = 0
    for match in _HTML_TABLE.finditer(text):
        blocks += _text_blocks(text[position:match.start()])
        blocks.append(Table(_html_rows(match.group())))
        position = match.end()
    blocks += _text_blocks(text[position:])

    for block in blocks:
        if isinstance(block, Table):
            block.rows = [
                ["\n".join(filter(None, map(clean, cell.split("\n")))) for cell in row]
                for row in block.rows
            ]
    return [b for b in blocks if b and (isinstance(b, str) or b.rows)]
