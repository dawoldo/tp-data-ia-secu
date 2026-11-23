"""What the parser extracts. Field names keep the French invoice vocabulary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ERROR = "error"      # an essential value is missing or unreadable
WARNING = "warning"  # a secondary value is missing, or something looks odd


@dataclass(frozen=True)
class Issue:
    severity: str
    field: str
    message: str


@dataclass
class Partie:
    """Supplier or client."""

    nom: str | None = None
    adresse: str | None = None
    code_postal: str | None = None
    ville: str | None = None
    siret: str | None = None
    tva_intracom: str | None = None  # supplier only


@dataclass
class LigneFacture:
    numero_ligne: int
    designation: str | None
    quantite: Decimal | None
    prix_unitaire_ht: Decimal | None
    taux_tva: Decimal | None          # percent: 20 means 20 %
    total_ht: Decimal | None


@dataclass
class TotalTva:
    taux: Decimal
    montant: Decimal


@dataclass
class Facture:
    numero: str | None = None
    date_emission: date | None = None
    date_echeance: date | None = None
    categorie: str | None = None
    statut: str | None = None
    mode_paiement: str | None = None
    iban: str | None = None
    total_ht: Decimal | None = None
    total_tva: Decimal | None = None
    total_ttc: Decimal | None = None
    detail_tva: list[TotalTva] = field(default_factory=list)
    fournisseur: Partie = field(default_factory=Partie)
    client: Partie = field(default_factory=Partie)
    lignes: list[LigneFacture] = field(default_factory=list)


@dataclass
class ParseResult:
    facture: Facture
    issues: list[Issue] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True if every essential value was read."""
        return not any(i.severity == ERROR for i in self.issues)
