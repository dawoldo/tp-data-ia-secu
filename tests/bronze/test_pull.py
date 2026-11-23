import json
import os
import subprocess
import sys

import pytest
from common import ROOT
from moto.server import ThreadedMotoServer

from bronze.ingestion import pull as pf


def pdf(t):
    return b"%PDF-1.4\n" + t.encode() + b"\n%%EOF"


@pytest.fixture
def s3():
    srv = ThreadedMotoServer(port=0)
    srv.start()
    host, port = srv.get_host_and_port()
    s = pf.Settings(f"http://127.0.0.1:{port}", "factures", "us-east-1", "k", "s3cr3t-value")
    import urllib.request as u

    u.urlopen(u.Request(s.endpoint + "/moto-api/reset", method="POST"))
    c = pf.make_client(s)
    c.create_bucket(Bucket="factures")
    c.ep = s.endpoint
    yield c
    srv.stop()


def put(c, k, b):
    c.put_object(Bucket="factures", Key=k, Body=b)


def run(c, d, **k):
    return pf.pull(c, "factures", d, **k)


def files(d):
    return sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file())


def test_first_then_second_run(s3, tmp_path):
    put(s3, "a.pdf", pdf("a"))
    put(s3, "2025/b.PDF", pdf("b"))
    put(s3, "n.txt", b"x")
    r = run(s3, tmp_path)
    assert len(r["pulled"]) == 2 and not r["failed"]
    assert files(tmp_path) == ["2025/b.PDF", "a.pdf", "manifest.json"]
    before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()}
    r = run(s3, tmp_path)
    assert r["pulled"] == [] and r["up_to_date"] == 2
    assert before == {
        p: (p.stat().st_mtime_ns, p.read_bytes()) for p in tmp_path.rglob("*") if p.is_file()
    }


def test_pagination(s3, tmp_path):
    for i in range(1005):
        put(s3, f"f{i:04}.pdf", pdf(str(i)))
    assert run(s3, tmp_path, dry_run=True)["found"] == 1005
    assert files(tmp_path) == []


def test_limit_resumes(s3, tmp_path):
    for i in range(5):
        put(s3, f"{i}.pdf", pdf(str(i)))
    r = run(s3, tmp_path, limit=2)
    assert len(r["pulled"]) == 2 and r["remaining"] == 3
    assert run(s3, tmp_path)["pulled"] == ["2.pdf", "3.pdf", "4.pdf"]


def test_changed_keeps_both_and_revert(s3, tmp_path):
    put(s3, "a.pdf", pdf("v1"))
    run(s3, tmp_path)
    put(s3, "a.pdf", pdf("v2"))
    run(s3, tmp_path)
    assert (tmp_path / "a.pdf").read_bytes() == pdf("v1") and len(
        list(tmp_path.glob("a.*.pdf"))
    ) == 1
    assert run(s3, tmp_path)["pulled"] == []
    put(s3, "a.pdf", pdf("v1"))
    run(s3, tmp_path)
    assert run(s3, tmp_path)["pulled"] == []
    assert len(list(tmp_path.glob("*.pdf"))) == 2


def test_damaged_and_deleted_restored(s3, tmp_path):
    put(s3, "a.pdf", pdf("a"))
    put(s3, "b.pdf", pdf("b"))
    run(s3, tmp_path)
    (tmp_path / "a.pdf").write_bytes(b"junk")
    (tmp_path / "b.pdf").unlink()
    assert run(s3, tmp_path)["pulled"] == ["a.pdf", "b.pdf"]
    assert (tmp_path / "a.pdf").read_bytes() == pdf("a")
    assert all(len(v) == 1 for v in json.loads((tmp_path / "manifest.json").read_text()).values())
    assert files(tmp_path) == ["a.pdf", "b.pdf", "manifest.json"]


def test_unmanifested_file_not_overwritten(s3, tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"mine")
    put(s3, "a.pdf", pdf("a"))
    run(s3, tmp_path)
    assert (tmp_path / "a.pdf").read_bytes() == b"mine"
    assert run(s3, tmp_path)["pulled"] == []


def test_bad_content_isolated(s3, tmp_path):
    put(s3, "a.pdf", b"<html>")
    put(s3, "z.pdf", b"")
    put(s3, "m.pdf", pdf("m"))
    r = run(s3, tmp_path)
    assert set(r["failed"]) == {"a.pdf", "z.pdf"} and r["pulled"] == ["m.pdf"]
    assert files(tmp_path) == ["m.pdf", "manifest.json"]


@pytest.mark.parametrize("key", ["../x.pdf", "/x.pdf", "a/../../x.pdf", "a//b.pdf", "./a.pdf"])
def test_unsafe_keys(tmp_path, key):
    with pytest.raises(pf.DownloadError):
        pf.target_path(tmp_path, key)


def test_truncated(tmp_path):
    class Body:
        def iter_chunks(self, n):
            yield pdf("a")

    class C:
        def get_object(self, **k):
            return {"Body": Body(), "ContentLength": 999, "ETag": "e"}

    with pytest.raises(pf.DownloadError):
        pf.download(C(), "b", "a.pdf", tmp_path, [])
    assert files(tmp_path) == []


def cli(*a, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith(("S3_", "AWS_"))}
    e.update(env)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "bronze",
            "pull",
            *(() if "--env-file" in a else ("--env-file", "/nonexistent")),
            *map(str, a),
        ],
        env=e,
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_cli(s3, tmp_path):
    put(s3, "a.pdf", pdf("a"))
    env = dict(AWS_ENDPOINT_URL=s3.ep, AWS_ACCESS_KEY_ID="k", AWS_SECRET_ACCESS_KEY="s3cr3t-value")
    r = cli("--dest", tmp_path, **env)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["pulled"] == ["a.pdf"] and "s3cr3t-value" not in r.stdout + r.stderr
    put(s3, "b.pdf", b"no")
    assert cli("--dest", tmp_path, **env).returncode == 1
    assert cli("--dest", tmp_path, **{**env, "S3_BUCKET": "nope"}).returncode == 2
    (tmp_path / "manifest.json").write_text("{")
    r = cli("--dest", tmp_path, **env)
    assert r.returncode == 2 and "manifest" in r.stderr


def test_cli_missing_and_unreachable(tmp_path):
    r = cli("--dest", tmp_path, AWS_ACCESS_KEY_ID="", AWS_SECRET_ACCESS_KEY="")
    assert r.returncode == 2 and "AWS_ACCESS_KEY_ID" in r.stderr and not r.stdout
    r = cli(
        "--dest",
        tmp_path,
        AWS_ACCESS_KEY_ID="k",
        AWS_SECRET_ACCESS_KEY="s",
        AWS_ENDPOINT_URL="http://127.0.0.1:9",
    )
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_env_file_wins_over_shell(s3, tmp_path):
    put(s3, "a.pdf", pdf("a"))
    f = tmp_path / "my.env"
    f.write_text(f"AWS_ACCESS_KEY_ID=k\nAWS_SECRET_ACCESS_KEY=s\nAWS_ENDPOINT_URL={s3.ep}\n")
    r = cli(
        "--env-file",
        f,
        "--dest",
        tmp_path / "l",
        AWS_ENDPOINT_URL="http://127.0.0.1:9",
        AWS_ACCESS_KEY_ID="other",
        AWS_SECRET_ACCESS_KEY="other",
    )
    assert r.returncode == 0, r.stderr
