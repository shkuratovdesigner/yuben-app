"""Credential scrubbing + local-daemon request guards.

These tests encode the two pre-launch findings they were written for:
  * an API key reaching the browser through an error message, and
  * a third-party page reaching this daemon's state-changing endpoints.
Both are regression-shaped: they fail loudly if the protection is removed.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.orchestrator.events import make_error_event
from app.redact import http_error_note, redact


# ---------------------------------------------------------------------------
# redact()
# ---------------------------------------------------------------------------

# A syntactically real-looking Google key. Not a live credential.
_KEY = "AIzaSyD-1234567890abcdefghijklmnopqrstu"
_URI = f"https://youtube.googleapis.com/youtube/v3/search?q=x&key={_KEY}&alt=json"


@pytest.mark.parametrize(
    "raw",
    [
        _URI,
        f"<HttpError 403 when requesting {_URI} returned 'quotaExceeded'>",
        f"?api_key={_KEY}",
        f"&access_token={_KEY}",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.abc.def",
        "sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ],
)
def test_redact_removes_credentials(raw: str) -> None:
    out = redact(raw)
    assert _KEY not in out
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out
    assert "sk-ant-api03-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in out
    assert "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" not in out


def test_redact_keeps_the_message_readable() -> None:
    """Scrubbing must not destroy the diagnostic value of the message."""
    out = redact(f"<HttpError 403 when requesting {_URI} returned 'quotaExceeded'>")
    assert "403" in out
    assert "quotaExceeded" in out
    assert "youtube.googleapis.com" in out
    assert "key=[redacted]" in out


def test_redact_is_safe_on_empty_and_none() -> None:
    assert redact(None) == ""
    assert redact("") == ""
    assert redact("nothing sensitive here") == "nothing sensitive here"


def test_error_event_scrubs_the_message() -> None:
    """The single funnel every error takes to the browser."""
    event = make_error_event("run-1", "cli_failed", f"The agent CLI failed: {_URI}")
    assert _KEY not in event.error.message
    assert _KEY not in (event.detail or "")
    assert _KEY not in event.model_dump_json()


def test_http_error_note_never_includes_the_uri() -> None:
    """Reproduces the original leak: HttpError.__str__ embeds the request URI."""

    class _Resp:
        status = 403

    class _FakeHttpError(Exception):
        resp = _Resp()
        reason = "quotaExceeded"

        def __str__(self) -> str:  # what googleapiclient actually does
            return f"<HttpError 403 when requesting {_URI} returned 'quotaExceeded'>"

    exc = _FakeHttpError()
    assert _KEY in str(exc), "precondition: the raw exception leaks the key"

    note = http_error_note(exc)
    assert _KEY not in note
    assert "403" in note


# ---------------------------------------------------------------------------
# Request guards
# ---------------------------------------------------------------------------


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


def test_rebound_host_is_rejected(client: TestClient) -> None:
    """DNS rebinding: attacker domain re-resolved to 127.0.0.1."""
    resp = client.get("/api/config", headers={"Host": "attacker-rebound.example:8000"})
    assert resp.status_code == 400


def test_localhost_hosts_are_accepted(client: TestClient) -> None:
    for host in ("localhost:8000", "127.0.0.1:8000"):
        assert client.get("/api/config", headers={"Host": host}).status_code == 200


def test_cross_site_post_is_rejected(client: TestClient) -> None:
    """A page on evil.example must not reach a state-changing endpoint.

    /config/remedy opens a Terminal, so the side effect matters even though
    CORS would hide the response.
    """
    resp = client.post(
        "/api/config/remedy",
        headers={"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
    )
    assert resp.status_code == 403


def test_cross_site_form_post_without_fetch_metadata_is_rejected(
    client: TestClient,
) -> None:
    """The no-JavaScript variant: an auto-submitting form still sends Origin."""
    resp = client.post(
        "/api/config/remedy",
        headers={"Origin": "https://evil.example"},
        data={"adapter": "claude_code"},
    )
    assert resp.status_code == 403


def test_bodyless_cross_site_post_is_rejected(client: TestClient) -> None:
    """The original bypass: no body => CORS-simple => never preflighted."""
    for path in ("/api/config/remedy", "/api/config/env-check", "/api/config/key-test"):
        resp = client.post(path, headers={"Sec-Fetch-Site": "cross-site"})
        assert resp.status_code == 403, path


def test_same_origin_post_still_works(client: TestClient) -> None:
    """The real client must keep working — bodyless POST included (api.ts:350)."""
    resp = client.post(
        "/api/config/env-check",
        headers={"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"},
    )
    assert resp.status_code == 200


def test_vite_proxy_same_site_post_still_works(client: TestClient) -> None:
    """localhost:5173 -> localhost:8000 is same-site (site ignores port)."""
    resp = client.post(
        "/api/config/env-check",
        headers={"Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-site"},
    )
    assert resp.status_code == 200


def test_non_browser_client_still_works(client: TestClient) -> None:
    """curl / the test suite send no fetch metadata; they are not the threat."""
    assert client.post("/api/config/env-check").status_code == 200


def test_safe_methods_are_never_blocked(client: TestClient) -> None:
    resp = client.get("/api/config", headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 200
