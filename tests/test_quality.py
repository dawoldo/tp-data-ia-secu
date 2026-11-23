import copy
import json
import subprocess
import sys
from decimal import Decimal as D

import duckdb
import pytest
from common import BRONZE, COUNT, ROOT, SRC, A, B, Bz, sub

R = str(ROOT)
from silver.build import analyse, summary, write


@pytest.fixture
def bz(tmp_path):
    r = tmp_path / "bz"
    r.mkdir()
    return Bz(r)


def codes(bz):
    s = analyse(bz.root)
    return {a.code for d in s.documents for a in d.anomalies}, s


FLAG = [
    ("total_ttc_incoherent", sub("36 973,80", "36 973,81")),
    ("ligne_incoherente", sub("|9|1 541,05", "|8|1 541,05")),
    ("somme_lignes", sub("Total HT 30 811,50", "Total HT 30 811,51")),
    (
        "tva_incoherente",
        sub("TVA 20 % 6 162,30", "TVA 20 % 6 162,50", "Total TVA 6 162,30", "Total TVA 6 162,50"),
    ),
    ("total_tva_incoherent", sub("Total TVA 6 162,30", "Total TVA 6 162,31")),
    ("taux_tva_inconnu", sub("|20 %|", "|19 %|", "TVA 20 %", "TVA 19 %")),
    ("detail_tva_incoherent", sub("TVA 20 %", "TVA 10 %")),
    ("echeance_avant_emission", sub("11/03/2025", "11/03/2024")),
    ("delai_inhabituel", sub("11/03/2025", "12/03/2025")),
    ("annee_incoherente", sub("10/01/2025", "10/01/2024")),
    ("iban_invalide", sub("FR1578820812191361939909169", "FR1578820812191361939909168")),
    ("iban_invalide", sub("FR1578820812191361939909169", "FR157882081219136193990916")),
    ("tva_intracom_incoherente", sub("FR09773602602", "FR09773602603")),
    ("fournisseur_egal_client", sub("20037917087083", "77360260298050")),
    ("nom_fichier", sub("A-2025-0001", "A-2025-0007")),
    (
        "emission_future",
        sub("10/01/2025", "10/12/2026", "11/03/2025", "11/01/2027", "A-2025-0001", "A-2026-0001"),
    ),
    ("lecture_partielle", sub("IBAN : ", "")),
    ("lecture_partielle", sub("Catégorie : Conseil\n", "")),
    (
        "mode_paiement_inconnu",
        sub("Mode de paiement : Carte bancaire", "Mode de paiement : Carte bancairc"),
    ),
    ("nom_fichier", sub("A-2025-0001", "A-7025-0001")),
    ("montant_non_positif", sub("36 973,80", "-36 973,80")),
]


@pytest.mark.parametrize("code,f", FLAG)
def test_flagged(bz, tmp_path, code, f):
    bz.add(f=f)
    c, s = codes(bz)
    assert code in c, c
    assert not s.documents[0].rejete
    t = write(s, tmp_path / "o")
    assert t["factures"] == 1 and t["rejets"] == 0
    assert duckdb.sql(
        f"select statut_qualite,nb_anomalies>0 from '{tmp_path}/o/factures.parquet'"
    ).fetchall() == [("signalee", True)]


REJ = [
    ("total_ttc", sub("36 973,80", "36 9?3,80")),
    ("numero", sub("Numéro de facture : A-2025-0001", "")),
    ("date_emission", sub("10/01/2025", "32/01/2025")),
    ("fournisseur.siret", sub("SIRET : 77360260298050", "SIRET : 773602602980")),
    ("lignes", lambda t: "\n".join(l for l in t.split("\n") if not l.startswith("|"))),
    ("lignes[1].quantite", sub("|9|1 541,05", "|O|1 541,05")),
    ("statut", sub("Statut : Payée", "Statut : Pyee")),
    ("montants", sub("36 973,80", "99 999 999 999 999,80")),
]


@pytest.mark.parametrize("champ,f", REJ)
def test_rejected(bz, tmp_path, champ, f):
    bz.add(f=f)
    bz.add(src=B)
    c, s = codes(bz)
    t = write(s, tmp_path / "o")
    assert t["factures"] == 1 and t["rejets"] == 1
    r = duckdb.sql(f"select motif,details,source from '{tmp_path}/o/rejets.parquet'").fetchall()[0]
    assert r[0] in ("lecture_incomplete", "valeur_hors_limites") and champ in r[1] and r[2] == A


def test_valid_untouched(bz):
    bz.add()
    bz.add(src=B)
    assert codes(bz)[0] == set()


def test_exact_duplicate(bz, tmp_path):
    a = bz.add()
    b = bz.add(source="copie.pdf", kind="image")
    c, s = codes(bz)
    assert c == {"doublon"}
    write(s, tmp_path / "o")
    assert duckdb.sql(
        f"select facture_id,statut_qualite from '{tmp_path}/o/factures.parquet'"
    ).fetchall() == [(a, "valide")]
    assert duckdb.sql(
        f"select document_id,doublon_de,motif from '{tmp_path}/o/rejets.parquet'"
    ).fetchall() == [(b, a, "doublon")]


def test_duplicate_order_independent(tmp_path):
    out = []
    for k in (0, 1):
        (tmp_path / str(k)).mkdir()
        z = Bz(tmp_path / str(k))
        L = [dict(kind="image", source="scan.pdf"), dict()]
        for x in L if k else L[::-1]:
            z.add(**x)
        out.append([d.record["kind"] for d in analyse(z.root).documents if not d.rejete])
    assert out == [["text"], ["text"]]


def test_contradictory_duplicate(bz, tmp_path):
    a = bz.add()
    b = bz.add(f=sub("Statut : Payée", "Statut : En retard"), source="x.pdf", kind="image")
    c, s = codes(bz)
    assert "doublon_contradictoire" in c
    t = write(s, tmp_path / "o")
    assert t["factures"] == 1 and t["rejets"] == 1
    assert duckdb.sql(
        f"select facture_id,statut_qualite from '{tmp_path}/o/factures.parquet'"
    ).fetchall() == [(a, "signalee")]


def test_triple_duplicate(bz, tmp_path):
    [bz.add(source=f"{i}.pdf") for i in range(3)]
    t = write(codes(bz)[1], tmp_path / "o")
    assert t["factures"] == 1 and t["rejets"] == 2


def test_same_number_other_supplier_kept(bz):
    bz.add()
    bz.add(
        f=sub(
            "77360260298050",
            "11111111198050",
            "FR09773602602",
            "FR09111111111",
            "**Aubry**",
            "**Autre**",
        ),
        source="y.pdf",
    )
    s = codes(bz)[1]
    assert not any(d.rejete for d in s.documents)


def test_rejected_does_not_shadow_valid(bz):
    bz.add(f=sub("36 973,80", "x"))
    bz.add(source="ok.pdf")
    s = codes(bz)[1]
    assert sum(not d.rejete for d in s.documents) == 1 and all(
        a.code != "doublon" for d in s.documents for a in d.anomalies
    )


def test_probable_duplicate(bz):
    bz.add()
    bz.add(f=sub("A-2025-0001", "A-2025-0099"), source="z.pdf")
    c, s = codes(bz)
    assert c == {"doublon_probable"} and not any(d.rejete for d in s.documents)


def test_iban_change_flagged(bz):
    for n in ("0002",):
        pass
    bz.add()
    bz.add(src="facture_A-2025-0003_scan.pdf")
    x = bz.add(
        src="facture_A-2025-0010_scan.pdf",
        f=sub("FR1578820812191361939909169", "FR2142784980841241182449353"),
    )
    c, s = codes(bz)
    assert c == {"identite_variable"} and [d.sha256 for d in s.documents if d.anomalies] == [x]


def test_supplier_siret_misread(bz):
    bz.add()
    bz.add(src="facture_A-2025-0003_scan.pdf")
    x = bz.add(
        src="facture_A-2025-0010_scan.pdf",
        f=sub("SIRET : 77360260298050", "SIRET : 77360260298059"),
    )
    c, s = codes(bz)
    assert [d.sha256 for d in s.documents if d.anomalies] == [x]


def test_address_misread(bz):
    bz.add()
    bz.add(src="facture_A-2025-0003_scan.pdf")
    x = bz.add(src="facture_A-2025-0010_scan.pdf", f=sub("24403 Boyer", "24408 Boyer"))
    s = codes(bz)[1]
    assert [d.sha256 for d in s.documents if d.anomalies] == [x]


def test_line_exact(bz):
    bz.add(f=sub("13 869,45 €|", "13 869,46 €|"))
    assert "ligne_incoherente" in codes(bz)[0]


def test_no_majority_flags_all(bz):
    bz.add()
    bz.add(src="facture_A-2025-0003_scan.pdf", f=sub("**Aubry**", "**Aubri**"))
    s = codes(bz)[1]
    assert all(d.anomalies for d in s.documents)


def test_rounding_per_line_accepted(bz):
    bz.add(
        f=sub(
            "TVA 20 % 6 162,30",
            "TVA 20 % 6 162,31",
            "Total TVA 6 162,30",
            "Total TVA 6 162,31",
            "36 973,80",
            "36 973,81",
        )
    )
    assert codes(bz)[0] == set()


def test_repaired_and_lost_words(bz):
    bz.add(repaired=True)
    rec = copy.deepcopy(SRC[B][1])
    rec["pages"][0]["missing_words"] = ["x"]
    bz.add(src=B, pages=rec["pages"])
    assert codes(bz)[0] == {"pdf_repare", "texte_perdu"}


def test_bronze_damage_quarantined(bz, tmp_path):
    bz.add()
    x = bz.add(src=B)
    p = next((bz.root / x / "v").glob("*.md"))
    p.write_text(p.read_text() + "x")
    s = analyse(bz.root)
    t = write(s, tmp_path / "o")
    assert t["factures"] == 1 and t["rejets"] == 1 and summary(s)["rejetees"] == 1


@pytest.mark.parametrize("ext", ["md", "json"])
def test_bronze_file_missing(bz, tmp_path, ext):
    bz.add()
    x = bz.add(src=B)
    next((bz.root / x / "v").glob("*." + ext)).unlink()
    s = analyse(bz.root)
    assert write(s, tmp_path / "o")["rejets"] == 1


def test_bronze_record_deleted(bz, tmp_path):
    import shutil

    a = bz.add()
    x = bz.add(src=B)
    (bz.root / "index.jsonl").write_text("".join(json.dumps({"sha256": i}) + "\n" for i in (a, x)))
    shutil.rmtree(bz.root / x)
    s = analyse(bz.root)
    t = write(s, tmp_path / "o")
    assert t["factures"] == 1 and t["rejets"] == 1


def test_types_and_exactness(bz, tmp_path):
    bz.add()
    write(analyse(bz.root), tmp_path / "o")
    d = dict(
        (r[0], r[1])
        for r in duckdb.sql(f"describe select * from '{tmp_path}/o/factures.parquet'").fetchall()
    )
    assert d["total_ttc"] == "DECIMAL(14,2)" and d["date_emission"] == "DATE"
    assert not any(
        "DOUBLE" in r[1] or "FLOAT" in r[1]
        for t in ("factures", "lignes_facture", "tva_facture")
        for r in duckdb.sql(f"describe select * from '{tmp_path}/o/{t}.parquet'").fetchall()
    )


def test_failed_write_keeps_old(bz, tmp_path, monkeypatch):
    o = tmp_path / "it's o"
    bz.add()
    write(analyse(bz.root), o)
    b = {p.name: p.read_bytes() for p in o.iterdir()}
    s = analyse(bz.root)
    s.documents[0].facture.total_ttc = D(10) ** 20
    with pytest.raises(duckdb.Error):
        write(s, o)
    assert {p.name: p.read_bytes() for p in o.iterdir()} == b


def test_real_sql(tmp_path):
    s = analyse(BRONZE)
    write(s, tmp_path / "o")
    q = lambda x: duckdb.sql(x.replace("@", f"{tmp_path}/o/")).fetchall()[0][0]
    assert (
        q("select count(*) from '@factures.parquet'") == COUNT
        and q(
            "select count(*) from '@lignes_facture.parquet' l anti join '@factures.parquet' f using(facture_id)"
        )
        == 0
        and q(
            "select count(*) from (select facture_id,sum(total_ht) s from '@lignes_facture.parquet' group by 1) join '@factures.parquet' f using(facture_id) where s<>f.total_ht"
        )
        == 0
    )


def test_cli(bz, tmp_path):
    run = lambda *a: subprocess.run(
        [sys.executable, "-B", "-m", "silver", *map(str, a)], cwd=R, capture_output=True, text=True
    )
    bz.add(f=sub("36 973,80", "36 973,81"))
    r = run("build", bz.root, "--out", tmp_path / "o")
    assert (
        r.returncode == 0
        and json.loads(r.stdout)["signalees"] == 1
        and "total_ttc_incoherent" in r.stderr
    )
    bz.add(src=B, f=lambda t: t.replace("Numéro", "Nmro"))
    r = run("build", bz.root, "--out", tmp_path / "o2", "--dry-run")
    assert r.returncode == 1 and not (tmp_path / "o2").exists()
    assert run("build", tmp_path / "none").returncode == 2
