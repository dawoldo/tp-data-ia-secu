import os
import shutil
import subprocess
import sys

from common import BRONZE, COUNT, ROOT

from bronze.storage.tables import write_tables
from silver.tables import analyse, write

R = str(ROOT)
import duckdb
import pytest

from warehouse import db as W


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "it's data"
    d.mkdir()
    write_tables(BRONZE, d / "bronze" / "tables")
    write(analyse(BRONZE), d / "silver")
    return d


HOLD = "import duckdb,sys,time\nc=duckdb.connect(sys.argv[1],read_only=sys.argv[2]=='ro'); c.execute('select count(*) from silver.factures').fetchall(); print('open',flush=True); time.sleep(60)"


def hold(p, mode):
    h = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(p), mode], stdout=subprocess.PIPE, text=True
    )
    assert h.stdout.readline() == "open\n"
    return h


def other(code):
    return subprocess.run([sys.executable, "-c", code], cwd=R, capture_output=True, text=True)


def test_every_view_matches_its_file(data):
    with W.connect(data) as c:
        for n, (f, _) in W.VIEWS.items():
            p = str(data / f).replace("'", "''")
            assert (
                c.execute(f"select * from {n} order by all").fetchall()
                == c.execute(f"select * from read_parquet('{p}') order by all").fetchall()
            )


def test_no_data_copied(data):
    p = W.build(data)
    with duckdb.connect(str(p), read_only=True) as c:
        assert (
            c.execute("select count(*) from duckdb_tables()").fetchone()[0] == 0
            and c.execute("select count(*) from duckdb_views() where not internal").fetchone()[0]
            == 7
        )


def test_naive_open_is_blocked(data):  # the problem is real
    p = W.build(data)
    h = hold(p, "rw")
    try:
        assert other(f"import duckdb; duckdb.connect({str(p)!r},read_only=True)").returncode != 0
    finally:
        h.kill()
        h.wait()


@pytest.mark.parametrize("mode", ["rw", "ro"])
def test_gui_never_blocks_programs_or_rebuild(data, mode):
    p = W.build(data)
    h = hold(p, mode)
    try:
        code = f"from pathlib import Path\nfrom warehouse.db import connect,build\nd=Path({str(data)!r})\nprint(connect(d).execute('select count(*) from silver.factures').fetchall())\nbuild(d)"
        r = other(code)
        assert r.returncode == 0 and r.stdout == f"[({COUNT},)]\n", r.stderr
    finally:
        h.kill()
        h.wait()
    assert duckdb.connect(str(p), read_only=True).execute(
        "select count(*) from silver.factures"
    ).fetchone() == (COUNT,)


def test_many_programs_at_once(data):
    c = f"from pathlib import Path\nfrom warehouse.db import connect\nc=connect(Path({str(data)!r}))\nfor _ in range(20): assert c.execute('select sum(total_ht) from silver.lignes_facture').fetchone()"
    ps = [subprocess.Popen([sys.executable, "-c", c], cwd=R) for _ in range(5)]
    assert [x.wait() for x in ps] == [0] * 5


def test_new_data_visible_without_rebuild(data):
    p = W.build(data)
    c = duckdb.connect(str(p), read_only=True)
    f = data / "silver/factures.parquet"
    t = data / "t.parquet"
    with duckdb.connect() as x:
        x.execute(
            f"copy (select * from read_parquet('{str(f).replace(chr(39), chr(39) * 2)}') limit 7) to '{str(t).replace(chr(39), chr(39) * 2)}' (format parquet)"
        )
    os.replace(t, f)
    assert c.execute("select count(*) from silver.factures").fetchone() == (7,)


def test_moved_data_dir(data, tmp_path):
    n = tmp_path / "elsewhere"
    shutil.move(data, n)
    r = subprocess.run(
        [sys.executable, "-m", "warehouse", "query", "select count(*) c from bronze.pages"],
        cwd=R,
        env={**os.environ, "DATA_DIR": str(n)},
        capture_output=True,
        text=True,
    )
    assert str(COUNT) in r.stdout, r.stderr


def test_missing_file(data):
    (data / "silver/rejets.parquet").unlink()
    with pytest.raises(FileNotFoundError, match="warehouse refresh"):
        W.connect(data)


def test_failed_build_keeps_old(data):
    p = W.build(data)
    b = p.read_bytes()
    (data / "silver/rejets.parquet").rename(data / "x")
    with pytest.raises(FileNotFoundError):
        W.build(data)
    assert p.read_bytes() == b and not list(p.parent.glob(".*"))


def test_export_does_not_remove_database(data):
    p = W.build(data)
    from_ = set(x.name for x in p.parent.iterdir())
    assert "entrepot.duckdb" in from_


def test_descriptions(data):
    with W.connect(data) as c:
        assert all(
            x[0]
            for x in c.execute("select comment from duckdb_views() where not internal").fetchall()
        )


def test_bad_sql(data):
    r = subprocess.run(
        [sys.executable, "-m", "warehouse", "query", "selec"],
        cwd=R,
        env={**os.environ, "DATA_DIR": str(data)},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_refresh_then_query(tmp_path):
    shutil.copytree(BRONZE, tmp_path / "bronze" / "documents")
    env = {**os.environ, "DATA_DIR": str(tmp_path)}

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "warehouse", *args],
            cwd=R,
            env=env,
            capture_output=True,
            text=True,
        )

    assert run("query", "select 1").returncode == 2  # nothing built yet
    assert run("refresh").returncode == 0
    assert run("build").returncode == 0
    assert str(COUNT) in run("query", "select count(*) from silver.factures").stdout


def test_refresh_without_bronze(tmp_path):
    r = subprocess.run(
        [sys.executable, "-m", "warehouse", "refresh"],
        cwd=R,
        env={**os.environ, "DATA_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2 and "Traceback" not in r.stderr
