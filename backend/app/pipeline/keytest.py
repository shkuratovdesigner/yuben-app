"""``test_youtube_key`` — one cheap YouTube Data API probe (B3).

Backs ``POST /api/config/key-test`` (CONTRACTS §1). B1's config router calls
``from app.pipeline import test_youtube_key`` defensively and coerces the
returned ``{ok, message}`` into ``KeyTestResult``.

The key is read from the local secret store (``secrets.get_youtube_key``) — it is
never passed through the API, logged, echoed, or placed in a URL (PRD §8). The
probe is a ``videos.list(part="id", id=...)`` call: **1 quota unit** (vs. 100 for
search), the cheapest way to prove the key is accepted.

Always returns a dict; never raises — every failure maps to a friendly message.
"""
from __future__ import annotations

from typing import Any, Dict

# A stable, always-public video id (the API only needs *a* valid id to accept the
# request; we don't inspect the content).
_PROBE_VIDEO_ID = "dQw4w9WgXcQ"


def _result(ok: bool, message: str) -> Dict[str, Any]:
    return {"ok": ok, "message": message}


def test_youtube_key() -> Dict[str, Any]:
    """Validate the stored YouTube key with a single 1-unit API call."""
    try:
        from app.store.secrets import get_youtube_key
    except Exception as exc:  # pragma: no cover - store always present in-app
        return _result(False, f"Secret store unavailable: {exc}")

    key = get_youtube_key()
    if not key:
        return _result(False, "No YouTube API key stored. Add your key in Setup.")

    try:
        from googleapiclient.discovery import build
        from googleapiclient.errors import HttpError
    except Exception:  # pragma: no cover - dep added in requirements.txt
        return _result(
            False,
            "google-api-python-client is not installed (run: pip install -r requirements.txt).",
        )

    try:
        service = build("youtube", "v3", developerKey=key, cache_discovery=False)
        resp = service.videos().list(part="id", id=_PROBE_VIDEO_ID).execute()
    except HttpError as exc:  # type: ignore[misc]
        status = getattr(getattr(exc, "resp", None), "status", None)
        reason = _http_reason(exc)
        if status == 403:
            if reason and "quota" in reason.lower():
                return _result(False, "YouTube API quota exceeded for today. Try again later.")
            return _result(
                False,
                "YouTube API key rejected (HTTP 403). Check the key is enabled for "
                "YouTube Data API v3 and not IP/referrer-restricted.",
            )
        if status == 400:
            return _result(False, "YouTube API key is invalid (HTTP 400).")
        return _result(False, f"YouTube API call failed (HTTP {status}).")
    except Exception as exc:
        return _result(False, f"Could not reach the YouTube API: {exc}")

    items = resp.get("items", []) if isinstance(resp, dict) else []
    if items:
        return _result(True, "YouTube API key is valid.")
    # 200 with no items usually means the key works but the id was filtered;
    # the key itself is still accepted.
    return _result(True, "YouTube API key accepted.")


def _http_reason(exc: Any) -> str:
    """Best-effort extraction of the Google API error 'reason' string."""
    try:
        import json

        content = getattr(exc, "content", b"") or b""
        if isinstance(content, bytes):
            content = content.decode("utf-8", "replace")
        data = json.loads(content)
        errors = data.get("error", {}).get("errors", [])
        if errors:
            return str(errors[0].get("reason", ""))
    except Exception:
        pass
    return ""
