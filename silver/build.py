"""Build the silver tables from bronze.

Silver is derived data: every build starts again from bronze and gives the same
tables for the same bronze. Each bronze document ends in exactly one place,
the table of invoices or the quarantine.
"""

from __future__ import annotations

import os
import shutil
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from .bronze import Unusable, read_documents
from .models import Partie
from .parser import parse_invoice
from .quality import REJET, Document, check_all

TABLES = {
    "factures": """
        facture_id VARCHAR PRIMARY KEY, numero VARCHAR NOT NULL,
        date_emission DATE NOT NULL, date_echeance DATE NOT NULL,
        statut VARCHAR NOT NULL, categorie VARCHAR, mode_paiement VARCHAR, iban VARCHAR,
        fournisseur_nom VARCHAR NOT NULL, fournisseur_siret VARCHAR NOT NULL,
        fournisseur_tva_intracom VARCHAR, fournisseur_adresse VARCHAR,
        fournisseur_code_postal VARCHAR, fournisseur_ville VARCHAR,
        client_nom VARCHAR NOT NULL, client_siret VARCHAR NOT NULL,
        client_adresse VARCHAR, client_code_postal VARCHAR, client_ville VARCHAR,
        total_ht DECIMAL(14,2) NOT NULL, total_tva DECIMAL(14,2) NOT NULL,
        total_ttc DECIMAL(14,2) NOT NULL,
        statut_qualite VARCHAR NOT NULL, nb_anomalies INTEGER NOT NULL,
        type_document VARCHAR NOT NULL, source VARCHAR NOT NULL, s3_key VARCHAR,
        bronze_version VARCHAR NOT NULL,
        UNIQUE (fournisseur_siret, numero)""",
    "lignes_facture": """
        facture_id VARCHAR NOT NULL, numero_ligne INTEGER NOT NULL,
        designation VARCHAR NOT NULL, quantite DECIMAL(12,2) NOT NULL,
        prix_unitaire_ht DECIMAL(14,2) NOT NULL, taux_tva DECIMAL(5,2) NOT NULL,
        total_ht DECIMAL(14,2) NOT NULL, PRIMARY KEY (facture_id, numero_ligne)""",
    "tva_facture": """
        facture_id VARCHAR NOT NULL, taux DECIMAL(5,2) NOT NULL,
        montant DECIMAL(14,2) NOT NULL""",
    "anomalies": """
        document_id VARCHAR, numero VARCHAR, source VARCHAR NOT NULL,
        code VARCHAR NOT NULL, gravite VARCHAR NOT NULL, champ VARCHAR NOT NULL,
        message VARCHAR NOT NULL""",
    "rejets": """
        document_id VARCHAR, numero VARCHAR, source VARCHAR NOT NULL, s3_key VARCHAR,
        motif VARCHAR NOT NULL, details VARCHAR NOT NULL, doublon_de VARCHAR""",
}


@dataclass
class Silver:
    documents: list[Document]
    unusable: list[Unusable]

    def rows(self) -> dict[str, list[tuple]]:
        rows: dict[str, list[tuple]] = {name: [] for name in TABLES}
        for doc in self.documents:
            f, record = doc.facture, doc.record
            s3_key = (record.get("origin") or {}).get("s3_key")
            for a in doc.anomalies:
                rows["anomalies"].append((doc.sha256, f.numero, record["source"], a.code,
                                          a.gravite, a.champ, a.message))
            if doc.rejete:
                causes = [a for a in doc.anomalies if a.gravite == REJET]
                rows["rejets"].append((
                    doc.sha256, f.numero, record["source"], s3_key, causes[0].code,
                    " ; ".join(f"{a.champ} : {a.message}" for a in causes), doc.doublon_de))
                continue
            rows["factures"].append((
                doc.sha256, f.numero, f.date_emission, f.date_echeance, f.statut, f.categorie,
                f.mode_paiement, f.iban, *_supplier(f.fournisseur), *_client(f.client),
                f.total_ht, f.total_tva, f.total_ttc,
                "signalee" if doc.anomalies else "valide", len(doc.anomalies),
                record["kind"], record["source"], s3_key, record["version"]))
            rows["lignes_facture"] += [
                (doc.sha256, l.numero_ligne, l.designation, l.quantite, l.prix_unitaire_ht,
                 l.taux_tva, l.total_ht) for l in f.lignes]
            rows["tva_facture"] += [(doc.sha256, t.taux, t.montant) for t in f.detail_tva]
        for bad in self.unusable:
            rows["anomalies"].append((None, None, bad.source, "bronze_inutilisable", REJET,
                                      "document", bad.reason))
            rows["rejets"].append((None, None, bad.source, None, "bronze_inutilisable",
                                   bad.reason, None))
        return rows


def _supplier(p: Partie) -> tuple:
    return p.nom, p.siret, p.tva_intracom, p.adresse, p.code_postal, p.ville


def _client(p: Partie) -> tuple:
    return p.nom, p.siret, p.adresse, p.code_postal, p.ville


def analyse(bronze: Path) -> Silver:
    documents, unusable = read_documents(bronze)
    docs = [
        Document(record["sha256"], record, parse_invoice(markdown))
        for markdown, record in documents
    ]
    check_all(docs)
    return Silver(docs, unusable)


def _literal(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def write(silver: Silver, out: Path) -> dict[str, int]:
    """Write one Parquet file per table. Nothing is replaced unless all succeed."""
    rows = silver.rows()
    total = len(silver.documents) + len(silver.unusable)
    if len(rows["factures"]) + len(rows["rejets"]) != total:
        raise RuntimeError("a document was lost or counted twice")  # must never happen
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / f".tmp-{uuid.uuid4().hex}"
    tmp.mkdir()
    try:
        with duckdb.connect() as db:
            db.execute("SET threads = 1")  # same bronze, same bytes
            for name, columns in TABLES.items():
                db.execute(f"CREATE TABLE {name} ({columns})")
                if rows[name]:
                    marks = ", ".join("?" * len(rows[name][0]))
                    db.executemany(f"INSERT INTO {name} VALUES ({marks})", rows[name])
                db.execute(f"COPY (SELECT * FROM {name} ORDER BY ALL) "
                           f"TO {_literal(tmp / (name + '.parquet'))} (FORMAT parquet)")
        for name in TABLES:
            os.replace(tmp / f"{name}.parquet", out / f"{name}.parquet")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {name: len(r) for name, r in rows.items()}


def summary(silver: Silver) -> dict[str, Any]:
    kept = [d for d in silver.documents if not d.rejete]
    return {
        "documents": len(silver.documents) + len(silver.unusable),
        "valides": sum(not d.anomalies for d in kept),
        "signalees": sum(bool(d.anomalies) for d in kept),
        "rejetees": len(silver.documents) - len(kept) + len(silver.unusable),
        "anomalies": dict(sorted(Counter(
            a.code for d in silver.documents for a in d.anomalies).items())),
    }
