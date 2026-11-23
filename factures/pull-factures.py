#!/usr/bin/env python3
"""Download new invoice PDFs from an S3 bucket into a local landing zone.

Re-running only downloads what is new or changed. Every file ever pulled is
recorded in <dest>/manifest.json with its S3 key, ETag and SHA-256.

    python factures/pull-factures.py                # pull everything new
    python factures/pull-factures.py --limit 5      # start small
    python factures/pull-factures.py --dry-run      # only show what would be pulled

Settings come from the .env next to this script (see MANUAL.md), then from
environment variables for whatever .env leaves out (containers, CI). The file
wins so that an unrelated AWS login in the shell is never used by accident.

Logs go to stderr. A one-line JSON summary goes to stdout for the next step.
Exit code: 0 = all good, 1 = some files failed, 2 = configuration or S3 error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
DEFAULT_ENDPOINT = "https://dams-5.s3-gateway.console.hyperfluid.cloud"
DEFAULT_BUCKET = "factures"
DEFAULT_REGION = "us-east-1"  # only used to sign requests
MANIFEST_NAME = "manifest.json"
CHUNK_SIZE = 1024 * 1024

log = logging.getLogger("pull-factures")


class ConfigError(Exception):
    """A setting or the local manifest is missing or unusable."""


class DownloadError(Exception):
    """A single object could not be stored safely."""


@dataclass(frozen=True)
class Settings:
    endpoint: str
    bucket: str
    region: str
    access_key: str
    secret_key: str

    @classmethod
    def load(cls, env_file: Path) -> Settings:
        from_file = {k: v for k, v in dotenv_values(env_file).items() if v}
        env = {**os.environ, **from_file}
        required = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
        missing = [name for name in required if not env.get(name)]
        if missing:
            raise ConfigError(
                f"missing {', '.join(missing)}: set them in {env_file} (see MANUAL.md)"
            )
        return cls(
            endpoint=env.get("AWS_ENDPOINT_URL") or DEFAULT_ENDPOINT,
            bucket=env.get("S3_BUCKET") or DEFAULT_BUCKET,
            region=env.get("AWS_DEFAULT_REGION") or DEFAULT_REGION,
            access_key=env["AWS_ACCESS_KEY_ID"],
            secret_key=env["AWS_SECRET_ACCESS_KEY"],
        )


def make_client(settings: Settings):
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint,
        region_name=settings.region,
        aws_access_key_id=settings.access_key,
        aws_secret_access_key=settings.secret_key,
        config=Config(
            connect_timeout=10,
            read_timeout=60,
            retries={"mode": "standard", "max_attempts": 5},
            s3={"addressing_style": "path"},
            # Recent boto3 adds checksums that some S3 gateways reject.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


def list_pdfs(client, bucket: str, prefix: str = "") -> list[dict]:
    """Return every PDF object in the bucket, sorted by key."""
    pages = client.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=prefix
    )
    objects = [obj for page in pages for obj in page.get("Contents", [])]
    pdfs = [o for o in objects if o["Key"].lower().endswith(".pdf")]
    if len(pdfs) < len(objects):
        log.info("ignoring %d non-PDF object(s)", len(objects) - len(pdfs))
    return sorted(pdfs, key=lambda o: o["Key"])


def load_manifest(dest: Path) -> dict[str, list[dict]]:
    """Manifest: S3 key -> versions pulled, oldest first."""
    path = dest / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigError(f"unreadable manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ConfigError(f"unreadable manifest {path}: expected a JSON object")
    return manifest


def save_manifest(dest: Path, manifest: dict[str, list[dict]]) -> None:
    path = dest / MANIFEST_NAME
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def sha256_file(path: Path) -> str:
    with path.open("rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def is_intact(dest: Path, version: dict) -> bool:
    path = dest / version["path"]
    return path.is_file() and sha256_file(path) == version["sha256"]


def is_up_to_date(dest: Path, versions: list[dict], etag: str) -> bool:
    """True if the latest pulled version matches S3 and is intact on disk."""
    return bool(versions) and versions[-1]["etag"] == etag and is_intact(dest, versions[-1])


def target_path(dest: Path, key: str) -> Path:
    """Map an S3 key to a path that is guaranteed to stay inside dest."""
    pure = PurePosixPath(key)
    target = dest / pure
    # The as_posix check rejects keys such as "a//b.pdf" that would land on
    # the same file as "a/b.pdf".
    if (
        pure.as_posix() != key
        or ".." in pure.parts
        or not target.resolve().is_relative_to(dest.resolve())
    ):
        raise DownloadError("unsafe S3 key")
    return target


def download(client, bucket: str, key: str, dest: Path, versions: list[dict]) -> dict:
    """Download one object and return its manifest entry.

    Content that was already pulled is never overwritten: when an object
    changes under the same key, the new version is saved next to the old one.
    """
    target = target_path(dest, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        head = b""
        with tmp.open("wb") as fh:
            for chunk in response["Body"].iter_chunks(CHUNK_SIZE):
                if len(head) < 1024:
                    head += chunk[: 1024 - len(head)]
                digest.update(chunk)
                size += len(chunk)
                fh.write(chunk)

        if size != response["ContentLength"]:
            raise DownloadError(f"got {size} of {response['ContentLength']} bytes")
        if b"%PDF-" not in head:
            raise DownloadError("content is not a PDF")

        sha256 = digest.hexdigest()
        damaged = any(
            dest / v["path"] == target and not is_intact(dest, v) for v in versions
        )
        # Different content already holds the plain name: keep both.
        if target.is_file() and not damaged and sha256_file(target) != sha256:
            target = target.with_name(f"{target.stem}.{sha256[:8]}{target.suffix}")
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)

    return {
        "path": target.relative_to(dest).as_posix(),
        "etag": response["ETag"],
        "sha256": sha256,
        "size": size,
        "last_modified": response["LastModified"].isoformat(),
        "pulled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def pull(
    client,
    bucket: str,
    dest: Path,
    prefix: str = "",
    limit: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Pull new or changed PDFs into dest and return a summary."""
    manifest = load_manifest(dest)
    objects = list_pdfs(client, bucket, prefix)
    todo = [
        o for o in objects
        if not is_up_to_date(dest, manifest.get(o["Key"], []), o["ETag"])
    ]
    selected = todo if limit is None else todo[:limit]
    summary = {
        "bucket": bucket,
        "found": len(objects),
        "up_to_date": len(objects) - len(todo),
        "pulled": [],
        "failed": {},
        "remaining": len(todo) - len(selected),
        "dry_run": dry_run,
    }
    log.info(
        "%d PDF(s) in bucket, %d up to date, %d to pull",
        len(objects), summary["up_to_date"], len(selected),
    )
    if dry_run:
        for obj in selected:
            log.info("would pull %s (%d bytes)", obj["Key"], obj["Size"])
        summary["remaining"] = len(todo)
        return summary

    dest.mkdir(parents=True, exist_ok=True)
    for i, obj in enumerate(selected, 1):
        key = obj["Key"]
        versions = manifest.get(key, [])
        try:
            entry = download(client, bucket, key, dest, versions)
        except (DownloadError, BotoCoreError, ClientError, OSError) as exc:
            log.error("[%d/%d] %s: %s", i, len(selected), key, exc)
            summary["failed"][key] = str(exc)
            continue
        # Restoring a lost or damaged file replaces its entry, not adds one.
        kept = [v for v in versions if v["path"] != entry["path"]]
        manifest[key] = kept + [entry]
        save_manifest(dest, manifest)  # after each file, so a crash loses nothing
        summary["pulled"].append(key)
        log.info("[%d/%d] %s", i, len(selected), entry["path"])
    return summary


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download new invoice PDFs from S3 into a landing zone."
    )
    parser.add_argument("--dest", type=Path, default=HERE / "landing",
                        help="landing directory (default: factures/landing)")
    parser.add_argument("--env-file", type=Path, default=HERE / ".env",
                        help="settings file (default: factures/.env)")
    parser.add_argument("--prefix", default="", help="only pull keys with this prefix")
    parser.add_argument("--limit", type=positive_int, help="pull at most N files")
    parser.add_argument("--dry-run", action="store_true", help="list without downloading")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(message)s"
    )
    logging.getLogger("botocore").setLevel(logging.WARNING)
    logging.getLogger("boto3").setLevel(logging.WARNING)
    try:
        settings = Settings.load(args.env_file)
        summary = pull(
            make_client(settings), settings.bucket, args.dest,
            prefix=args.prefix, limit=args.limit, dry_run=args.dry_run,
        )
    except (ConfigError, BotoCoreError, ClientError, OSError, ValueError) as exc:
        log.error("%s", exc)
        return 2
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
