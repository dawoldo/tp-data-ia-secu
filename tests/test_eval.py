import copy
from decimal import Decimal as D

from common import DATA

from evaluation.__main__ import real_truth
from evaluation.compare import FIELDS, Score, values, wilson
from evaluation.report import render
from evaluation.synth import make_scan, pick

T = real_truth()
F = T["facture_GPE-2025-0003_scan.pdf"]


def sc(mut=None, state="valide"):
    g = copy.deepcopy(F)
    mut and mut(g)
    s = Score()
    s.add("x", F, g, state)
    return s


def test_identical():
    s = sc()
    assert s.perfect == 1 and s.total("exact") == s.size == len(values(F)) and not s.errors


def test_wrong_is_silent_only_when_valid():
    m = lambda g: setattr(g, "total_ttc", D("1"))
    assert (
        sc(m).silent == 1
        and sc(m, "signalee").silent == 0
        and sc(m).total("faux") == 1
        and sc(m).perfect == 0
    )


def test_missing_not_silent():
    s = sc(lambda g: setattr(g, "iban", None))
    assert s.total("manquant") == 1 and s.silent == 0


def test_lost_last_line():
    s = sc(lambda g: g.lignes.pop())
    assert (
        s.counts["nombre de lignes"]["faux"] == 1
        and s.counts["ligne.total_ht"]["manquant"] == 1
        and s.size == len(values(F))
    )


def test_extra_line():
    s = sc(lambda g: g.lignes.append(g.lignes[0]))
    assert s.total("faux") == 1 and s.size == len(values(F)) and s.perfect == 0


def test_unreadable_document():
    s = Score()
    s.add("x", F, None, "illisible")
    assert s.total("manquant") == s.size == len(values(F)) and s.perfect == 0


def test_every_field_detected():
    for n in FIELDS:

        def m(g, n=n):
            if n.startswith("ligne."):
                setattr(g.lignes[0], n[6:], "?")
            elif "." in n:
                a, b = n.split(".")
                setattr(getattr(g, a), b, "?")
            elif n == "detail_tva":
                g.detail_tva.clear()
            elif n == "nombre de lignes":
                g.lignes.pop()
            else:
                setattr(g, n, "?")

        s = sc(m)
        assert s.counts[n]["exact"] < sum(s.counts[n].values()), n


def test_wilson():
    assert wilson(0, 0) == (0, 1)
    a, b = wilson(20, 20)
    assert 0.83 < a < 0.84 and b == 1
    a, b = wilson(10, 20)
    assert a < 0.5 < b


def test_truth_is_arithmetically_sound():
    for n, f in T.items():
        assert (
            sum(l.total_ht for l in f.lignes) == f.total_ht
            and f.total_ht + f.total_tva == f.total_ttc
            and all(l.quantite * l.prix_unitaire_ht == l.total_ht for l in f.lignes)
        ), n


def test_synth_deterministic_and_image_only():
    import pymupdf

    b = (DATA / "facture_A-2025-0001_texte.pdf").read_bytes()
    x = make_scan(b)
    assert x == make_scan(b)
    d = pymupdf.open(stream=x, filetype="pdf")
    assert not d[0].get_text().strip() and len(d[0].get_images()) == 1


def test_pick():
    n = [f"facture_{p}-2025-{i:04}_texte.pdf" for p in "ABC" for i in range(5)]
    assert (
        pick(n, 6) == pick(n[::-1], 6)
        and len({x.split("-")[0] for x in pick(n, 3)}) == 3
        and len(pick(n, 99)) == 15
    )


def test_render():
    r = render({("reel", 650): sc(lambda g: setattr(g, "iban", "x")), ("reel", 1540): sc()})
    assert "| reel | 650 |" in r and "iban" in r and r.count("|---") > 5
