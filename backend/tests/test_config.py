"""B1 verification: config router + write-only key storage + stub surface.

The local store is isolated to a temp dir (``YUBEN_DATA_DIR``) and the secret
backend is forced to the local file (``YUBEN_FORCE_FILE_SECRET``) so these tests
never touch a real ``backend/.yuben`` or the OS keychain. Env vars are set before
importing the app; store paths resolve at call time, so this is sufficient.
"""
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="yuben-test-")
os.environ["YUBEN_DATA_DIR"] = _TMP
os.environ["YUBEN_FORCE_FILE_SECRET"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

_DUMMY_KEY = "AIzaSyDUMMY-not-a-real-key-000000000000"


def test_health_ok():
    assert client.get("/api/health").status_code == 200


def test_get_config_defaults_no_key():
    # Runs before any mutation (module-order): a clean, empty store.
    resp = client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema_version"] == "1.0"
    assert body["adapter"] is None
    assert body["model"] is None
    assert body["youtube_key_present"] is False
    assert body["anthropic_key_present"] is False
    assert body["onboarding_complete"] is False


def test_put_config_roundtrips():
    resp = client.put("/api/config", json={"adapter": "claude-code", "model": "default"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["adapter"] == "claude-code"
    assert body["model"] == "default"
    # Round-trips on a fresh GET.
    body2 = client.get("/api/config").json()
    assert body2["adapter"] == "claude-code"
    assert body2["model"] == "default"


def test_put_config_partial_update_preserves_fields():
    client.put("/api/config", json={"adapter": "claude-code", "model": "default"})
    client.put("/api/config", json={"onboarding_complete": True})
    body = client.get("/api/config").json()
    assert body["adapter"] == "claude-code"  # preserved, not wiped
    assert body["model"] == "default"
    assert body["onboarding_complete"] is True


def test_put_config_ignores_unknown_keys():
    # An echoed full Config (with derived/immutable fields) must not 422.
    resp = client.put(
        "/api/config",
        json={
            "schema_version": "1.0",
            "adapter": "gemini-cli",
            "model": "default",
            "youtube_key_present": True,
            "onboarding_complete": True,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["adapter"] == "gemini-cli"


def test_post_key_is_write_only():
    resp = client.post("/api/config/key", json={"key": _DUMMY_KEY})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    # The key never appears in the acknowledgement body.
    assert _DUMMY_KEY not in resp.text
    # The present-flag flips true, but the value is still never returned.
    cfg = client.get("/api/config")
    assert cfg.json()["youtube_key_present"] is True
    assert _DUMMY_KEY not in cfg.text


def test_post_key_rejects_empty():
    assert client.post("/api/config/key", json={"key": ""}).status_code == 422
    assert client.post("/api/config/key", json={}).status_code == 422


def test_post_anthropic_key_is_write_only_and_separate():
    _ANTHROPIC = "sk-ant-dummy-not-a-real-key-000000"
    resp = client.post("/api/config/key", json={"key": _ANTHROPIC, "provider": "anthropic"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert _ANTHROPIC not in resp.text  # write-only: never echoed
    cfg = client.get("/api/config").json()
    assert cfg["anthropic_key_present"] is True
    assert _ANTHROPIC not in client.get("/api/config").text


def test_env_check_wired_to_adapter_probe(monkeypatch):
    # B2 (Wave 2) wired env-check: the config router now delegates to
    # app.adapters.check_env. Monkeypatch it so this stays deterministic
    # (no live CLI turn) while still exercising the route + coercion.
    import app.adapters as adapters_pkg

    monkeypatch.setattr(
        adapters_pkg,
        "check_env",
        lambda adapter, model=None: {
            "ok": True, "adapter": adapter, "version": "2.1.198", "message": "probe ok",
        },
    )
    resp = client.post("/api/config/env-check", json={"adapter": "claude-code"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["adapter"] == "claude-code"
    assert body["version"] == "2.1.198"
    assert body["message"] == "probe ok"


def test_env_check_without_body_ok():
    # No body: adapter falls back to stored config; still a graceful stub.
    resp = client.post("/api/config/env-check")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_key_test_graceful_stub(monkeypatch):
    # B3 (Wave 2) wired the key-test: the config router now delegates to
    # app.pipeline.test_youtube_key, which reads the stored key via
    # secrets.get_youtube_key. Force the "no key" path so this stays
    # deterministic and offline (no live YouTube call) while still exercising
    # the route + coercion. (Mirrors the env-check update above for B2.)
    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: None)
    resp = client.post("/api/config/key-test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "No YouTube API key" in body["message"]


def test_stub_routers_return_501():
    # /api/adapters is implemented by B2 (Wave 2) and now returns 200 — see
    # test_adapters.py. The B5 routes (GET /api/research/{id}, /api/history*,
    # implemented in Wave 2 too and now return real responses — see
    # test_verify.py. B4's research lifecycle is now live too
    # (see test_orchestrator.py): an empty body fails validation, and the
    # events/cancel routes 404 on an unknown run.
    assert client.post("/api/research", json={}).status_code == 422
    assert client.get("/api/research/r_x/events").status_code == 404
    assert client.post("/api/research/r_x/cancel").status_code == 404


# --- store-level checks: the shared surfaces B4/B5 build on -------------------
def test_run_store_lifecycle():
    from app.store import run_store

    run_id = run_store.create_run({"query": "ai agents"})
    assert run_id.startswith("r_")
    assert run_store.has_run(run_id)
    assert run_store.get_status(run_id) == {"status": "queued", "phase": "queued"}

    run_store.set_phase(run_id, "searching")
    assert run_store.get_status(run_id)["status"] == "running"

    # append_event advances phase/status from the event too.
    run_store.append_event(run_id, {"phase": "scoring", "label": "Scoring"})
    assert run_store.get_events(run_id)[-1]["phase"] == "scoring"
    assert run_store.get_status(run_id)["phase"] == "scoring"

    assert run_store.get_result(run_id) is None
    run_store.set_result(run_id, {"ok": True})
    assert run_store.get_result(run_id) == {"ok": True}
    assert run_store.get_status(run_id)["status"] == "done"

    # Unknown run is distinguishable from a real one.
    assert run_store.get_status("r_nope") == {"status": "not_found", "phase": None}
    assert run_store.get_result("r_nope") is None


def test_history_store_roundtrip():
    from contracts.python.models import HistoryItem
    from app.store import history_store

    item = HistoryItem(
        run_id="r_test_hist",
        topic_title="Test topic",
        query="test query",
        format="longform",
        created_at="2026-07-11T10:00:00Z",
        counts={"curated": 15},
        outperformance="highest",
    )
    history_store.add_history(item)
    ids = {h.run_id for h in history_store.list_history()}
    assert "r_test_hist" in ids
    assert history_store.delete_history("r_test_hist") is True
    assert history_store.delete_history("r_test_hist") is False
