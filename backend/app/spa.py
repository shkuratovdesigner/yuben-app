"""Serve the built frontend from the backend, so real use is one port.

``make dev`` runs two processes on two ports because the runtimes differ: Vite
compiles React and hot-reloads, uvicorn runs the pipeline. That split is a
*development* need — the browser still only ever talks to :5173, which proxies
``/api/*`` across (see frontend/vite.config.ts).

For real use there is no reason to run Node at all: the build is static files.
``mount_spa`` attaches ``frontend/dist`` to the same app that serves the API, so
``make start`` is one process on http://localhost:8000 with no proxy hop. The
SPA then calls ``/api/*`` same-origin, which is the case ``ALLOWED_ORIGINS`` in
security.py already allows.

Serving is opt-in via ``YUBEN_SERVE_SPA``, which only ``make start`` sets — it
is deliberately *not* inferred from ``dist/`` being present. A leftover build
directory would otherwise make ``:8000`` answer with a stale copy of the app
during ``make dev``, which is a worse failure than answering ``404``: a UI that
is quietly out of date invites debugging code you are not running. Keying off an
explicit switch also keeps the route table identical between developers, rather
than depending on who has run a build.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import StaticFiles

# backend/app/spa.py -> parents[2] == repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where `npm run build` (via `make build`) writes the SPA.
DIST_DIR = _REPO_ROOT / "frontend" / "dist"

#: Methods the SPA fallback answers. Anything else against a non-API path is a
#: method error, not a missing page.
_READ_METHODS = frozenset({"GET", "HEAD"})

#: Set by `make start`. Absent or falsey => the backend is a JSON API only.
SERVE_SPA_ENV = "YUBEN_SERVE_SPA"

#: Spellings accepted as "on", so `YUBEN_SERVE_SPA=0` reads as off rather than
#: as a non-empty (and therefore truthy) string.
_TRUTHY = frozenset({"1", "true", "yes", "on"})


def spa_requested(env: Mapping[str, str] | None = None) -> bool:
    """Whether this process was asked to serve the built SPA."""
    source = os.environ if env is None else env
    return source.get(SERVE_SPA_ENV, "").strip().lower() in _TRUTHY


def mount_spa(app: FastAPI, dist_dir: Path = DIST_DIR) -> bool:
    """Serve ``dist_dir`` alongside the API. Returns whether it was mounted.

    Does not consult ``YUBEN_SERVE_SPA`` — the caller decides, via
    ``spa_requested()``, so this stays directly testable against a fixture
    directory. Returns ``False`` when there is no build to serve.

    Call this *after* every API router is registered: Starlette matches routes
    in registration order, so the catch-all below must be last or it would
    shadow ``/api/*``.
    """
    dist_root = dist_dir.resolve()
    index = dist_root / "index.html"
    if not index.is_file():
        return False

    # Hashed filenames, so StaticFiles' conditional-GET handling is worth having
    # here rather than routing them through the fallback below.
    assets = dist_root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    def _index() -> FileResponse:
        # The shell references hashed asset filenames, so a cached copy outlives
        # the assets it points at: after a rebuild the browser would request
        # bundles that no longer exist. Revalidate it every time — the assets
        # themselves stay cacheable because their names change.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    @app.api_route(
        "/{spa_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def spa_fallback(spa_path: str, request: Request) -> Response:
        # An unmatched /api path is a bug in a caller, not a client-side route.
        # Answering it with the HTML shell would turn "endpoint typo" into
        # "JSON parse error" at the call site — and it must 404 identically
        # whether or not a build happens to be present.
        if spa_path == "api" or spa_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)

        if request.method not in _READ_METHODS:
            return JSONResponse({"detail": "Method Not Allowed"}, status_code=405)

        # A real build artifact (favicon, logo, manifest…). `resolve()` and the
        # containment check keep `..` in the URL from reaching outside dist.
        candidate = (dist_root / spa_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist_root):
            return FileResponse(candidate)

        # Anything else is a client-side route (/history, /run/:id, …) which
        # only exists once React boots, so hand back the shell and let the
        # router resolve it.
        return _index()

    return True
