"""Local-daemon hardening: DNS-rebinding and cross-site request defence.

YuBen's backend is a localhost daemon holding four provider keys, so the
threat model is not a remote attacker — it is *a website the user happens to
visit* reaching http://localhost:8000 (or whatever ``YUBEN_PORT`` names) from
their browser.

CORS does not stop this. CORS governs whether a cross-origin page may **read**
a response; it does nothing about the side effect having already happened. Two
concrete gaps this module closes:

1. **DNS rebinding.** An attacker domain re-resolved to 127.0.0.1 is, to the
   browser, same-origin with the attacker's page — so CORS never engages.
   ``TrustedHostMiddleware`` rejects it, because the request still carries the
   attacker's hostname in ``Host``.

2. **Bodyless / simple POSTs.** ``POST`` with no body (or a form content type)
   is a CORS "simple" request: no preflight, so the allowlist hides the
   *response* while the endpoint has already run. ``/api/config/remedy`` opens
   a Terminal, so "the side effect already happened" is not academic.

The guard below keys off ``Sec-Fetch-Site``, which browsers set and page
JavaScript cannot forge (it is a forbidden header). Absent means a non-browser
client — curl, the test suite, a native app — which is not the threat here and
is allowed through.
"""
from __future__ import annotations

import os
from typing import Iterable, Mapping, Optional, Sequence

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

#: Hostnames this daemon will answer to. Anything else is a rebinding attempt.
ALLOWED_HOSTS: Sequence[str] = ("localhost", "127.0.0.1", "[::1]", "testserver")

#: The backend's port. ``python yuben.py start`` and ``dev`` set it for the
#: server and the Vite proxy alike, so all three agree (reliability W7).
PORT_ENV = "YUBEN_PORT"
DEFAULT_PORT = 8000
#: The Vite dev server. Fixed: vite.config.ts uses strictPort.
DEV_FRONTEND_PORT = 5173


def backend_port(env: Optional[Mapping[str, str]] = None) -> int:
    """The port from ``YUBEN_PORT``, or 8000.

    A malformed value fails loudly at startup. Falling back to 8000 instead
    would serve on one port and allow another, so every save or run would 403.
    """
    raw = (os.environ if env is None else env).get(PORT_ENV, "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        port = 0
    if not 1 <= port <= 65535:
        raise ValueError(f"{PORT_ENV} must be a port number from 1 to 65535, got {raw!r}.")
    return port


def allowed_origins(port: Optional[int] = None) -> tuple[str, ...]:
    """Origins the real client can present: the Vite dev server, or the backend
    itself when the built SPA is served same-origin on ``port``."""
    port = backend_port() if port is None else port
    return (
        f"http://localhost:{DEV_FRONTEND_PORT}",
        f"http://127.0.0.1:{DEV_FRONTEND_PORT}",
        f"http://localhost:{port}",
        f"http://127.0.0.1:{port}",
    )


#: The allowlist for the default port, kept for callers that want a constant.
ALLOWED_ORIGINS: Sequence[str] = allowed_origins(DEFAULT_PORT)

#: Methods that can change state or spend the user's quota.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: `Sec-Fetch-Site` values that are not a third-party page calling us.
#: - same-origin: the built SPA, or via the Vite proxy
#: - same-site:   localhost:5173 -> localhost:8000 (site ignores port)
#: - none:        user-initiated (address bar, bookmark)
_SAFE_FETCH_SITES = frozenset({"same-origin", "same-site", "none"})


def _forbidden(reason: str) -> JSONResponse:
    return JSONResponse({"detail": reason}, status_code=403)


class SameOriginGuardMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests that originate from a third-party page."""

    def __init__(self, app, origins: Optional[Iterable[str]] = None) -> None:
        super().__init__(app)
        # Read at construction, i.e. app startup, so YUBEN_PORT set by the
        # launcher is what the guard enforces.
        self._allowed = frozenset(allowed_origins() if origins is None else origins)

    async def dispatch(self, request: Request, call_next):
        if request.method not in _UNSAFE_METHODS:
            return await call_next(request)

        # Browsers set this and page JS cannot override it. Missing => not a
        # browser (curl / tests), which this guard is not aimed at.
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site and fetch_site.lower() not in _SAFE_FETCH_SITES:
            return _forbidden(
                "Cross-site requests are not allowed against the local YuBen "
                "backend."
            )

        # Belt and braces for browsers that omit Sec-Fetch-Site: a form POST
        # from evil.example still carries its Origin.
        origin = request.headers.get("origin")
        if origin and origin not in self._allowed:
            return _forbidden(
                "Requests from this origin are not allowed against the local "
                "YuBen backend."
            )

        return await call_next(request)
