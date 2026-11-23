"""Shared by the tests: paths, and bronze stores made of altered invoices."""

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data"
BRONZE = DATA / "bronze"

# source name -> (Markdown, bronze record)
SRC = {}
for _path in sorted(BRONZE.glob("*/*/*.json")):
    _record = json.loads(_path.read_text())
    SRC[_record["source"]] = (_path.with_suffix(".md").read_text(), _record)
COUNT = len(SRC)
A = "facture_A-2025-0001_texte.pdf"
B = "facture_GPE-2025-0003_scan.pdf"


class Bz:
    """A bronze store filled with copies of real records, altered at will."""

    def __init__(self, root):
        self.root, self.n = root, 0

    def add(self, src=A, f=None, **changes):
        markdown, record = SRC[src]
        record = copy.deepcopy(record)
        text = f(markdown) if f else markdown
        if f:
            assert text != markdown, "mutation had no effect"
        self.n += 1
        sha = hashlib.sha256(f"{self.n}{src}".encode()).hexdigest()
        record.update(sha256=sha, markdown_sha256=hashlib.sha256(text.encode()).hexdigest())
        record.update(changes)
        folder = self.root / sha / "v"
        folder.mkdir(parents=True)
        name = record["source"].split("/")[-1]
        (folder / f"{name}.md").write_text(text)
        (folder / f"{name}.json").write_text(json.dumps(record))
        return sha


def sub(*pairs):
    """A mutation replacing each first string by the second."""

    def apply(text):
        for old, new in zip(pairs[::2], pairs[1::2]):
            assert old in text, old
            text = text.replace(old, new)
        return text

    return apply
