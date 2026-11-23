"""Read the bronze layer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REQUIRED = {"source", "sha256", "kind", "converted_at"}


@dataclass(frozen=True)
class Unusable:
    source: str
    reason: str


def _markdown_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    return sorted(
        p for p in source.rglob("*")
        if p.name.lower().endswith((".pdf.md", ".pdf.json"))
        and not any(part.startswith(".") for part in p.relative_to(source).parts)
    )


def read_documents(source: Path) -> tuple[list[tuple[str, dict[str, Any]]], list[Unusable]]:
    """Markdown and record of the newest version of each PDF, and what is unusable.

    A PDF with a damaged version is still usable through its intact ones.
    """
    newest: dict[str, tuple[str, dict[str, Any]]] = {}
    unusable: list[tuple[str, Unusable]] = []
    for base in sorted({p.with_name(p.name.rsplit(".", 1)[0]) for p in _markdown_files(source)}):
        try:
            record = json.loads(base.with_name(base.name + ".json").read_text(encoding="utf-8"))
            if not isinstance(record, dict) or REQUIRED - record.keys():
                raise ValueError("traçabilité incomplète")
            data = base.with_name(base.name + ".md").read_bytes()
            expected = record.get("markdown_sha256")
            if expected not in (None, hashlib.sha256(data).hexdigest()):
                raise ValueError("Markdown modifié depuis son extraction")
            markdown = data.decode("utf-8")
        except (OSError, ValueError) as exc:
            folder = base.parent.parent.name
            unusable.append((folder, Unusable(base.name, f"{type(exc).__name__}: {exc}")))
            continue
        record["version"] = base.parent.name
        known = newest.get(record["sha256"])
        if known is None or record["converted_at"] > known[1]["converted_at"]:
            newest[record["sha256"]] = (markdown, record)
    documents = sorted(newest.values(), key=lambda d: (d[1]["source"], d[1]["sha256"]))
    found = newest.keys() | {folder for folder, _ in unusable}
    unusable += [
        (digest, Unusable(digest, "enregistrement disparu de la couche bronze"))
        for digest in _indexed(source) if digest not in found
    ]
    return documents, [bad for folder, bad in unusable if folder not in newest]


def _indexed(source: Path) -> list[str]:
    """Every PDF that bronze says it holds, so that a deleted one is not forgotten."""
    index = source / "index.jsonl"
    if not index.is_file():
        return []
    lines = index.read_text(encoding="utf-8").splitlines()
    return sorted({json.loads(line)["sha256"] for line in lines if line.strip()})
