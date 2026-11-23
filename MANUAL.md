# Pipeline user manual

The pipeline downloads invoice PDFs from S3, converts them to Markdown, and turns them into checked, typed tables.

```
S3 bucket ── pull-factures.py ──> factures/landing/ ── extraction convert ──> factures/bronze/
                                                        ├─ text PDF: PyMuPDF
                                                        └─ scan: LightOnOCR-3
factures/bronze/ ── silver build ──> factures/silver/  (tables, anomalies, quarantine)
factures/bronze/ ── warehouse.export_parquet ──> factures/silver/ + factures/warehouse/  (all tables)
those tables ── warehouse.db ──> SQL with DuckDB
```

Every step can be run again safely: finished work is skipped, failures are retried.

> **Current state: bronze, silver and warehouse.** The pipeline covers steps 1 to 4 of `CONSIGNES.md`: download, text/scan detection, OCR, raw Markdown with its traceability record (`factures/bronze/`), then typed tables with quality checks and quarantine (`factures/silver/`). Step 5 (OCR evaluation) is in `evaluation/`. Step 6 (warehouse) is DuckDB over those tables. The MCP server and agent are not built yet.

## Setup

Requires Python 3.11 or later. Run all commands from the project root.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create two settings files. Both are ignored by Git; never commit them. Values in these files take priority over environment variables.

| File | Variable | Required | Default |
|---|---|---|---|
| `factures/.env` | `AWS_ACCESS_KEY_ID` | yes | |
| | `AWS_SECRET_ACCESS_KEY` | yes | |
| | `AWS_ENDPOINT_URL` | no | the project's S3 gateway |
| | `AWS_DEFAULT_REGION` | no | `us-east-1` |
| | `S3_BUCKET` | no | `factures` |
| `.env` | `OCR_KEY` | yes | |
| | `OCR_ENDPOINT` | yes | full URL, ending in `/chat/completions` |
| | `OCR_MODEL` | no | `lightonocr-3-1b-test` |
| | `OCR_ENGINE` | no | `lightonocr` |

## Quick start

```bash
.venv/bin/python factures/pull-factures.py --limit 5   # download 5 new invoices
.venv/bin/python -m extraction classify                # text or scan?
.venv/bin/python -m extraction convert                 # fill the bronze layer
.venv/bin/python -m extraction verify                  # check the bronze layer
.venv/bin/python -m silver build                       # check and build the silver tables
.venv/bin/python -m warehouse.export_parquet           # silver + bronze tables
.venv/bin/python -m warehouse.db build                  # database for DBeaver
.venv/bin/python -m evaluation run                      # measure the OCR
```

Without `--limit`, the first command downloads everything new.

## Commands

Add `--help` to any command to list its arguments.

### `factures/pull-factures.py`: download invoices

Downloads new or changed PDFs and records each one in `manifest.json` (S3 key, ETag, SHA-256). Lost or damaged files are downloaded again. If an invoice changes under the same name, both versions are kept.

| Argument | Effect | Default |
|---|---|---|
| `--dest DIR` | Where to save the PDFs | `factures/landing` |
| `--limit N` | Download at most N files | all |
| `--prefix TEXT` | Only S3 keys starting with TEXT | all |
| `--dry-run` | List what would be downloaded, save nothing | off |
| `--env-file FILE` | S3 settings file | `factures/.env` |

### `python -m extraction classify`: text or scan

Prints `text`, `image` or `error` for each PDF, with the reason. It looks at the content, not the file name. A PDF with at least one page that needs OCR is `image`. Writes nothing and makes no OCR call.

| Argument | Effect | Default |
|---|---|---|
| `source` | PDF or folder | `factures/landing` |
| `--json` | One JSON line per file, with the measurements | off |

### `python -m extraction ocr-page`: OCR one page

Sends one page to the OCR model and prints the text, then the time and token usage. Saves nothing. Useful to check the model or compare settings.

| Argument | Effect | Default |
|---|---|---|
| `file` | PDF to read (required) | |
| `--page N` | Page number, starting at 1 | `1` |
| `--max-side N` | Longest side of the image, in pixels | `1540` |
| `--image-format png\|jpeg` | Image format sent to the model | `png` |
| `--env-file FILE` | OCR settings file | `.env` |

### `python -m extraction convert`: fill the bronze layer

Reads text pages directly, sends the others to the OCR model, and adds the result to the bronze store. Nothing is ever replaced:

- A PDF is recognized by its content. A known PDF is skipped, and one known under another name is only listed as a duplicate.
- New settings add a version next to the old one, **so changing a setting sends every scan to the OCR again**. Check with `--dry-run`.
- A PDF that differs from what `pull-factures.py` downloaded is refused.
- Parsing runs in a separate process: a PDF that crashes it, hangs or needs too much memory fails alone.
- After 3 OCR outages in a row, scans wait for the next run and text PDFs continue.
- Only one run at a time can write to a store.

| Argument | Effect | Default |
|---|---|---|
| `source` | PDF or folder | `factures/landing` |
| `--out DIR` | Bronze store | `factures/bronze` |
| `--dry-run` | Show what would be done and the number of OCR calls; write nothing | off |
| `--limit N` | Stop after N new conversions | all |
| `--no-ocr` | Convert text PDFs only; scans stay pending | off |
| `--max-side N` | As for `ocr-page` | `1540` |
| `--image-format png\|jpeg` | As for `ocr-page` | `png` |
| `--timeout N` | Seconds allowed to parse one PDF | `120` |
| `--max-pages N` | Refuse longer PDFs | `100` |
| `--env-file FILE` | OCR settings file | `.env` |

To compare OCR settings, use a separate store, because silver reads the newest version of each PDF:

```bash
.venv/bin/python -m extraction convert --max-side 2339 --out factures/bronze-2339
```

### `python -m extraction verify`: check the bronze layer

Recomputes every hash and reports records that were modified, damaged or deleted. Changes nothing.

| Argument | Effect | Default |
|---|---|---|
| `store` | Bronze store | `factures/bronze` |

### `python -m silver parse`: look at the extracted data

For inspection; `build` does not need it. Reads the bronze Markdown of text PDFs and scans, and prints the data of each invoice. If a PDF has several versions, the newest is used. Values are found by label, never by position. A value that does not match its format stays empty and is reported; nothing is guessed or corrected. Saves nothing.

| Argument | Effect | Default |
|---|---|---|
| `source` | `.md` file or folder | `factures/bronze` |
| `--json` | One JSON line per invoice, with every field | off |

| Group | Fields |
|---|---|
| Invoice | `numero`, `date_emission`, `date_echeance`, `categorie`, `statut`, `mode_paiement`, `iban` |
| `fournisseur`, `client` | `nom`, `adresse`, `code_postal`, `ville`, `siret`, and `tva_intracom` (supplier only) |
| Amounts | `total_ht`, `total_tva`, `total_ttc`, `detail_tva` (amount per rate) |
| `lignes` | `numero_ligne`, `designation`, `quantite`, `prix_unitaire_ht`, `taux_tva`, `total_ht` |

| State | Meaning |
|---|---|
| `ok` | Every field was read |
| `check` | A secondary field is missing or odd (`warning`) |
| `ERROR` | An essential field is missing or unreadable (`error`) |

`ok` does not mean the amounts add up: that is checked by `build`.

### `python -m silver build`: check and build the silver tables

Parses every bronze document, checks it, and writes the tables. Each build starts again from bronze; the same bronze gives identical files. If a build fails before the end, the previous tables stay. Problems are listed on stderr.

| Argument | Effect | Default |
|---|---|---|
| `source` | Bronze store | `factures/bronze` |
| `--out DIR` | Where to write the tables | `factures/silver` |
| `--dry-run` | Check only, write nothing | off |

Each document ends in exactly one of three states. Values are never corrected.

| State | Meaning | Where |
|---|---|---|
| `valide` | Nothing to report | `factures` |
| `signalee` | Readable but doubtful; kept, with its reasons | `factures` + `anomalies` |
| rejected | Cannot be used: essential field unreadable, duplicate, damaged bronze record | `rejets` + `anomalies` |

**For reliable totals, filter on `statut_qualite = 'valide'`**, or say that flagged invoices are included.

| Checked | Codes |
|---|---|
| Reading | `lecture_incomplete` (rejected), `lecture_partielle`, `valeur_hors_limites` (rejected), `bronze_inutilisable` (rejected), `pdf_repare`, `texte_perdu` |
| Duplicates | `doublon` (rejected), `doublon_contradictoire` (one kept and flagged, the others rejected), `doublon_probable` |
| Amounts | `ligne_incoherente`, `somme_lignes`, `total_ttc_incoherent`, `montant_non_positif` |
| VAT | `tva_incoherente`, `total_tva_incoherent`, `detail_tva_incoherent`, `taux_tva_inconnu` |
| Dates | `echeance_avant_emission`, `delai_inhabituel` (not 0, 15, 30, 45 or 60 days), `annee_incoherente`, `emission_future`, `statut_incoherent` |
| Identity | `iban_invalide`, `tva_intracom_incoherente`, `fournisseur_egal_client`, `identite_variable` (differs from the company's other invoices), `nom_fichier`, `mode_paiement_inconnu` |

Not checked: the SIRET checksum and the VAT number key (the invoices are fictional and nearly all would fail), and the wording of product names and categories. `identite_variable` cannot help for a company seen only once.

### `python -m evaluation run`: measure the OCR

Compares the pipeline with a ground truth, field by field, at several image sizes: 20 real scans transcribed from the images, and synthetic scans made from the native PDFs, whose text layer is the truth. Prints the tables and saves them in `evaluation/resultats.md`. The analysis is in `evaluation/ANALYSE.md`.

The first run makes about 140 OCR calls (about 40 minutes); the next ones make none. Nothing is saved while scans still wait for the OCR.

| Argument | Effect | Default |
|---|---|---|
| `--sides N ...` | Image sizes to compare, in pixels | `650 800 1540 2339` |
| `--synthetic N` | Number of synthetic scans | `20` |
| `--no-ocr` | Use only the results already there | off |
| `--out FILE` | Where to save the tables | `evaluation/resultats.md` |
| `--env-file FILE` | OCR settings file | `.env` |

Work files are in `factures/evaluation/`, apart from the real bronze and silver data.

### `python -m warehouse.export_parquet`: every table as Parquet

Prepares the warehouse. Does what `silver build` does, and adds the bronze tables with every extraction ever made (all versions). Tables are rebuilt each time; the bronze ones are read back and compared before they replace the previous ones. OCR evaluation runs are not included.

| Argument | Effect | Default |
|---|---|---|
| `source` | Bronze store | `factures/bronze` |
| `--silver DIR` | Where the silver tables are refreshed | `factures/silver` |
| `--out DIR` | Where to write the bronze tables | `factures/warehouse` |

### `python -m warehouse.db`: query with SQL

DuckDB is an SQL database that runs inside a program, without a server, and reads Parquet files in place. The database holds **views only**: the data stays in the Parquet files, once. New data shows up without rebuilding.

| Command | Effect |
|---|---|
| `build` | Create `factures/warehouse/entrepot.duckdb`, for graphical tools |
| `query "SQL"` | Run one query and print the result |

| View | Content |
|---|---|
| `silver.factures`, `silver.lignes_facture`, `silver.tva_facture`, `silver.anomalies`, `silver.rejets` | Silver tables |
| `bronze.extractions`, `bronze.pages` | Bronze tables |

```bash
.venv/bin/python -m warehouse.db query "SELECT statut, count(*), sum(total_ttc) FROM silver.factures WHERE statut_qualite = 'valide' GROUP BY ALL"
```

- **From a program:** `from warehouse.db import connect`, then `connect().execute("SELECT ...")`. It does not open the database file, so a graphical tool cannot block it.
- **From DBeaver:** create a DuckDB connection to `factures/warehouse/entrepot.duckdb`.
- **On another machine or in a container:** run `build` there; do not copy the file, its views hold absolute paths. Set `FACTURES_DIR` if the data is not in `factures/`.

## Output

| In `factures/warehouse/` (Parquet) | One row per |
|---|---|
| `bronze_extractions` | extraction: origin, settings, hashes |
| `bronze_pages` | page: raw text, method, OCR time and tokens |
| `entrepot.duckdb` | not a table: views for graphical tools, see `warehouse.db` |

| In `factures/silver/` (Parquet) | One row per |
|---|---|
| `factures` | usable invoice, with its quality state and origin |
| `lignes_facture` | invoice line |
| `tva_facture` | VAT rate of an invoice |
| `anomalies` | problem found |
| `rejets` | rejected document, with its reason |

`facture_id` and `document_id` are the SHA-256 of the PDF, which is also its bronze folder. Amounts are exact decimals.

| In `factures/bronze/` | Content |
|---|---|
| `PDF_HASH/VERSION/NAME.pdf.md` | Markdown, with `<!-- page: N -->` before each page |
| `PDF_HASH/VERSION/NAME.pdf.json` | Traceability: S3 key and ETag, hashes, class and reason, settings, OCR time and raw OCR response |
| `index.jsonl` | Hash of every record, used by `verify` |
| `sources.jsonl` | Every file and S3 key where each PDF was seen |
| `errors.jsonl` | Every failure, with date and file |

`PDF_HASH` is the SHA-256 of the PDF, `VERSION` a hash of the settings. To find an invoice: `find factures/bronze -name '*A-2025-0003*'`. The files are read-only; never edit or delete them.

Markdown is kept as extracted, so tables are Markdown for text PDFs and can be HTML for scans.

`pull-factures.py` and `convert` print a JSON summary on stdout. Logs go to stderr.

| Exit code | Meaning |
|---|---|
| 0 | Success |
| 1 | Some files failed, wait for OCR, are damaged, or some invoices are rejected or incomplete |
| 2 | Configuration, input or S3 error |

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

About 2 minutes. The tests need no network, credentials or downloaded invoices: they use `tests/data` (27 fictional invoices) and fake S3 and OCR servers.

## Troubleshooting

| Message or field | What to do |
|---|---|
| `missing AWS_…` or `missing OCR_…` | Fill in the matching `.env` file |
| `HTTP 503 … model_not_ready` | The model is stopped. Start it in Hyperfluid, then run `convert` again |
| `HTTP 401`, `403` or `404` (OCR) | Check `OCR_KEY`, `OCR_ENDPOINT` and `OCR_MODEL` |
| `pending_ocr` | Scans waiting for OCR; run `convert` again |
| `duplicates` | Same content as a known PDF; nothing to do |
| `damaged` | The bronze record was modified. It is left as is; run `verify`, then restore it from a backup |
| `repaired` | The PDF was damaged and content may be missing; check it by hand |
| `failed` | The reason is in the summary and, for `convert`, in `errors.jsonl` |
| `unusable bronze record` | The `.md` or `.json` was modified or is missing. Run `verify` |
| `bloc d'adresse inattendu` | The name and address are not name, street, town. Check the PDF |
| `introuvable`, `… illisible` | The label is missing, or the value has an unexpected format. Check the `.md` against the PDF |
| `another run is using …` | Wait for the other `convert` to finish |
| `differs from what was downloaded` | The PDF was changed locally. Run `pull-factures.py` again |
| `bronze_inutilisable` | The bronze record was changed or deleted. Run `extraction verify` |
| `… is missing: run python -m warehouse.export_parquet` | The Parquet tables have not been created yet |
