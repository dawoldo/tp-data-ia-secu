"""Compare invoices with the truth, field by field."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from silver.models import Facture

EXACT, MISSING, WRONG = "exact", "manquant", "faux"

SIMPLE = (
    "numero", "date_emission", "date_echeance", "categorie", "statut", "mode_paiement",
    "iban", "total_ht", "total_tva", "total_ttc",
)
SUPPLIER = ("nom", "adresse", "code_postal", "ville", "siret", "tva_intracom")
CLIENT = ("nom", "adresse", "code_postal", "ville", "siret")
LINE = ("designation", "quantite", "prix_unitaire_ht", "taux_tva", "total_ht")
FIELDS = (
    *SIMPLE, "detail_tva", *(f"fournisseur.{n}" for n in SUPPLIER),
    *(f"client.{n}" for n in CLIENT), "nombre de lignes", *(f"ligne.{n}" for n in LINE),
)


def values(f: Facture) -> list[tuple[str, Any]]:
    """Every (field, value) of an invoice; line fields repeat, in order."""
    out: list[tuple[str, Any]] = [(n, getattr(f, n)) for n in SIMPLE]
    out.append(("detail_tva", tuple((t.taux, t.montant) for t in f.detail_tva) or None))
    out += [(f"fournisseur.{n}", getattr(f.fournisseur, n)) for n in SUPPLIER]
    out += [(f"client.{n}", getattr(f.client, n)) for n in CLIENT]
    out.append(("nombre de lignes", len(f.lignes) or None))
    for line in f.lignes:
        out += [(f"ligne.{n}", getattr(line, n)) for n in LINE]
    return out


@dataclass
class Error:
    document: str
    field: str
    expected: Any
    got: Any
    state: str          # of the document: valide, signalee, rejetee, illisible

    @property
    def silent(self) -> bool:
        return self.got is not None and self.state == "valide"


@dataclass
class Score:
    documents: int = 0
    perfect: int = 0
    states: Counter = field(default_factory=Counter)
    counts: dict[str, Counter] = field(default_factory=lambda: {f: Counter() for f in FIELDS})
    errors: list[Error] = field(default_factory=list)
    seconds: list[float] = field(default_factory=list)

    def add(self, name: str, truth: Facture, got: Facture | None, state: str) -> None:
        self.documents += 1
        self.states[state] += 1
        expected = values(truth)
        found = values(got) if got else []
        # Beyond the true lines, extra ones are counted by "nombre de lignes".
        found += [(n, None) for n, _ in expected[len(found):]]
        clean = True
        for (name_, want), (_, have) in zip(expected, found):
            outcome = EXACT if have == want else MISSING if have is None else WRONG
            self.counts[name_][outcome] += 1
            if outcome != EXACT:
                clean = False
                self.errors.append(Error(name, name_, want, have, state))
        self.perfect += clean

    def total(self, outcome: str) -> int:
        return sum(c[outcome] for c in self.counts.values())

    @property
    def size(self) -> int:
        return sum(sum(c.values()) for c in self.counts.values())

    @property
    def silent(self) -> int:
        return sum(e.silent for e in self.errors)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95 % confidence interval of a proportion; sound even at 100 %."""
    if not n:
        return 0.0, 1.0
    p = successes / n
    middle = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, middle - half), min(1.0, middle + half)
