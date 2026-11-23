import json
import re
import subprocess
import sys
from decimal import Decimal as D

import pytest
from common import BRONZE, COUNT, ROOT, SRC

R = str(ROOT)
from silver.parser import parse_amount as PA
from silver.parser import parse_invoice as P

FILES = [m for m, _ in SRC.values()]
T, O, O1 = (
    SRC[n][0]
    for n in (
        "facture_A-2025-0001_texte.pdf",
        "facture_BS-2026-0009_scan.pdf",
        "facture_A-2026-0007_scan.pdf",
    )
)


def html2pipe(t):
    def c(m):
        rows = [
            re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.S)
            for r in re.findall(r"<tr>(.*?)</tr>", m[0], re.S)
        ]
        o = ["|" + "|".join(r) + "|" for r in rows]
        o.insert(1, "|" + "---|" * len(rows[0]))
        return "\n" + "\n".join(o) + "\n"

    return re.sub(r"<table>.*?</table>", c, t, flags=re.S)


FMT = {
    "nobold": lambda t: t.replace("**", ""),
    "nbsp": lambda t: re.sub(r"(?<=\d) (?=[\d€%])", " ", t),
    "nnbsp": lambda t: re.sub(r"(?<=\d) (?=[\d€%])", " ", t),
    "curly": lambda t: t.replace("Date d'", "Date d’"),
    "upper_labels": lambda t: (
        re.sub(
            r"(Numéro de facture|Statut|Total HT|Total TTC|Mode de paiement)(?=[\s*:]+)",
            lambda m: m[0].upper(),
            t,
        )
        if "<th>Total HT" not in t and "|Total HT" not in t
        else t
    ),
    "noaccent_labels": lambda t: (
        t.replace("Date d'échéance", "Date d'echeance")
        .replace("Numéro", "Numero")
        .replace("Désignation", "Designation")
    ),
    "boldvals": lambda t: re.sub(r"^(Statut|IBAN) : (.*)$", r"\1 : **\2**", t, flags=re.M),
    "colon_in_bold": lambda t: re.sub(r"\*\*([^*\n]+)\*\* : ", r"**\1 :** ", t),
    "nospace_colon": lambda t: t.replace(" : ", ": "),
    "blanklines": lambda t: re.sub(r"\n(?!\||\s*<)", "\n\n", t),
    "html2pipe": html2pipe,
    "crlf": lambda t: t.replace("\n", "\r\n"),
    "bullets": lambda t: re.sub(r"^(Statut|IBAN|Catégorie|Total)", r"- \1", t, flags=re.M),
    "entities": lambda t: t.replace("€", "&euro;"),
    "colon_totals": lambda t: re.sub(r"^(\**Total (?:HT|TVA|TTC)\**) ", r"\1 : ", t, flags=re.M),
    "headings": lambda t: re.sub(r"^(\**Facturé à)", r"### \1", t, flags=re.M),
    "attrs": lambda t: t.replace("<td>", '<td align="right">'),
    "nfd": lambda t: __import__("unicodedata").normalize("NFD", t),
}


@pytest.mark.parametrize("k", FMT)
def test_format_invariant(k):
    for f in FILES:
        t = f
        a, b = P(t), P(FMT[k](t))
        assert a.complete and a.facture == b.facture, b.issues


def test_every_single_char_digit_drop_is_never_silently_dropped():
    # removing any label => field None + issue, other fields intact
    base = P(T).facture
    for lab, fld in [
        ("Numéro de facture : ", "numero"),
        ("Date d'émission : ", "date_emission"),
        ("Statut : ", "statut"),
        ("IBAN : ", "iban"),
    ]:
        r = P(T.replace(lab, ""))
        assert getattr(r.facture, fld) is None and any(i.field == fld for i in r.issues)


@pytest.mark.parametrize("src", [T, O, O1])
def test_any_deleted_line_is_reported(src):
    """Deleting any content line either leaves the result unchanged or raises an issue (or only drops a whole item row / optional line)."""
    base = P(src).facture
    L = src.split("\n")
    silent = []
    for i, l in enumerate(L):
        r = P("\n".join(L[:i] + L[i + 1 :]))
        if r.facture != base and not r.issues:
            silent.append(l)
    print(silent)
    assert all(
        re.match(r"^\|[A-ZÉ]", l) or re.search(r"</?t[rd]|</?th|</?tbody|</?thead", l)
        for l in silent
    ), silent


@pytest.mark.parametrize(
    "a,b,fld",
    [
        ("36 973,80", "36 973,8", "total_ttc"),
        ("36 973,80", "36 9T3,80", "total_ttc"),
        ("36 973,80", "36 97 3,80", "total_ttc"),
        ("10/01/2025", "1O/01/2025", "date_emission"),
        ("10/01/2025", "31/02/2025", "date_emission"),
        ("Statut : Payée", "Statut : Pavée", "statut"),
        ("SIRET : 77360260298050", "SIRET : 7736026029805", "fournisseur.siret"),
        ("SIRET client : 20037917087083", "SIRET client : 2003791708708X", "client.siret"),
        ("|13 869,45 €|", "|13 869 €|", "lignes[1].total_ht"),
        ("|9|", "|g|", "lignes[1].quantite"),
        ("FR1578820812191361939909169", "FR15?", "iban"),
        ("Date d'émission : 10/01/2025", "Date d'émission : 10/01/2025 Lombard", "date_emission"),
    ],
)
def test_corrupt(a, b, fld):
    assert a in T
    r = P(T.replace(a, b))
    assert any(i.field == fld for i in r.issues), r.issues
    assert (fld == "iban") or not r.complete


def test_conflict():
    r = P(T + "\nTotal TTC 1,00 €\n")
    assert r.facture.total_ttc is None and not r.complete


def test_unlabelled_client_siret_not_mixed():
    r = P(T.replace("SIRET client", "SIRET"))
    assert r.facture.fournisseur.siret is None and not r.complete


def test_stamp_before_name():
    r = P(T.replace("**Aubry**", "DUPLICATA\nPage 1/1\n**Aubry**"))
    assert not r.complete and r.facture.fournisseur.nom is None


def test_stamp_one_line_before_name():
    r = P(T.replace("**Aubry**", "DUPLICATA\n**Aubry**"))
    print(r.facture.fournisseur)
    assert r.facture.fournisseur.nom != "DUPLICATA" or r.issues


def test_name_lost():
    for a in ("**Aubry**\n", "96, avenue de Meyer\n"):
        r = P(T.replace(a, ""))
        assert r.issues, (a, r.facture.fournisseur)
    assert not P(T.replace("**Aubry**\n", "")).complete


def test_stamp_replaces_street():
    assert not P(
        T.replace("96, avenue de Meyer\n", "").replace("**Aubry**", "PAYÉ\n**Aubry**")
    ).complete


def test_two_pages():
    a = T.replace(
        "|Journée",
        "\n<!-- page: 2 -->\n\n|Désignation|Qté|Prix unitaire HT|TVA|Total HT|\n|---|---|---|---|---|\n|Journée",
    )
    assert P(a).facture == P(T).facture
    b = T.replace("|Journée", "\n<!-- page: 2 -->\n\n|Journée")
    assert P(b).facture == P(T).facture


def test_totals_in_item_table():
    t = re.sub(r"\n+(\**Total (?:HT|TVA|TTC)\**|TVA 20 %) (.*?)(?=\n)", r"\n|||\1||\2|", T)
    t = re.sub(r"\|\n\n+\|\|\|", "|\n|||", t)
    assert P(t).facture == P(T).facture, P(t).issues


def test_layout_table():
    t = T.replace(
        "Numéro de facture : A-2025-0001\nDate d'émission : 10/01/2025\n",
        "|Numéro de facture : A-2025-0001|Date d'émission : 10/01/2025|\n|---|---|\n\n",
    )
    assert P(t).facture == P(T).facture
    t = T.replace("Statut : Payée", "|Statut :|Payée|\n|---|---|\n")
    assert P(t).facture == P(T).facture


def test_label_on_own_line():
    t = T.replace("Statut : Payée", "Statut :\nPayée").replace(
        "Total HT 30 811,50 €", "Total HT\n\n30 811,50 €"
    )
    assert P(t).facture == P(T).facture, P(t).issues


def test_total_named_product():
    r = P(T.replace("|Formation DuckDB et Parquet|", "|Total TTC formation|"))
    assert len(r.facture.lignes) == 3 and r.facture.lignes[0].designation == "Total TTC formation"


def test_multi_vat():
    r = P(T.replace("TVA 20 % 6 162,30 €", "TVA 20 % 6 000,00 €\n\nTVA 5,5 % 162,30 €"))
    assert [(str(x.taux), x.montant) for x in r.facture.detail_tva] == [
        ("20", D("6000.00")),
        ("5.5", D("162.30")),
    ]


@pytest.mark.parametrize(
    "t",
    [
        "",
        "<!-- page: 1 -->",
        "hello",
        "|a|b|\n|---|",
        "<table><tr><td>",
        "# FACTURE\n" * 50,
        "<table></table>",
    ],
)
def test_garbage(t):
    r = P(t)
    assert not r.complete


@pytest.mark.parametrize(
    "t", ["1,541.05", "1.541", "12 34,05", "", "€", "1 541,05 $", "1e3", "٣,٠٠"]
)
def test_amount_rejected(t):
    with pytest.raises(ValueError):
        PA(t)


@pytest.mark.parametrize(
    "t,v",
    [
        ("1 541,05 €", "1541.05"),
        ("1541,05", "1541.05"),
        ("1.541,05 EUR", "1541.05"),
        ("-40,00 €", "-40.00"),
        ("0,99€", "0.99"),
        ("1 234 567,89 €", "1234567.89"),
    ],
)
def test_amount(t, v):
    assert PA(t) == D(v)


def test_no_float_json():
    p = subprocess.run(
        [sys.executable, "-B", "-m", "silver", "parse", "--json", str(BRONZE)],
        cwd=R,
        capture_output=True,
        text=True,
    )
    x = [json.loads(l) for l in p.stdout.splitlines()]
    assert (
        p.returncode == 0
        and len(x) == COUNT
        and isinstance(x[0]["facture"]["total_ttc"], str)
        and x[0]["sha256"]
    )


def test_cli_missing(tmp_path):
    (tmp_path / "a.pdf.md").write_text(T)
    p = subprocess.run(
        [sys.executable, "-B", "-m", "silver", "parse", str(tmp_path)],
        cwd=R,
        capture_output=True,
        text=True,
    )
    assert p.returncode == 1 and "unusable" in p.stderr
