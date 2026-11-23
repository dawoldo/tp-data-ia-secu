"""Bronze layer: raw extractions of the invoices, never modified.

    ingestion/    S3 bucket -> landing zone, and where each file comes from
    extraction/   one PDF -> raw Markdown (text layer or OCR)
    storage/      append-only store, and its Parquet tables
    pipeline.py   landing zone -> extraction -> store
"""

import pymupdf

# MuPDF prints its messages on stdout by default, which carries our results.
pymupdf.set_messages(pylogging=True)
