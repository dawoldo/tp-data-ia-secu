import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time

import pymupdf
import pytest
from common import ROOT

R = str(ROOT)
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import bad_workers

from bronze import pipeline as V
from bronze.extraction import ocr as O
from bronze.extraction import pdf as F
from bronze.extraction import worker as W
from bronze.storage import store as B

T = "Facture numero A-2025-0001\nSIRET 77360260298050 total TTC 36 973,80 euros\nMerci de votre confiance"


def mk(*pages, extra=""):
    d = pymupdf.open()
    for k in pages:
        p = d.new_page()
        if k in ("text", "stamp", "hidden"):
            p.insert_text((50, 60), T + extra, render_mode=3 if k == "hidden" else 0)
        if k in ("scan", "stamp", "hidden"):
            s = pymupdf.open()
            q = s.new_page()
            q.insert_text((50, 200), T + extra)
            p.insert_image(p.rect, pixmap=q.get_pixmap(dpi=60), overlay=False)
        if k == "vector":
            p.draw_line((50, 50), (300, 300))
        if k == "marker":
            p.insert_text((50, 60), "<!-- page: 9 -->\n" + T)
    return d.tobytes()


class Srv:
    def __init__(s):
        s.reqs = []
        s.plan = lambda n: (200, "stop", "# OCR text")
        s.headers = {}
        s.delay = 0
        o = s

        class H(BaseHTTPRequestHandler):
            def do_POST(h):
                b = json.loads(h.rfile.read(int(h.headers["Content-Length"])))
                o.reqs.append((b, h.headers.get("Authorization")))
                time.sleep(o.delay)
                st, fin, txt = o.plan(len(o.reqs))
                out = json.dumps(
                    {"choices": [{"finish_reason": fin, "message": {"content": txt}}], "usage": {}}
                    if st == 200
                    else {"error": "x"}
                ).encode()
                h.send_response(st)
                [h.send_header(k, v) for k, v in o.headers.items()]
                h.send_header("Content-Length", str(len(out)))
                h.end_headers()
                h.wfile.write(out)

            def log_message(h, *a):
                pass

        s.h = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=s.h.serve_forever, daemon=True).start()
        s.url = f"http://127.0.0.1:{s.h.server_port}/v1/secret-org/chat/completions"


@pytest.fixture
def srv():
    s = Srv()
    yield s
    s.h.shutdown()


def eng(s, sleep=lambda t: None, **k):
    return O.LightOnOcr(s.url, "KEY123", sleep=sleep, **k)


@pytest.fixture
def land(tmp_path):
    l = tmp_path / "in"
    l.mkdir()
    (l / "t.pdf").write_bytes(mk("text"))
    (l / "s.pdf").write_bytes(mk("scan"))
    manifest(l)
    return l


def manifest(l):
    (l / "manifest.json").write_text(
        json.dumps(
            {
                p.relative_to(l).as_posix(): [
                    {
                        "path": p.relative_to(l).as_posix(),
                        "etag": f'"{p.name}"',
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "size": 1,
                        "last_modified": "x",
                        "pulled_at": "y",
                    }
                ]
                for p in l.rglob("*.pdf")
            }
        )
    )


def run(l, o, e, **k):
    return V.convert_folder(l, B.BronzeStore(o), e, **k)


def snap(o):
    return {
        p.relative_to(o).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in o.rglob("*")
        if p.is_file() and p.name != ".lock"
    }


def recs(o):
    return [json.loads(p.read_text()) for p in sorted(o.glob("*/*/*.json"))]


def verify(o):
    return B.BronzeStore(o).verify()


@pytest.mark.parametrize(
    "pages,kind",
    [
        (["text"], "text"),
        (["scan"], "image"),
        (["text", "scan"], "image"),
        (["hidden"], "image"),
        (["stamp"], "image"),
        (["vector"], "image"),
        (["blank"], "text"),
    ],
)
def test_classify(pages, kind):
    with W.PdfWorker() as w:
        assert w.analyse(mk(*pages), with_text=False)["kind"] == kind


def test_second_run_adds_nothing(srv, land, tmp_path):
    o = tmp_path / "o"
    r = run(land, o, eng(srv))
    assert (r["text"], r["image"], r["ocr_calls"]) == (1, 1, 1)
    a = snap(o)
    r = run(land, o, eng(srv))
    assert r["skipped"] == 2 and r["ocr_calls"] == 0 and len(srv.reqs) == 1 and snap(o) == a
    assert verify(o) == (2, [])


def test_request_and_record(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    b, auth = srv.reqs[0]
    assert auth == "Bearer KEY123"
    c = b["messages"][0]["content"]
    assert [x["type"] for x in c] == ["image_url"]
    img = base64.b64decode(c[0]["image_url"]["url"].split(",")[1])
    pm = pymupdf.Pixmap(img)
    assert max(pm.width, pm.height) == 1540
    r = next(x for x in recs(o) if x["kind"] == "image")
    assert (
        r["origin"]
        == {"s3_key": "s.pdf", "etag": '"s.pdf"', "last_modified": "x", "pulled_at": "y"}
        and r["pages"][0]["image_sha256"] == hashlib.sha256(img).hexdigest()
        and r["pages"][0]["ocr_response"]
    )
    assert "KEY123" not in json.dumps(recs(o)) and "secret-org" not in json.dumps(recs(o))


def test_read_only(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o444 for p in o.glob("*/*/*"))


def test_duplicate_names(srv, tmp_path):
    l = tmp_path / "i"
    (l / "sub").mkdir(parents=True)
    d = mk("scan")
    [(l / n).write_bytes(d) for n in ("a.pdf", "b.pdf", "sub/a.pdf")]
    manifest(l)
    o = tmp_path / "o"
    r = run(l, o, eng(srv))
    assert (
        r["image"] == 1 and sorted(r["duplicates"]) == ["b.pdf", "sub/a.pdf"] and len(srv.reqs) == 1
    )
    assert len((o / "sources.jsonl").read_text().splitlines()) == 3
    a = snap(o)
    run(l, o, eng(srv))
    assert snap(o) == a


def test_same_name_new_content(srv, tmp_path):
    l = tmp_path / "i"
    l.mkdir()
    (l / "a.pdf").write_bytes(mk("text"))
    o = tmp_path / "o"
    run(l, o, None)
    a = snap(o)
    (l / "a.pdf").write_bytes(mk("text", extra=" v2"))
    r = run(l, o, None)
    assert (
        r["text"] == 1
        and len(recs(o)) == 2
        and all(snap(o)[k] == v for k, v in a.items() if "jsonl" not in k)
    )


def test_new_settings_add_version(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    a = snap(o)
    r = run(land, o, eng(srv, max_side=2000))
    assert r["image"] == 1 and r["skipped"] == 1 and len(recs(o)) == 3
    assert all(snap(o)[k] == v for k, v in a.items() if "jsonl" not in k)
    assert run(land, o, eng(srv))["skipped"] == 2 and run(land, o, None)["skipped"] == 2
    assert verify(o) == (3, [])


def tamper(p, f):
    p.chmod(0o644)
    p.write_bytes(f(p.read_bytes()))


@pytest.mark.parametrize(
    "pat,f",
    [
        ("*.md", lambda b: b + b"x"),
        ("*.md", lambda b: b""),
        ("*.json", lambda b: b.replace(b'"s3_key": "t.pdf"', b'"s3_key": "z.pdf"')),
        ("*.json", lambda b: b"{"),
        ("*.json", lambda b: b"[]"),
    ],
)
def test_tampering(srv, land, tmp_path, pat, f):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    p = next(x for x in o.glob("*/*/" + pat) if x.name.startswith("t."))
    tamper(p, f)
    a = p.read_bytes()
    n, pr = verify(o)
    assert n == 1 and len(pr) == 1, pr
    r = run(land, o, eng(srv))
    assert r["damaged"] == ["t.pdf"] and r["skipped"] == 1 and p.read_bytes() == a


def test_deleted_record(srv, land, tmp_path):
    import shutil

    o = tmp_path / "o"
    run(land, o, eng(srv))
    shutil.rmtree(next(o.glob("*/*/t.pdf.md")).parent.parent)
    n, pr = verify(o)
    assert n == 1 and "missing" in pr[0]
    assert run(land, o, eng(srv))["text"] == 1 and verify(o) == (2, [])


def test_deleted_single_file(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    next(o.glob("*/*/t.pdf.json")).unlink()
    assert len(verify(o)[1]) == 1 and run(land, o, eng(srv))["damaged"] == ["t.pdf"]


def test_stray_folder_not_trusted(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    d = o / ("f" * 64) / "abc"
    d.mkdir(parents=True)
    (d / "x.pdf.md").write_text("x")
    (d / "x.pdf.json").write_text("{}")
    assert len(verify(o)[1]) == 1
    assert run(land, o, eng(srv))["skipped"] == 2 and len(verify(o)[1]) == 1


def test_crash_before_index(srv, land, tmp_path, monkeypatch):
    o = tmp_path / "o"
    monkeypatch.setattr(
        B.BronzeStore, "_add_to_index", lambda *a: (_ for _ in ()).throw(KeyboardInterrupt)
    )
    with pytest.raises(KeyboardInterrupt):
        run(land, o, eng(srv))
    monkeypatch.undo()
    n = len(srv.reqs)
    r = run(land, o, eng(srv))
    assert (
        r["skipped"] + r["text"] + r["image"] == 2
        and r["skipped"] == 1
        and verify(o) == (2, [])
        and len(srv.reqs) == max(n, 1)
    )


def test_torn_journal(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    p = o / "index.jsonl"
    b = p.read_bytes()
    p.write_bytes(b[:-20])
    assert run(land, o, eng(srv))["skipped"] == 2 and verify(o) == (2, [])
    assert all(json.loads(x) for x in p.read_text().splitlines())


def test_corrupt_journal_stops(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    p = o / "index.jsonl"
    p.write_text("garbage\n" + p.read_text())
    with pytest.raises(B.BronzeError):
        B.BronzeStore(o)


def test_lock(srv, land, tmp_path):
    o = tmp_path / "o"
    with B.BronzeStore(o).locked():
        with pytest.raises(B.BronzeError):
            run(land, o, eng(srv))
    assert run(land, o, eng(srv))["image"] == 1


def cli(*a, env=None):
    return subprocess.run(
        [sys.executable, "-m", "bronze", *map(str, a)],
        cwd=R,
        capture_output=True,
        text=True,
        env={**{k: v for k, v in os.environ.items() if not k.startswith("OCR_")}, **(env or {})},
    )


def test_kill9_then_resume(srv, tmp_path):
    l = tmp_path / "i"
    l.mkdir()
    o = tmp_path / "o"
    srv.delay = 0.6
    [(l / f"{i}.pdf").write_bytes(mk("scan", extra=str(i))) for i in range(6)]
    f = tmp_path / "e"
    f.write_text(f"OCR_KEY=k\nOCR_ENDPOINT={srv.url}\n")
    p = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "bronze",
            "convert",
            str(l),
            "--out",
            str(o),
            "--env-file",
            str(f),
        ],
        cwd=R,
        stdout=-1,
        stderr=-1,
    )
    while len(srv.reqs) < 3:
        time.sleep(0.02)
    r = cli("convert", l, "--out", o, "--env-file", f)
    assert r.returncode == 2 and "another run" in r.stderr
    p.kill()
    p.wait()
    time.sleep(0.3)
    done = len(recs(o))
    assert 0 < done < 6
    r = cli("convert", l, "--out", o, "--env-file", f)
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert (
        s["skipped"] == done
        and s["image"] == 6 - done
        and verify(o) == (6, [])
        and not (o / ".tmp").exists()
    )


def test_child_exits_with_parent_killed():
    time.sleep(0.5)
    out = subprocess.run(
        ["pgrep", "-f", "multiprocessing.spawn"], capture_output=True, text=True
    ).stdout.split()
    me = str(os.getpid())
    assert len(out) <= 2, out


@pytest.mark.parametrize(
    "fn,msg",
    [("crash", "crashed"), ("hang", "took more"), ("memory", "memory"), ("raises", "RuntimeError")],
)
def test_hostile_pdf_isolated(fn, msg):
    with W.PdfWorker(timeout=8) as w:
        with pytest.raises(F.PdfError, match=msg):
            w._call(getattr(bad_workers, fn))
        assert w.analyse(mk("text"))["kind"] == "text"


def test_child_never_prints_on_stdout():
    p = subprocess.run(
        [
            sys.executable,
            "-c",
            "import bad_workers\nfrom bronze.extraction.worker import PdfWorker\nif __name__=='__main__':\n  with PdfWorker() as w: print(w._call(bad_workers.chatty))",
        ],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__),
    )
    assert p.stdout == "ok\n", p


def test_page_limit(tmp_path, srv):
    l = tmp_path / "i"
    l.mkdir()
    (l / "a.pdf").write_bytes(mk(*["scan"] * 4))
    r = run(l, tmp_path / "o", eng(srv), max_pages=3)
    assert "limit" in r["failed"]["a.pdf"] and not srv.reqs


def test_bad_pdfs(srv, tmp_path):
    l = tmp_path / "i"
    l.mkdir()
    good = mk("text")
    d = pymupdf.open(stream=good, filetype="pdf")
    o = tmp_path / "o"
    (l / "enc.pdf").write_bytes(
        d.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="x", owner_pw="y")
    )
    (l / "empty.pdf").write_bytes(b"")
    (l / "fake.pdf").write_bytes(b"<html>")
    (l / "rep.pdf").write_bytes(good[:-60])
    (l / "z.PDF").write_bytes(good)
    r = run(l, o, eng(srv))
    assert (
        set(r["failed"]) == {"enc.pdf", "empty.pdf", "fake.pdf"}
        and r["repaired"] == ["rep.pdf"]
        and r["text"] == 2
    )
    assert len((o / "errors.jsonl").read_text().splitlines()) == 3
    assert verify(o) == (2, [])


def test_outage_recovery(srv, tmp_path):
    l = tmp_path / "i"
    l.mkdir()
    o = tmp_path / "o"
    [(l / f"{i}s.pdf").write_bytes(mk("scan", extra=str(i))) for i in range(6)]
    (l / "z.pdf").write_bytes(mk("text"))
    srv.plan = lambda n: (503, "", "")
    r = run(l, o, eng(srv))
    assert (
        len(r["pending_ocr"]) == 6 and r["text"] == 1 and len(srv.reqs) == 9 and len(recs(o)) == 1
    )
    srv.plan = lambda n: (200, "stop", "ok")
    r = run(l, o, eng(srv))
    assert r["image"] == 6 and r["skipped"] == 1


@pytest.mark.parametrize(
    "plan", [(200, "length", "x"), (200, "stop", " "), (200, "stop", None), (400, "", "")]
)
def test_bad_answers(srv, land, tmp_path, plan):
    srv.plan = lambda n: plan
    o = tmp_path / "o"
    r = run(land, o, eng(srv))
    assert list(r["failed"]) == ["s.pdf"] and len(recs(o)) == 1


def test_errors_redacted(srv, land, tmp_path):
    o = tmp_path / "o"
    e = O.LightOnOcr(
        "http://127.0.0.1:9/v1/organizations/secret-org/x", "KEY123", sleep=lambda t: None
    )
    run(land, o, e)
    t = (o / "errors.jsonl").read_text()
    assert (
        "secret-org" not in t and "KEY123" not in t and "127.0.0.1" not in t and "Connection" in t
    )


def test_redirect_not_followed(srv, land, tmp_path):
    other = Srv()
    srv.plan = lambda n: (307, "", "")
    srv.headers = {"Location": other.url}
    r = run(land, tmp_path / "o", eng(srv))
    assert list(r["failed"]) == ["s.pdf"] and not other.reqs
    other.h.shutdown()


def test_retry_after(srv, land, tmp_path):
    w = []
    srv.plan = lambda n: (429, "", "") if n == 1 else (200, "stop", "ok")
    srv.headers = {"Retry-After": "7"}
    assert run(land, tmp_path / "o", eng(srv, sleep=w.append))["image"] == 1 and w == [7]


def test_manifest_mismatch(srv, land, tmp_path):
    (land / "t.pdf").write_bytes(mk("text", extra="changed"))
    o = tmp_path / "o"
    r = run(land, o, eng(srv))
    assert "differs" in r["failed"]["t.pdf"] and [x["source"] for x in recs(o)] == ["s.pdf"]


def test_manifest_bad(srv, land, tmp_path):
    (land / "manifest.json").write_text("{")
    with pytest.raises(B.BronzeError):
        run(land, tmp_path / "o", eng(srv))


def test_single_file_and_subfolder_keep_names(srv, tmp_path):
    l = tmp_path / "i"
    (l / "sub").mkdir(parents=True)
    (l / "sub/a.pdf").write_bytes(mk("text"))
    manifest(l)
    o = tmp_path / "o"
    run(l / "sub", o, None)
    assert recs(o)[0]["source"] == "sub/a.pdf" and recs(o)[0]["origin"]["s3_key"] == "sub/a.pdf"
    assert run(l / "sub/a.pdf", o, None)["skipped"] == 1 and run(l, o, None)["skipped"] == 1


def test_unrelated_parent_manifest(srv, tmp_path):
    (tmp_path / "manifest.json").write_text('{"name":"webapp"}')
    l = tmp_path / "i"
    l.mkdir()
    (l / "a.pdf").write_bytes(mk("text"))
    run(l, tmp_path / "o", None)
    assert recs(tmp_path / "o")[0]["source"] == "a.pdf"


def test_dry_run(srv, land, tmp_path):
    o = tmp_path / "o"
    r = run(land, o, eng(srv), dry_run=True)
    assert (r["text"], r["image"], r["ocr_calls"]) == (1, 1, 1) and not o.exists() and not srv.reqs


def test_limit(tmp_path):
    l = tmp_path / "i"
    l.mkdir()
    (l / "a.pdf").write_bytes(b"x")
    [(l / f"{i}.pdf").write_bytes(mk("text", extra=i)) for i in "bcd"]
    o = tmp_path / "o"
    assert (
        run(l, o, None, limit=1)["text"] == 1
        and run(l, o, None, limit=1)["text"] == 1
        and len(recs(o)) == 2
    )


def test_mixed_and_marker(srv, tmp_path):
    l = tmp_path / "i"
    l.mkdir()
    (l / "m.pdf").write_bytes(mk("text", "scan", "blank", "marker"))
    o = tmp_path / "o"
    run(l, o, eng(srv))
    m = next(o.glob("*/*/*.md")).read_text()
    assert [m.count(f"<!-- page: {i} -->") for i in (1, 2, 3, 4, 9)] == [1, 1, 1, 1, 0]
    assert verify(o) == (1, [])


def test_cli(land, tmp_path):
    o = tmp_path / "o"
    r = cli("convert", land, "--out", o, "--no-ocr")
    assert r.returncode == 1
    json.loads(r.stdout)
    assert cli("verify", o).returncode == 0
    tamper(next(o.glob("*/*/*.md")), lambda b: b + b"x")
    assert cli("verify", o).returncode == 1
    assert cli("verify", tmp_path / "no").returncode == 2
    assert cli("convert", land, "--force").returncode == 2
    assert cli("convert", land, "--out", o, "--env-file", "/nope").returncode == 2
    assert cli("classify", land).returncode == 0


def test_silver_newest_and_tamper(srv, land, tmp_path):
    o = tmp_path / "o"
    run(land, o, eng(srv))
    srv.plan = lambda n: (200, "stop", "# second")
    time.sleep(0.01)
    run(land, o, eng(srv, max_side=2000))
    (land / "u.PDF").write_bytes(mk("text", extra="up"))
    run(land, o, eng(srv))
    from silver.reader import read_documents as fd

    d, u = fd(o)
    assert len(d) == 3 and not u and any("second" in m for m, _ in d)
    tamper(next(o.glob("*/*/t.pdf.md")), lambda b: b + b"x")
    d, u = fd(o)
    assert len(d) == 2 and len(u) == 1
