"""Tests run on tests/data only: no network, no credentials, no real data needed."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT, ROOT / "tests"):
    sys.path.insert(0, str(path))
# Worker processes and command-line tests need the same modules.
os.environ["PYTHONPATH"] = os.pathsep.join((str(ROOT), str(ROOT / "tests")))
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
