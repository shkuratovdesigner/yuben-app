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

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.middleware.trustedhost import TrustedHostMiddleware  # noqa: E402

from app.store.seed import seed_example_research  # noqa: E402

from app.security import (  # noqa: E402
    ALLOWED_HOSTS,
    SameOriginGuardMiddleware,
)
from app.api.adapters import router as adapters_router  # noqa: E402
from app.api.config import router as config_router  # noqa: E402
from app.api.health import router as health_router  # noqa: E402
from app.api.history import router as history_router  # noqa: E402
from app.api.research import router as research_router  # noqa: E402
from app.api.research_result import router as research_result_router  # noqa: E402

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # A fresh install opens on an empty History, which gives the user nothing to
    # read the UI against. Seed the bundled example run (once — see seed.py) so
    # there is a finished run to open before any quota is spent.
    seed_example_research()
    yield


app = FastAPI(title="YuBen Backend", version="0.1.0", lifespan=lifespan)

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

# CORS alone does not protect a localhost daemon: it governs whether a page may
# *read* our response, not whether the side effect ran. These two close the gap
# — see app/security.py for the full reasoning.
#
# Middleware runs outermost-registered-last in Starlette, so registering these
# after CORS puts them *in front* of it: a rebound or cross-site request is
# rejected before any route (or the CORS layer) sees it.
app.add_middleware(SameOriginGuardMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(ALLOWED_HOSTS))

# Full route surface (CONTRACTS.md §1). Order is not significant — the paths are
# disjoint (research lifecycle vs research result differ by segment depth).
app.include_router(health_router)
app.include_router(config_router)
app.include_router(adapters_router)
app.include_router(research_router)
app.include_router(research_result_router)
app.include_router(history_router)
