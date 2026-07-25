"""The one-port mode: the backend serving the built SPA (app/spa.py).

Two things are worth pinning down here. First, that serving the SPA never
weakens the API surface — an unmatched /api path must still 404 as JSON on every
method, or an endpoint typo turns into a confusing parse error at the call site.
Second, that it is strictly opt-in: `make dev` must keep :8000 API-only even
with a stale dist/ present, so nobody debugs a UI they are not running.

The fixture builds a throwaway dist instead of using frontend/dist, so these
pass whether or not anyone has run `make build`.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.spa import SERVE_SPA_ENV, mount_spa, spa_requested

_INDEX_HTML = "<!doctype html><title>YuBen</title><div id=root></div>"


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    """A minimal stand-in for `npm run build` output."""
    (tmp_path / "index.html").write_text(_INDEX_HTML)
    (tmp_path / "favicon.svg").write_text("<svg/>")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index-abc123.js").write_text("console.log(1)")
    return tmp_path


@pytest.fixture
def client(dist: Path) -> TestClient:
    """An app with a couple of real-shaped API routes, plus the SPA mounted."""
    app = FastAPI()

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    @app.post("/api/thing")
    async def thing():
        return {"ok": True}

    assert mount_spa(app, dist) is True
    return TestClient(app)


# --- opt-in switch ---------------------------------------------------------


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_spa_requested_accepts_truthy_spellings(value: str):
    assert spa_requested({SERVE_SPA_ENV: value}) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_spa_requested_rejects_everything_else(value: str):
    """`=0` must read as off — a naive truthiness check would call it on."""
    assert spa_requested({SERVE_SPA_ENV: value}) is False


def test_spa_not_requested_when_env_absent():
    assert spa_requested({}) is False


def test_mount_is_a_noop_without_a_build(tmp_path: Path):
    """An empty dist/ must leave the app untouched rather than half-mounted."""
    app = FastAPI()
    assert mount_spa(app, tmp_path) is False

    resp = TestClient(app).get("/")
    assert resp.status_code == 404


def test_dev_mode_leaves_the_backend_api_only():
    """The real app, imported without the env var set: no UI on :8000.

    This is the regression that matters — inferring the mount from dist/ meant a
    developer who had ever run a build got a stale SPA here instead of a 404.
    """
    from app.main import app as real_app

    assert spa_requested({}) is False
    assert TestClient(real_app).get("/").status_code == 404


# --- the API surface is unchanged by mounting -----------------------------


def test_api_routes_still_win_over_the_catch_all(client: TestClient):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
def test_unknown_api_path_404s_as_json_on_every_method(
    client: TestClient, method: str
):
    """Never the HTML shell: a typo'd endpoint must not read as a parse error."""
    resp = getattr(client, method)("/api/nope")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}
    assert "text/html" not in resp.headers["content-type"]


def test_bare_api_prefix_404s(client: TestClient):
    assert client.get("/api").status_code == 404


# --- serving the app ------------------------------------------------------


def test_root_serves_the_shell(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.text == _INDEX_HTML


@pytest.mark.parametrize("route", ["/history", "/run/r_abc", "/onboarding/model"])
def test_client_side_routes_fall_back_to_the_shell(client: TestClient, route: str):
    """BrowserRouter paths only exist once React boots, so a hard load of one
    has to return index.html for the router to resolve it."""
    resp = client.get(route)
    assert resp.status_code == 200
    assert resp.text == _INDEX_HTML


def test_shell_is_revalidated_not_cached(client: TestClient):
    """It names hashed bundles, so a cached shell outlives its own assets."""
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_real_files_are_served_from_the_build(client: TestClient):
    assert client.get("/favicon.svg").text == "<svg/>"
    assert client.get("/assets/index-abc123.js").status_code == 200


def test_non_read_method_on_an_app_path_is_405(client: TestClient):
    resp = client.post("/history")
    assert resp.status_code == 405


def test_traversal_cannot_escape_the_build(client: TestClient, dist: Path):
    """`..` in the URL must not reach files outside dist/."""
    secret = dist.parent / "outside.txt"
    secret.write_text("do not serve me")

    for attempt in ("/../outside.txt", "/%2e%2e%2foutside.txt", "/assets/../../outside.txt"):
        resp = client.get(attempt)
        assert "do not serve me" not in resp.text, attempt
