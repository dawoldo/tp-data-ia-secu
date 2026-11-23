"""Where the PDFs of the landing zone come from."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from ..extraction.pdf import PdfError
from ..storage.store import BronzeError
from . import MANIFEST_NAME


class Landing:
    """Where PDFs come from, according to the manifest of pull.py."""

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
            raise PdfError("differs from what was downloaded; run python -m bronze pull again")
        return {k: v for k, v in entry.items() if k != "sha256"}
