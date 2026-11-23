"""Extract an invoice from bronze Markdown, whatever its source.

Principles:
- values are found by their label, never by position or formatting;
- a value must match its expected format entirely, otherwise it stays empty;
- nothing is guessed or corrected: every doubt becomes an Issue.

Business checks (do the amounts add up? is the SIRET valid?) are not done here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

from .markdown import Block, Table, clean, fold, read_blocks
from .models import (
    ERROR, WARNING, Facture, Issue, LigneFacture, ParseResult, Partie, TotalTva,
)

# --- Values -----------------------------------------------------------------

# re.A everywhere: \d must only accept 0-9.
_AMOUNT = re.compile(r"(-?)\s?(\d{1,3}(?:[ .]\d{3})+|\d+)[,.](\d{2})", re.A)
_STATUTS = {"payee": "Payée", "en attente": "En attente", "en retard": "En retard"}


def parse_amount(text: str) -> Decimal:
    """French amount: "1 541,05 €" -> Decimal("1541.05")."""
    bare = re.sub(r"\s?(?:€|EUR)$", "", text.strip(), flags=re.I)
    match = _AMOUNT.fullmatch(bare)
    if not match:
        raise ValueError("montant illisible")
    sign, whole, cents = match.groups()
    return Decimal(f"{sign}{re.sub(r'[ .]', '', whole)}.{cents}")


def parse_quantity(text: str) -> Decimal:
    if not re.fullmatch(r"\d{1,3}(?: \d{3})+|\d+(?:[,.]\d{1,2})?", text.strip(), re.A):
        raise ValueError("quantité illisible")
    return Decimal(text.replace(" ", "").replace(",", "."))


def parse_rate(text: str) -> Decimal:
    match = re.fullmatch(r"(\d{1,2}(?:[,.]\d{1,2})?)\s?%", text.strip(), re.A)
    if not match:
        raise ValueError("taux de TVA illisible")
    return Decimal(match[1].replace(",", "."))


def parse_date(text: str) -> date:
    match = re.fullmatch(r"(\d{2})([/.-])(\d{2})\2(\d{4})", text.strip(), re.A)
    if not match:
        raise ValueError("date illisible (JJ/MM/AAAA attendu)")
    return date(int(match[4]), int(match[3]), int(match[1]))


def _pattern(regex: str, what: str, squeeze: bool = False) -> Callable[[str], str]:
    def parse(text: str) -> str:
        value = re.sub(r"\s", "", text) if squeeze else text.strip()
        if not re.fullmatch(regex, value, re.A):
            raise ValueError(f"{what} illisible")
        return value
    return parse


def parse_text(text: str) -> str:
    if not text.strip():
        raise ValueError("vide")
    return text.strip()


def parse_statut(text: str) -> str:
    try:
        return _STATUTS[fold(text.strip())]
    except KeyError:
        raise ValueError("statut inconnu") from None


parse_siret = _pattern(r"\d{14}", "SIRET (14 chiffres)", squeeze=True)
parse_iban = _pattern(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", "IBAN", squeeze=True)
parse_tva_number = _pattern(r"FR[0-9A-Z]{2}\d{9}", "numéro de TVA", squeeze=True)
parse_numero = _pattern(r"(?=.*\d)[A-Z0-9]+(?:[-/_][A-Z0-9]+)*", "numéro de facture")

# --- Labels -----------------------------------------------------------------

# Matched on folded text (no accents, lower case) and followed by a colon.
# Longer labels come first: "siret client" must win over "siret" and "client".
_LABELS = {
    "numero": r"(?:numero de facture|facture n[o°]|n[o°] de facture)",
    "date_emission": r"date d'emission|date de facture",
    "date_echeance": r"date d'echeance",
    "categorie": r"categorie",
    "statut": r"statut",
    "mode_paiement": r"mode de paiement",
    "iban": r"iban",
    "siret_client": r"siret client",
    "siret": r"siret",
    "tva_intracom": r"(?:n[o°] )?tva intracom(?:munautaire)?\.?",
    "facture_a": r"facture a",
    "client": r"client",
}
_LABEL_RE = re.compile(
    r"(?<![\w'])(?:" + "|".join(f"(?P<{k}>{v})" for k, v in _LABELS.items()) + r")\s*:"
)
_FACTURE_A_ALONE = re.compile(r"facture a")

# Totals start a line; the colon is optional.
_TOTAL_RE = re.compile(
    r"(?:(?P<total_ht>(?:total|montant) (?:ht|h\.t\.))"
    r"|(?P<total_tva>(?:total|montant) (?:tva|t\.v\.a\.))"
    r"|(?P<total_ttc>(?:total|montant) (?:ttc|t\.t\.c\.)|net a payer)"
    r"|(?P<tva>tva \(?(?P<taux>\d{1,2}(?:[,.]\d{1,2})?\s?%)\)?))"
    r"\s*:?\s*(?P<value>(?:[-\d].*)?)"
)

# A street line: a house number, or a street word such as "rue Carpentier".
_STREET = re.compile(
    r"\d+\s*(?:bis|ter|quater|[a-d])?\s*,|(?:\d+\s*(?:bis|ter|quater|[a-d])?,?\s+)?"
    r"(?:rue|avenue|av\.|boulevard|bd|chemin|place|allee|impasse|route|quai|cours|square|"
    r"passage|sentier|faubourg|zone|lieu-dit|residence|bp)\b", re.A
)

# --- Item table -------------------------------------------------------------

_COLUMNS = {
    "designation": ("designation", "description", "libelle"),
    "quantite": ("qte", "quantite"),
    "prix_unitaire_ht": ("prix unitaire", "p.u", "pu ht"),
    "taux_tva": ("tva",),
    "total_ht": ("total", "montant"),
}


def _columns(header: list[str]) -> dict[str, int] | None:
    """Map each field to its column, or None if this is not an item header."""
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        name = fold(clean(cell))
        for column, keys in _COLUMNS.items():
            if column not in found and name.startswith(keys):
                found[column] = index
                break
    return found if len(found) == len(_COLUMNS) else None


def _is_total_row(cells: list[str]) -> bool:
    """A total inside the item table: a total label, and no quantity or price.

    The numbers decide, so that a product called "Total ..." stays an item.
    """
    filled = [c for c in cells if c]
    return (
        any(_TOTAL_RE.match(fold(c)) for c in filled)
        and sum(bool(re.match(r"-?\d", c)) for c in filled) <= 1
    )


def _row_lines(cells: list[str]) -> list[str]:
    """Turn a row of a layout table back into text lines."""
    parts = [p for c in cells for p in c.split("\n") if p]
    labelled = any(_LABEL_RE.search(fold(p)) for p in parts)
    if not labelled:
        return [" ".join(parts)] if parts else []
    lines: list[str] = []
    for part in parts:  # "Statut :" | "Payée" is one line, two labels are two
        if lines and lines[-1].endswith(":"):
            lines[-1] += " " + part
        else:
            lines.append(part)
    return lines


# --- Parser -----------------------------------------------------------------

class _Parser:
    def __init__(self, markdown: str) -> None:
        self.facture = Facture()
        self.issues: list[Issue] = []
        self.lines: list[str] = []
        self.item_rows: list[tuple[dict[str, int], list[str]]] = []
        self._split(read_blocks(markdown))

    def issue(self, severity: str, field: str, message: str) -> None:
        self.issues.append(Issue(severity, field, message))

    def _split(self, blocks: list[Block]) -> None:
        """Separate item rows from everything else, kept as text lines."""
        columns: dict[str, int] | None = None
        width = 0
        for block in blocks:
            if isinstance(block, str):
                self.lines.append(block)
                continue
            inside = False
            for number, row in enumerate(block.rows):
                header = _columns(row)
                if header:
                    columns, width, inside = header, len(row), True
                elif number == 0 and columns and len(row) == width and self._reads(columns, row):
                    inside = True  # table continued on the next page, no header
                    self.item_rows.append((columns, row))
                elif inside and columns and not _is_total_row(row):
                    if any(row):
                        self.item_rows.append((columns, row))
                else:
                    self.lines += _row_lines(row)

    @staticmethod
    def _reads(columns: dict[str, int], row: list[str]) -> bool:
        try:
            parse_quantity(row[columns["quantite"]])
            parse_amount(row[columns["total_ht"]])
        except ValueError:
            return False
        return True

    def run(self) -> ParseResult:
        values = self._labelled_values()
        f, get = self.facture, self._value
        f.numero = get(values, "numero", parse_numero, ERROR)
        f.date_emission = get(values, "date_emission", parse_date, ERROR)
        f.date_echeance = get(values, "date_echeance", parse_date, ERROR)
        f.statut = get(values, "statut", parse_statut, ERROR)
        f.categorie = get(values, "categorie", parse_text, WARNING)
        f.mode_paiement = get(values, "mode_paiement", parse_text, WARNING)
        f.iban = get(values, "iban", parse_iban, WARNING)
        self._parties(values)
        self._totals()
        self._items()
        return ParseResult(f, self.issues)

    # Labels

    def _labelled_values(self) -> dict[str, list[tuple[int, str]]]:
        """Label -> [(line number, text up to the next label or end of line)]."""
        values: dict[str, list[tuple[int, str]]] = {}
        for number, line in enumerate(self.lines):
            folded = fold(line)
            if _FACTURE_A_ALONE.fullmatch(folded):
                values.setdefault("facture_a", []).append((number, ""))
                continue
            matches = list(_LABEL_RE.finditer(folded))
            for i, match in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
                text = line[match.end():end].strip(" |\t")
                if not text and i + 1 == len(matches) and match.lastgroup != "facture_a":
                    text = self._following(number)
                values.setdefault(match.lastgroup or "", []).append((number, text))
        return values

    def _following(self, number: int) -> str:
        """The next line, when a label stands alone and its value is below."""
        if number + 1 >= len(self.lines):
            return ""
        line = self.lines[number + 1]
        folded = fold(line)
        return "" if _LABEL_RE.search(folded) or _TOTAL_RE.match(folded) else line

    def _value(
        self,
        values: dict[str, list[tuple[int, str]]],
        label: str,
        parse: Callable[[str], Any],
        severity: str,
        field: str | None = None,
    ) -> Any:
        return self._single([t for _, t in values.get(label, [])], parse, severity, field or label)

    def _single(
        self, texts: list[str], parse: Callable[[str], Any], severity: str, field: str
    ) -> Any:
        """One agreed value, or None and an issue."""
        if not texts:
            self.issue(severity, field, "introuvable")
            return None
        parsed = []
        for text in texts:
            try:
                parsed.append(parse(text))
            except ValueError as exc:
                self.issue(severity, field, f"{exc} : {text[:80]!r}")
                return None
        if any(p != parsed[0] for p in parsed):
            self.issue(severity, field, f"valeurs contradictoires : {texts}")
            return None
        return parsed[0]

    # Supplier and client

    def _parties(self, values: dict[str, list[tuple[int, str]]]) -> None:
        f, get = self.facture, self._value
        f.fournisseur.siret = get(values, "siret", parse_siret, ERROR, "fournisseur.siret")
        f.fournisseur.tva_intracom = get(
            values, "tva_intracom", parse_tva_number, WARNING, "fournisseur.tva_intracom")
        f.client.siret = get(values, "siret_client", parse_siret, ERROR, "client.siret")

        # Supplier: the unlabelled lines just above its SIRET.
        block: list[str] = []
        if values.get("siret"):
            number = values["siret"][0][0] - 1
            while number >= 0 and not self._is_labelled(number):
                if not self._is_title(number):
                    block.insert(0, self.lines[number])
                number -= 1
        self._party(f.fournisseur, block, "fournisseur")

        # Client: its name, then the unlabelled lines that follow.
        block = []
        start = values.get("client") or values.get("facture_a")
        if start:
            number, name = start[0]
            block = [name] if name else []
            number += 1
            if name and number < len(self.lines) and self.lines[number] == name:
                number += 1  # the name was read from the line below its label
            while number < len(self.lines) and not self._is_labelled(number):
                if not self._is_title(number):
                    block.append(self.lines[number])
                number += 1
        self._party(f.client, block, "client")

    def _is_labelled(self, number: int) -> bool:
        folded = fold(self.lines[number])
        return bool(
            _LABEL_RE.search(folded) or _TOTAL_RE.match(folded)
            or _FACTURE_A_ALONE.fullmatch(folded)
        )

    def _is_title(self, number: int) -> bool:
        return fold(self.lines[number]) == "facture"

    def _party(self, party: Partie, block: list[str], field: str) -> None:
        if not block:
            self.issue(ERROR, f"{field}.nom", "introuvable")
            return
        town = [i for i, line in enumerate(block) if re.fullmatch(r"[0-9]{5} \D.*", line)]
        streets = [bool(_STREET.match(fold(line))) for line in block[:-1]]
        # Exactly a name, at most one street line, then the town. Anything else
        # (a stamp above the name, a missing name...) could pass for the name.
        if town != [len(block) - 1] or streets not in ([False], [False, True]):
            self.issue(ERROR, f"{field}.nom", f"bloc d'adresse inattendu : {block}")
            return
        party.nom = block[0]
        party.adresse = block[1] if len(block) == 3 else None
        party.code_postal, party.ville = block[-1].split(" ", 1)
        if party.adresse is None:
            self.issue(WARNING, f"{field}.adresse", "introuvable")

    # Amounts

    def _totals(self) -> None:
        texts: dict[str, list[str]] = {"total_ht": [], "total_tva": [], "total_ttc": []}
        rates: list[tuple[str, str]] = []
        for number, line in enumerate(self.lines):
            match = _TOTAL_RE.fullmatch(fold(line))
            if not match:
                continue
            value = match["value"] or self._following(number)
            if match["tva"]:
                rates.append((match["taux"], value))
                continue
            for name in texts:
                if match[name]:
                    texts[name].append(value)
        f = self.facture
        f.total_ht = self._single(texts["total_ht"], parse_amount, ERROR, "total_ht")
        f.total_tva = self._single(texts["total_tva"], parse_amount, ERROR, "total_tva")
        f.total_ttc = self._single(texts["total_ttc"], parse_amount, ERROR, "total_ttc")
        if not rates:
            self.issue(WARNING, "detail_tva", "introuvable")
        for rate, value in rates:
            try:
                entry = TotalTva(parse_rate(rate), parse_amount(value))
            except ValueError as exc:
                self.issue(WARNING, "detail_tva", f"{exc} : {rate} {value[:80]!r}")
                continue
            if entry in f.detail_tva:
                continue  # repeated on another page
            if any(e.taux == entry.taux for e in f.detail_tva):
                self.issue(WARNING, "detail_tva", f"montants contradictoires pour {entry.taux} %")
            f.detail_tva.append(entry)

    # Items

    def _items(self) -> None:
        for number, (columns, row) in enumerate(self.item_rows, 1):
            def cell(name: str) -> str:
                index = columns[name]
                return row[index].replace("\n", " ") if index < len(row) else ""

            def read(name: str, parse: Callable[[str], Any]) -> Any:
                try:
                    return parse(cell(name))
                except ValueError as exc:
                    self.issue(ERROR, f"lignes[{number}].{name}", f"{exc} : {cell(name)[:80]!r}")
                    return None

            if len(row) > 1 + max(columns.values()) and any(row[1 + max(columns.values()):]):
                self.issue(ERROR, f"lignes[{number}]", f"cellules en trop : {row}")
            self.facture.lignes.append(LigneFacture(
                number,
                read("designation", parse_text),
                read("quantite", parse_quantity),
                read("prix_unitaire_ht", parse_amount),
                read("taux_tva", parse_rate),
                read("total_ht", parse_amount),
            ))
        if not self.facture.lignes:
            self.issue(ERROR, "lignes", "aucune ligne trouvée")


def parse_invoice(markdown: str) -> ParseResult:
    return _Parser(markdown).run()
