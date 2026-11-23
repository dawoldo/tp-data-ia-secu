"""Quality checks. They describe problems; they never change a value.

REJET: the invoice cannot be used (unreadable or duplicate) and goes to quarantine.
SIGNALEMENT: it is readable but doubtful; it is kept, with the reason.

Not checked on purpose: the SIRET checksum and the VAT number key. The invoices of
this project are fictional and almost none would pass.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..models import ERROR, Facture, ParseResult, Partie

REJET = "rejet"
SIGNALEMENT = "signalement"

CENT = Decimal("0.01")
TAUX_TVA = {Decimal(t) for t in ("0", "2.1", "5.5", "8.5", "10", "20")}
DELAIS = {0, 15, 30, 45, 60}        # usual payment terms, in days; 60 is the legal maximum
MODES_PAIEMENT = {"Carte bancaire", "Chèque", "Prélèvement SEPA", "Virement bancaire"}
MONTANT_MAX = Decimal(10) ** 12     # what the silver tables can hold


@dataclass(frozen=True)
class Anomalie:
    code: str
    gravite: str
    champ: str
    message: str


@dataclass
class Document:
    """One invoice, with where it comes from and what is wrong with it."""

    sha256: str
    record: dict[str, Any]          # bronze record
    result: ParseResult
    anomalies: list[Anomalie] = field(default_factory=list)
    doublon_de: str | None = None   # sha256 of the document kept instead

    @property
    def facture(self) -> Facture:
        return self.result.facture

    @property
    def rejete(self) -> bool:
        return any(a.gravite == REJET for a in self.anomalies)

    def add(self, code: str, champ: str, message: str, gravite: str = SIGNALEMENT) -> None:
        self.anomalies.append(Anomalie(code, gravite, champ, message))


# --- One invoice on its own ---------------------------------------------------

Problem = tuple[str, str, str]  # code, field, message


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def check_amounts(f: Facture) -> Iterator[Problem]:
    for l in f.lignes:
        if _cents(l.quantite * l.prix_unitaire_ht) != l.total_ht:
            yield ("ligne_incoherente", f"lignes[{l.numero_ligne}].total_ht",
                   f"{l.quantite} x {l.prix_unitaire_ht} = "
                   f"{_cents(l.quantite * l.prix_unitaire_ht)}, indiqué {l.total_ht}")
        if l.quantite <= 0 or l.prix_unitaire_ht < 0:
            yield ("ligne_incoherente", f"lignes[{l.numero_ligne}]",
                   f"quantité {l.quantite}, prix unitaire {l.prix_unitaire_ht}")
    somme = sum((l.total_ht for l in f.lignes), Decimal(0))
    if somme != f.total_ht:
        yield ("somme_lignes", "total_ht", f"somme des lignes {somme}, indiqué {f.total_ht}")
    if f.total_ht + f.total_tva != f.total_ttc:
        yield ("total_ttc_incoherent", "total_ttc",
               f"HT + TVA = {f.total_ht + f.total_tva}, indiqué {f.total_ttc}")
    if f.total_ttc <= 0:
        yield "montant_non_positif", "total_ttc", f"total TTC {f.total_ttc}"


def check_vat(f: Facture) -> Iterator[Problem]:
    bases: dict[Decimal, list[Decimal]] = defaultdict(list)
    for l in f.lignes:
        bases[l.taux_tva].append(l.total_ht)
    for taux in sorted(bases):
        if taux not in TAUX_TVA:
            yield "taux_tva_inconnu", "taux_tva", f"{taux} % n'est pas un taux français"
    if not f.detail_tva:
        return  # already reported by the parser
    somme = sum((t.montant for t in f.detail_tva), Decimal(0))
    if somme != f.total_tva:
        yield ("total_tva_incoherent", "total_tva",
               f"somme par taux {somme}, indiqué {f.total_tva}")
    if {t.taux for t in f.detail_tva} != set(bases):
        yield ("detail_tva_incoherent", "detail_tva",
               "les taux du récapitulatif ne sont pas ceux des lignes")
    for t in f.detail_tva:
        lignes = bases.get(t.taux, [])
        attendu = _cents(sum(lignes, Decimal(0)) * t.taux / 100)
        # VAT may be rounded once or per line: half a cent of slack for each.
        if abs(attendu - t.montant) > CENT / 2 * (len(lignes) + 1):
            yield ("tva_incoherente", "detail_tva",
                   f"{t.taux} % : calculé {attendu}, indiqué {t.montant}")


def check_dates(f: Facture) -> Iterator[Problem]:
    jours = (f.date_echeance - f.date_emission).days
    if jours < 0:
        yield ("echeance_avant_emission", "date_echeance",
               f"échéance {f.date_echeance} avant émission {f.date_emission}")
    elif jours not in DELAIS:
        # The only clue when a day or a month is misread.
        yield "delai_inhabituel", "date_echeance", f"échéance à {jours} jours"
    annee = re.fullmatch(r"[A-Z]+-(\d{4})-\d+", f.numero)
    if annee and int(annee[1]) != f.date_emission.year:
        yield ("annee_incoherente", "date_emission",
               f"émise en {f.date_emission.year}, numéro {f.numero}")


def iban_valid(iban: str) -> bool:
    moved = iban[4:] + iban[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def check_identifiers(f: Facture) -> Iterator[Problem]:
    if f.iban and (not iban_valid(f.iban) or (f.iban.startswith("FR") and len(f.iban) != 27)):
        yield "iban_invalide", "iban", f"clé de contrôle ou longueur incorrecte : {f.iban}"
    tva = f.fournisseur.tva_intracom
    if tva and tva[4:] != f.fournisseur.siret[:9]:
        yield ("tva_intracom_incoherente", "fournisseur.tva_intracom",
               f"{tva} ne contient pas le SIREN du SIRET {f.fournisseur.siret}")
    if f.fournisseur.siret == f.client.siret:
        yield "fournisseur_egal_client", "client.siret", "même SIRET que le fournisseur"


def check_payment(f: Facture) -> Iterator[Problem]:
    if f.mode_paiement and f.mode_paiement not in MODES_PAIEMENT:
        yield "mode_paiement_inconnu", "mode_paiement", f.mode_paiement


CHECKS: tuple[Callable[[Facture], Iterable[Problem]], ...] = (
    check_amounts, check_vat, check_dates, check_identifiers, check_payment,
)


def _too_large(f: Facture) -> bool:
    values = [f.total_ht, f.total_tva, f.total_ttc, *(t.montant for t in f.detail_tva)]
    for l in f.lignes:
        values += [l.prix_unitaire_ht, l.total_ht, l.quantite * 100]
    return any(abs(v) >= MONTANT_MAX for v in values)


def check_document(doc: Document) -> None:
    """All checks that need only this document."""
    for issue in doc.result.issues:
        if issue.severity == ERROR:
            doc.add("lecture_incomplete", issue.field, issue.message, REJET)
        else:
            doc.add("lecture_partielle", issue.field, issue.message)
    if doc.rejete:
        return  # the other checks need every essential value
    f = doc.facture
    if _too_large(f):
        doc.add("valeur_hors_limites", "montants", "montant ou quantité démesuré", REJET)
        return
    for check in CHECKS:
        for code, champ, message in check(f):
            doc.add(code, champ, message)
    _check_origin(doc)


def _check_origin(doc: Document) -> None:
    f, record = doc.facture, doc.record
    if record.get("repaired"):
        doc.add("pdf_repare", "document", "PDF endommagé, du contenu peut manquer")
    if any(p.get("missing_words") for p in record.get("pages", [])):
        doc.add("texte_perdu", "document", "des mots du PDF manquent dans le Markdown")
    nom = re.search(r"(?<![A-Z0-9])[A-Z]+-\d{4}-\d+(?!\d)", record["source"].rsplit("/", 1)[-1])
    if nom and nom[0] != f.numero:
        doc.add("nom_fichier", "numero", f"lu {f.numero}, fichier {record['source']}")
    # The day we received the file, not today: a rebuild must give the same result.
    origin = record.get("origin") or {}
    recu = date.fromisoformat((origin.get("pulled_at") or record["converted_at"])[:10])
    if f.date_emission > recu:
        doc.add("emission_future", "date_emission",
                f"émise le {f.date_emission}, reçue le {recu}")
    if f.statut == "En retard" and f.date_echeance >= recu:
        doc.add("statut_incoherent", "statut",
                f"en retard, mais échéance {f.date_echeance} et réception {recu}")


# --- Invoices compared with each other ----------------------------------------

def _preference(doc: Document) -> tuple:
    """Which of several copies to keep: native text first, then the oldest."""
    origin = doc.record.get("origin") or {}
    return (doc.record["kind"] != "text", origin.get("last_modified") or "9", doc.sha256)


def check_duplicates(docs: list[Document]) -> None:
    """At most one document per supplier and invoice number."""
    groups: dict[tuple, list[Document]] = defaultdict(list)
    for doc in docs:
        groups[doc.facture.fournisseur.siret, doc.facture.numero].append(doc)
    for group in groups.values():
        kept, *others = sorted(group, key=_preference)
        for other in others:
            other.doublon_de = kept.sha256
            if other.facture == kept.facture:
                other.add("doublon", "numero", f"déjà présente : {kept.record['source']}", REJET)
            else:
                other.add("doublon_contradictoire", "numero",
                          f"même numéro, contenu différent : {kept.record['source']}", REJET)
                kept.add("doublon_contradictoire", "numero",
                         f"même numéro, contenu différent : {other.record['source']}")

    same: dict[tuple, list[Document]] = defaultdict(list)
    for doc in docs:
        if not doc.rejete:
            f = doc.facture
            lines = tuple((l.designation, l.quantite, l.prix_unitaire_ht) for l in f.lignes)
            same[f.fournisseur.siret, f.client.siret, f.date_emission, lines].append(doc)
    for group in same.values():
        for doc in group if len(group) > 1 else []:
            autres = ", ".join(sorted(d.facture.numero for d in group if d is not doc))
            doc.add("doublon_probable", "numero", f"même contenu que {autres}")


def _address(p: Partie) -> str:
    return f"{p.adresse}, {p.code_postal} {p.ville}"


_LINKS: tuple[tuple[str, str, Callable[[Facture], Any], Callable[[Facture], Any]], ...] = (
    # field, label, company, value that must be stable for that company
    ("fournisseur.nom", "nom", lambda f: f.fournisseur.siret, lambda f: f.fournisseur.nom),
    ("fournisseur.siret", "SIRET", lambda f: f.fournisseur.nom, lambda f: f.fournisseur.siret),
    ("fournisseur.tva_intracom", "numéro de TVA",
     lambda f: f.fournisseur.siret, lambda f: f.fournisseur.tva_intracom),
    ("fournisseur.adresse", "adresse",
     lambda f: f.fournisseur.siret, lambda f: _address(f.fournisseur)),
    ("iban", "IBAN", lambda f: f.fournisseur.siret, lambda f: f.iban),
    ("client.nom", "nom", lambda f: f.client.siret, lambda f: f.client.nom),
    ("client.siret", "SIRET", lambda f: f.client.nom, lambda f: f.client.siret),
    ("client.adresse", "adresse", lambda f: f.client.siret, lambda f: _address(f.client)),
)


def check_consistency(docs: list[Document]) -> None:
    """A company keeps its name, identifiers and address from one invoice to the next.

    The less frequent value is flagged; without a majority, all are.
    """
    for champ, label, key, value in _LINKS:
        groups: dict[Any, list[Document]] = defaultdict(list)
        for doc in docs:
            if value(doc.facture) is not None:
                groups[key(doc.facture)].append(doc)
        for company, group in groups.items():
            counts = Counter(value(d.facture) for d in group)
            if len(counts) == 1:
                continue
            top = max(counts.values())
            usual = {v for v, n in counts.items() if n == top}
            for doc in group:
                mine = value(doc.facture)
                if len(usual) > 1 or mine not in usual:
                    others = ", ".join(sorted(str(v) for v in counts if v != mine))
                    doc.add("identite_variable", champ,
                            f"{label} {mine} pour {company}, ailleurs : {others}")


def check_all(docs: list[Document]) -> None:
    for doc in docs:
        check_document(doc)
    usable = [d for d in docs if not d.rejete]
    check_duplicates(usable)
    check_consistency([d for d in usable if not d.rejete])
