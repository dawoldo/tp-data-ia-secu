import glob
import json
import shutil
import subprocess
import sys

from common import BRONZE, COUNT, ROOT, B, Bz, sub

R = str(ROOT)
from pathlib import Path

import duckdb
import pytest

from bronze.storage import tables as E
from silver.tables import analyse, write

REAL = BRONZE


@pytest.fixture
def bz(tmp_path):
    r = tmp_path / "bz"
    r.mkdir()
    return Bz(r)


def ex(src, t):
    rows, unusable = E.write_tables(src, t / "w")
    return rows | write(analyse(src), t / "s"), unusable


def q(t, sql):
    return duckdb.sql(sql.replace("@s", f"{t}/s").replace("@w", f"{t}/w")).fetchall()


def test_text_matches_bronze(tmp_path):
    n, u = ex(REAL, tmp_path)
    assert n["pages"] == COUNT and n["factures"] == COUNT and not u
    recs = {
        json.loads(Path(p).read_text())["sha256"]: Path(p)
        for p in glob.glob(str(REAL / "*/*/*.json"))
    }
    for d, m in q(tmp_path, "select document_id,markdown from '@w/pages.parquet'"):
        assert recs[d].with_suffix(".md").read_text() == f"<!-- page: 1 -->\n\n{m}\n"


def test_silver_joins_bronze(tmp_path):
    ex(REAL, tmp_path)
    assert q(
        tmp_path,
        "select count(*) from '@s/factures.parquet' f join '@w/extractions.parquet' b on f.facture_id=b.document_id and f.bronze_version=b.version where f.s3_key=b.s3_key",
    ) == [(COUNT,)]


def test_types(tmp_path):
    ex(REAL, tmp_path)
    d = {r[0]: r[1] for r in q(tmp_path, "describe select * from '@w/extractions.parquet'")}
    assert (
        d["converted_at"] == "TIMESTAMP WITH TIME ZONE"
        and d["ocr_max_side"] == "INTEGER"
        and d["pdf_repare"] == "BOOLEAN"
    )


def test_deterministic(tmp_path):
    for x in "ab":
        ex(REAL, tmp_path / x)
    assert all(
        p.read_bytes() == (tmp_path / "b" / p.relative_to(tmp_path / "a")).read_bytes()
        for p in (tmp_path / "a").rglob("*.parquet")
    )


@pytest.mark.parametrize("v", ["=A1", "a;b,c", 'dit "oui"', "back\\slash", "tab\tx", "NULL"])
def test_odd_text(bz, tmp_path, v):
    bz.add(f=sub("Formation DuckDB et Parquet", v))
    ex(bz.root, tmp_path)
    assert v in q(tmp_path, "select markdown from '@w/pages.parquet'")[0][0]


def test_rejects_and_damage(bz, tmp_path):
    bz.add()
    bz.add(src=B, f=sub("Numéro de facture", "Nmro"))
    x = bz.add(src="facture_A-2025-0003_scan.pdf")
    p = next((bz.root / x / "v").glob("*.md"))
    p.write_text(p.read_text() + "!")
    n, u = ex(bz.root, tmp_path)
    assert n["factures"] == 1 and n["rejets"] == 2 and n["extractions"] == 2 and len(u) == 1


def test_all_versions(bz, tmp_path):
    x = bz.add()
    shutil.copytree(bz.root / x / "v", bz.root / x / "v2")
    n, _ = ex(bz.root, tmp_path)
    assert n["extractions"] == 2 and n["factures"] == 1


def test_failure_keeps_previous(tmp_path, monkeypatch):
    ex(REAL, tmp_path)
    b = {p: p.read_bytes() for p in tmp_path.rglob("*.parquet")}
    real = E._write_files

    def fail(*a):
        real(*a)
        raise RuntimeError("x")

    monkeypatch.setattr(E, "_write_files", fail)
    with pytest.raises(RuntimeError):
        ex(REAL, tmp_path)
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == b


def test_multi_page():
    assert E.split_pages("<!-- page: 1 -->\n\na\n\n<!-- page: 2 -->\n\nb\n\nc\n") == ["a", "b\n\nc"]


def test_cli(tmp_path):
    run = lambda *a: subprocess.run(
        [sys.executable, "-B", "-m", "bronze", "tables", *map(str, a)],
        cwd=R,
        capture_output=True,
        text=True,
    )
    r = run(BRONZE, "--out", tmp_path / "w")
    assert r.returncode == 0 and len(list(tmp_path.rglob("*.parquet"))) == 2
    assert run(tmp_path / "no").returncode == 2
