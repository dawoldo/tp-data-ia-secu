"""Where everything is. The only module shared by every layer."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"

DATA = Path(os.environ.get("DATA_DIR") or ROOT / "data")
LANDING = DATA / "landing"                      # PDFs as downloaded
BRONZE = DATA / "bronze" / "documents"          # append-only store
BRONZE_TABLES = DATA / "bronze" / "tables"      # the same, as Parquet
SILVER = DATA / "silver"                        # Parquet
WAREHOUSE = DATA / "warehouse"                  # DuckDB views
EVALUATION = DATA / "evaluation"                # OCR measurements, apart from the rest
