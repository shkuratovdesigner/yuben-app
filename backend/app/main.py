"""YuBen backend — FastAPI application entrypoint.

B1 owns this file. It (1) puts the repo root on ``sys.path`` at startup so the
shared ``contracts`` package imports when the app is launched from ``backend/``
(the conftest does the same for tests — see conftest note "B1/B3 reuse the same
bootstrap at app startup"), (2) wires CORS for the Vite dev origin, and
(3) registers the FULL router surface (CONTRACTS.md §1) so the app boots with
every route present. Config is the real implementation; adapters / research /
history are Wave-1 stubs that B2–B5 fill in their own files — collision-free.
"""
from __future__ import annotations

import sys
from pathlib import Path

# --- repo-root bootstrap (before importing anything that needs `contracts`) ---
# backend/app/main.py -> parents[2] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from app.api.adapters import router as adapters_router  # noqa: E402
from app.api.config import router as config_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.history import router as history_router  # noqa: E402
from app.api.research import router as research_router  # noqa: E402
from app.api.research_result import router as research_result_router  # noqa: E402

app = FastAPI(title="YuBen Backend", version="0.1.0")

# Local-only: the React SPA runs on the Vite dev origin. No other origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Full route surface (CONTRACTS.md §1). Order is not significant — the paths are
# disjoint (research lifecycle vs research result differ by segment depth).
app.include_router(health_router)
app.include_router(config_router)
app.include_router(adapters_router)
app.include_router(research_router)
app.include_router(research_result_router)
app.include_router(history_router)
