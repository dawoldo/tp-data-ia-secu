# Manual

```
S3 ── bronze pull ──> data/landing ── bronze convert ──> data/bronze/documents ── warehouse refresh ──> tables ──> SQL
                                       text PDF: PyMuPDF
                                       scan: LightOnOCR-3
```

Built: steps 1 to 6 of `CONSIGNES.md`. Not built: MCP server, agent.

Every command can be rerun: finished work is skipped, failures are retried.

## Setup

Python 3.11+, from the project root:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

`.env` (never commit it; it overrides environment variables):

| Variable | Default |
|---|---|
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | required to pull |
| `OCR_KEY`, `OCR_ENDPOINT` (full URL, ends in `/chat/completions`) | required for OCR |
| `AWS_ENDPOINT_URL`, `AWS_DEFAULT_REGION`, `S3_BUCKET` | project gateway, `us-east-1`, `factures` |
| `OCR_MODEL`, `OCR_ENGINE` | `lightonocr-3-1b-test`, `lightonocr` |

`DATA_DIR` (environment variable only) moves the data out of `data/`.

## Run everything

```bash
alias py=.venv/bin/python
py -m bronze pull          # download
py -m bronze convert       # extract
py -m warehouse refresh    # build all tables
py -m warehouse build      # database for DBeaver
```

## Commands

Prefix with `py -m`. `[x]` is the default.

### bronze: raw extractions, never modified

| Command | Does | Arguments |
|---|---|---|
| `bronze pull` | Download new or changed PDFs | `--dest` [`data/landing`], `--limit N`, `--prefix TEXT`, `--dry-run`, `--env-file` [`.env`] |
| `bronze classify [source]` | Print `text` or `image` per PDF, judged on content | `--json` |
| `bronze ocr-page FILE` | OCR one page, print text and time | `--page` [1], `--max-side` [1540 px], `--image-format png\|jpeg` [png], `--env-file` |
| `bronze convert [source]` | Extract new PDFs into the store | `--out` [`data/bronze/documents`], `--dry-run`, `--limit N`, `--no-ocr`, `--max-side`, `--image-format`, `--timeout` [120 s], `--max-pages` [100], `--env-file` |
| `bronze verify [store]` | Report modified or deleted records | |
| `bronze tables [store]` | Write the store as Parquet | `--out` [`data/bronze/tables`] |

**New OCR settings resend every scan.** Check with `--dry-run`; experiment in another `--out`.

### silver: typed and checked

| Command | Does | Arguments |
|---|---|---|
| `silver parse [source]` | Print extracted data, save nothing | `--json` |
| `silver build [source]` | Check every invoice, write the tables | `--out` [`data/silver`], `--dry-run` |

| State | Meaning | Table |
|---|---|---|
| `valide` | Nothing to report | `factures` |
| `signalee` | Readable but doubtful | `factures` + `anomalies` |
| rejected | Unreadable, duplicate or damaged | `rejets` + `anomalies` |

**Filter totals on `statut_qualite = 'valide'`.** Values are never corrected. Anomaly codes: [silver/quality/checks.py](silver/quality/checks.py).

### warehouse: SQL with DuckDB

| Command | Does |
|---|---|
| `warehouse refresh` | `bronze tables` + `silver build` |
| `warehouse build` | Create `data/warehouse/entrepot.duckdb` for DBeaver (views only) |
| `warehouse query "SQL"` | Run one query |

Views: `silver.factures`, `silver.lignes_facture`, `silver.tva_facture`, `silver.anomalies`, `silver.rejets`, `bronze.extractions`, `bronze.pages`.

```bash
py -m warehouse query "SELECT statut, sum(total_ttc) FROM silver.factures WHERE statut_qualite = 'valide' GROUP BY ALL"
```

In Python: `from warehouse.db import connect`. On another machine, rerun `warehouse build`; do not copy the file.

### evaluation: OCR accuracy

| Command | Does | Arguments |
|---|---|---|
| `evaluation run` | Compare with the ground truth, field by field | `--sides` [650 800 1540 2339], `--synthetic` [20], `--no-ocr`, `--out` [`evaluation/resultats.md`], `--env-file` |

First run: about 140 OCR calls, 40 minutes. Analysis: [evaluation/ANALYSE.md](evaluation/ANALYSE.md).

## Exit codes

0: done. 1: some files failed, pending, damaged or rejected. 2: configuration or input error. Results on stdout, logs on stderr.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
py -m pytest
```

3 minutes, no network or credentials.

## Troubleshooting

| Message | Do |
|---|---|
| `missing AWS_…`, `missing OCR_…` | Fill in `.env` |
| `503 model_not_ready`, `pending_ocr` | Start the model in Hyperfluid, rerun `convert` |
| OCR `401`, `403`, `404` | Check `OCR_KEY`, `OCR_ENDPOINT`, `OCR_MODEL` |
| `damaged`, `bronze_inutilisable` | Run `bronze verify`, restore from a backup |
| `differs from what was downloaded` | Rerun `bronze pull` |
| `repaired` | Damaged PDF: check it by hand |
| `another run is using …` | Wait |
| `… is missing: run python -m warehouse refresh` | Do that |
