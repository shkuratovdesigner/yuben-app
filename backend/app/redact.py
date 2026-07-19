"""Credential scrubbing for anything that can reach a user's screen or logs.

Why this exists: ``googleapiclient`` puts the API key in the request URI, and
``HttpError.__str__`` interpolates that URI verbatim. So *any* code that
f-strings the exception — ``f"failed: {e}"`` — prints a live YouTube key. The
same shape shows up in most HTTP clients (keys in query strings, bearer tokens
in echoed headers).

Fixing the known call sites is necessary but not sufficient: the next
``except Exception as e: ... {e}`` reintroduces the leak. So we also run every
user-facing error message through :func:`redact` at the single funnel that
builds error events (``orchestrator.events.make_error_event``). Defense in
depth — the call sites stay correct on their own, and the funnel catches
whatever slips through later.

This backs the guarantee ``app/store/secrets.py`` states: a key is NEVER
returned by any endpoint, logged, or placed in a URL / query string.
"""
from __future__ import annotations

import re
from typing import Optional

_PLACEHOLDER = "[redacted]"

# (pattern, replacement) pairs. Each replacement keeps the *name* of what was
# removed so the message still reads sensibly — "key=[redacted]" rather than a
# bare "[redacted]" — which matters because these strings are shown to users.
_PATTERNS = (
    # ?key=AIza... / &access_token=... / &api_key=... — the googleapiclient case.
    # Stops at the next query separator so the rest of the URI (host, path,
    # other params) survives and the error stays diagnosable.
    (
        re.compile(
            r"(?i)\b(key|api[_-]?key|access[_-]?token|token|apikey|password|secret)"
            r"(?:=|%3D)[^&\s\"'<>]+"
        ),
        r"\1=" + _PLACEHOLDER,
    ),
    # "Authorization: Bearer <jwt>" in an echoed header dump. Consumes to end of
    # line: the value may contain spaces (a scheme prefix), and over-redacting
    # an error string is safe where under-redacting is not.
    (
        re.compile(r"(?i)\b(authorization|x-api-key)(\s*:\s*)[^\r\n]+"),
        r"\1\2" + _PLACEHOLDER,
    ),
    # Vendor-shaped literals, for when a key is interpolated with no name= prefix.
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{8,}"), _PLACEHOLDER),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), _PLACEHOLDER),
    (re.compile(r"\bAIza[A-Za-z0-9_\-]{20,}"), _PLACEHOLDER),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), _PLACEHOLDER),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"), _PLACEHOLDER),
)


def redact(text: Optional[str]) -> str:
    """Return ``text`` with anything credential-shaped replaced.

    Safe on ``None``/empty and never raises — this runs on error paths, where a
    scrubber that itself throws would mask the original failure.
    """
    if not text:
        return ""
    out = str(text)
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out


def http_error_note(exc: BaseException) -> str:
    """A short, key-free description of a Google API client error.

    Prefer this over ``str(exc)`` at every logging site. Mirrors the pattern
    already used in ``app/pipeline/keytest.py``: status code and reason only,
    never the exception object (whose repr carries the request URI).
    """
    status = getattr(getattr(exc, "resp", None), "status", None)
    reason = None
    # HttpError exposes the parsed reason on some versions only; fall back to
    # the class name rather than the message, which may embed the URI.
    for attr in ("reason", "_get_reason"):
        value = getattr(exc, attr, None)
        if callable(value):
            try:
                value = value()
            except Exception:  # pragma: no cover - defensive on error paths
                value = None
        if isinstance(value, str) and value.strip():
            reason = value.strip()
            break
    if status and reason:
        return f"HTTP {status} ({redact(reason)})"
    if status:
        return f"HTTP {status}"
    return type(exc).__name__
