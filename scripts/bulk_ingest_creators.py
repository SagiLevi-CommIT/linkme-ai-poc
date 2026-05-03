"""CLI wrapper for offline creator bulk ingestion."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from knowledge_setup.bulk_ingest_creators import main


if __name__ == "__main__":
    raise SystemExit(main())
