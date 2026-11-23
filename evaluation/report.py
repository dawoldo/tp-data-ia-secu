"""Result tables, in Markdown."""

from __future__ import annotations

from statistics import mean

from .compare import EXACT, FIELDS, MISSING, WRONG, Score, wilson


def _percent(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %".replace(".", ",") if whole else "-"


def _bounds(part: int, whole: int) -> str:
    low, high = wilson(part, whole)
    return f"{100 * low:.0f}-{100 * high:.0f} %"


def render(scores: dict[tuple[str, int], Score]) -> str:
    keys = list(scores)
    lines = [
        "# Résultats de l'évaluation OCR", "",
        "Fichier généré par `python -m evaluation run`, ne pas modifier à la main.", "",
        "## Vue d'ensemble", "",
        "| Série | Image (px) | Factures | Factures sans erreur (IC 95 %) | Champs exacts | "
        "Manquants | Faux | dont non signalés | s/page |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for (series, side), s in scores.items():
        seconds = f"{mean(s.seconds):.1f}".replace(".", ",") if s.seconds else "-"
        lines.append(
            f"| {series} | {side} | {s.documents} | {s.perfect} ({_bounds(s.perfect, s.documents)}) | "
            f"{s.total(EXACT)}/{s.size} ({_percent(s.total(EXACT), s.size)}) | "
            f"{s.total(MISSING)} | {s.total(WRONG)} | {s.silent} | {seconds} |")
    lines += [
        "", "« Faux » : une valeur a été lue mais elle est inexacte. « Non signalés » : valeurs "
        "fausses dans une facture que les contrôles qualité déclarent valide.", "",
        "## État des factures après les contrôles qualité", "",
        "| Série | Image (px) | Valides | Signalées | Rejetées | Illisibles |",
        "|---|---|---|---|---|---|",
    ]
    for (series, side), s in scores.items():
        lines.append(f"| {series} | {side} | " + " | ".join(
            str(s.states[x]) for x in ("valide", "signalee", "rejetee", "illisible")) + " |")
    lines += [
        "", "## Précision champ par champ", "",
        "Part de valeurs exactes. Entre parenthèses : manquantes + fausses.", "",
        "| Champ | Valeurs | " + " | ".join(f"{a} {b}" for a, b in keys) + " |",
        "|---" * (len(keys) + 2) + "|",
    ]
    for name in FIELDS:
        cells = []
        for key in keys:
            c = scores[key].counts[name]
            n = sum(c.values())
            bad = f" ({c[MISSING]}+{c[WRONG]})" if c[EXACT] != n else ""
            cells.append(_percent(c[EXACT], n) + bad)
        sizes = sorted({sum(s.counts[name].values()) for s in scores.values()})
        lines.append(f"| {name} | {' / '.join(map(str, sizes))} | " + " | ".join(cells) + " |")
    lines += ["", "## Erreurs", ""]
    for (series, side), s in scores.items():
        if not s.errors:
            continue
        lines += [f"### {series}, {side} px", "",
                  "| Facture | Champ | Attendu | Lu | État |", "|---|---|---|---|---|"]
        shown = s.errors[:40]
        lines += [f"| {e.document} | {e.field} | {e.expected} | "
                  f"{'(rien)' if e.got is None else e.got} | {e.state} |" for e in shown]
        if len(s.errors) > len(shown):
            lines.append(f"| ... | {len(s.errors) - len(shown)} autres | | | |")
        lines.append("")
    if not any(s.errors for s in scores.values()):
        lines.append("Aucune.")
    return "\n".join(lines).rstrip() + "\n"
