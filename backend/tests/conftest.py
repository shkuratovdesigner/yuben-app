"""Put the repo root on sys.path so the backend can import the shared
`contracts` package (Pydantic models) and, later, the research scripts.

pyproject's `pythonpath=["."]` adds backend/ (for `app`); this adds the repo
root (for `contracts`). B1/B3 reuse the same bootstrap at app startup.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
