"""Silver layer: clean, typed and checked invoices, derived from bronze.

    reader.py     bronze store -> Markdown and its record
    parsing/      Markdown -> invoice
    quality/      checks, quarantine
    tables.py     Parquet tables
"""
