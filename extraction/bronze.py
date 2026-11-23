"""Append-only store of raw extractions.

    <root>/<sha256 of the PDF>/<version>/NAME.pdf.md      Markdown, as extracted
                                        /NAME.pdf.json    traceability record
    <root>/index.jsonl      hashes of every record, to detect changes and losses
    <root>/sources.jsonl    every place a PDF was seen (file, S3 key, ETag)
    <root>/errors.jsonl     every failure

A version is a hash of the extraction settings: new settings add a version and
never replace one. Files are read-only and appear all at once or not at all.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORMAT = 2


class BronzeError(Exception):
    """The store cannot be used."""


class DamagedRecord(Exception):
    """A stored record was modified, or is incomplete."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def version_of(settings: dict[str, Any]) -> str:
    return sha256(json.dumps(settings, sort_keys=True).encode())[:16]


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_once(path: Path, data: bytes) -> None:
    with path.open("xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    path.chmod(0o444)


class BronzeStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._index = {
            (e["sha256"], e["version"]): e for e in self._read_lines("index.jsonl")
        }
        self._sources = {
            (e["sha256"], e["source"], e["etag"]) for e in self._read_lines("sources.jsonl")
        }

    # Journals

    def _read_lines(self, name: str) -> list[dict[str, Any]]:
        path = self.root / name
        if not path.exists():
            return []
        entries = []
        lines = path.read_text(encoding="utf-8").split("\n")
        for number, line in enumerate(lines, 1):
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError as exc:
                if number == len(lines):
                    continue  # cut short by a crash: reconcile() rebuilds it
                raise BronzeError(f"{path}, line {number}: {exc}") from exc
        return entries

    def _append(self, name: str, entry: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / name
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with path.open("a+b") as fh:
            if fh.tell():  # never glue an entry to one cut short by a crash
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b"\n":
                    fh.seek(0)
                    fh.truncate(fh.read().rfind(b"\n") + 1)
            fh.write(line.encode())
            fh.flush()
            os.fsync(fh.fileno())

    def log_error(self, source: str, exc: Exception) -> None:
        self._append("errors.jsonl", {
            "at": now(), "source": source, "type": type(exc).__name__, "error": str(exc),
        })

    def note_source(self, digest: str, source: str, origin: dict[str, Any] | None) -> None:
        """Remember where a PDF was seen. Writes nothing if already known."""
        etag = origin["etag"] if origin else None
        if (digest, source, etag) in self._sources:
            return
        self._append("sources.jsonl", {
            "sha256": digest, "source": source, "etag": etag,
            "s3_key": origin["s3_key"] if origin else None, "seen_at": now(),
        })
        self._sources.add((digest, source, etag))

    # Records

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        """One writer at a time. The lock disappears with the process."""
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / ".lock").open("w") as fh:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BronzeError(f"another run is using {self.root}") from None
            shutil.rmtree(self.root / ".tmp", ignore_errors=True)  # left by a crash
            self._reconcile()
            yield

    def _folders(self) -> Iterator[Path]:
        if self.root.is_dir():
            for path in sorted(self.root.glob("*/*/")):
                if not path.parent.name.startswith("."):
                    yield path

    def _load(self, folder: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        """Return a record and its index entry, checking everything but the index."""
        files = sorted(folder.iterdir())
        names = [f.name for f in files]
        if len(files) != 2 or not names[1].endswith(".md") \
                or names[0].removesuffix(".json") != names[1].removesuffix(".md"):
            raise DamagedRecord(f"{folder}: unexpected files {names}")
        raw, markdown = files[0].read_bytes(), files[1].read_bytes()
        try:
            record = json.loads(raw)
            facts = {
                "PDF hash": record["sha256"] == folder.parent.name,
                "settings": version_of(record["settings"]) == folder.name,
                "Markdown": record["markdown_sha256"] == sha256(markdown),
                "pages": record["page_count"] == markdown.count(b"<!-- page: "),
            }
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise DamagedRecord(f"{folder}: unreadable record ({exc!r})") from exc
        wrong = [name for name, right in facts.items() if not right]
        if wrong:
            raise DamagedRecord(f"{folder}: does not match its record: {', '.join(wrong)}")
        return record, {
            "sha256": folder.parent.name, "version": folder.name,
            "record_sha256": sha256(raw), "added_at": now(),
        }

    def _check(self, folder: Path) -> dict[str, Any]:
        record, entry = self._load(folder)
        known = self._index.get((entry["sha256"], entry["version"]))
        if known is None:
            raise DamagedRecord(f"{folder}: not in the index")
        if known["record_sha256"] != entry["record_sha256"]:
            raise DamagedRecord(f"{folder}: record modified")
        return record

    def _reconcile(self) -> None:
        """Index records whose run stopped between storing and indexing them."""
        for folder in self._folders():
            if (folder.parent.name, folder.name) not in self._index:
                with contextlib.suppress(DamagedRecord):
                    self._add_to_index(self._load(folder)[1])

    def _add_to_index(self, entry: dict[str, Any]) -> None:
        self._append("index.jsonl", entry)
        self._index[entry["sha256"], entry["version"]] = entry

    def find(
        self, digest: str, accept: Callable[[dict[str, Any]], bool]
    ) -> dict[str, Any] | None:
        """The newest intact record of this PDF whose settings are accepted."""
        folder = self.root / digest
        if not folder.is_dir():
            return None
        records = [self._check(f) for f in sorted(folder.iterdir()) if f.is_dir()]
        accepted = [r for r in records if accept(r["settings"])]
        return max(accepted, key=lambda r: r["converted_at"], default=None)

    def add(self, name: str, markdown: str, record: dict[str, Any]) -> None:
        data = markdown.encode()
        record = {"format": FORMAT, **record, "markdown_sha256": sha256(data)}
        raw = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode()
        target = self.root / record["sha256"] / version_of(record["settings"])
        tmp = self.root / ".tmp" / uuid.uuid4().hex
        tmp.mkdir(parents=True)
        try:
            _write_once(tmp / f"{name}.md", data)
            _write_once(tmp / f"{name}.json", raw)
            _sync_dir(tmp)
            target.parent.mkdir(exist_ok=True)
            os.rename(tmp, target)  # fails if the version exists
            _sync_dir(target.parent)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            with contextlib.suppress(OSError):
                tmp.parent.rmdir()
        self._add_to_index(self._load(target)[1])

    def verify(self) -> tuple[int, list[str]]:
        """Number of intact records, and every problem found."""
        intact, problems, seen = 0, [], set()
        for folder in self._folders():
            seen.add((folder.parent.name, folder.name))
            try:
                self._check(folder)
                intact += 1
            except (DamagedRecord, OSError) as exc:
                problems.append(str(exc))
        problems += [
            f"{self.root / digest / version}: missing"
            for digest, version in self._index if (digest, version) not in seen
        ]
        return intact, problems
