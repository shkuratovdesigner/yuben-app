"""Reliability Phase 1: correct errors before YouTube quota is spent.

Covers the typed adapter errors (SDK exception -> AdapterError.kind), the
orchestrator's kind/code -> ErrorCode mapping and wording, YouTube errors by
reason, and the model-check preflight. No network, no keys, no quota.
"""
import json
import os
import tempfile

os.environ.setdefault("YUBEN_DATA_DIR", tempfile.mkdtemp(prefix="yuben-errors-test-"))
os.environ.setdefault("YUBEN_FORCE_FILE_SECRET", "1")

import anthropic  # noqa: E402
import httplib2  # noqa: E402
import httpx2  # noqa: E402
import openai  # noqa: E402
import pytest  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402

import app.adapters as registry  # noqa: E402
from app.adapters import base  # noqa: E402
from app.adapters.base import AdapterError, OutputTruncated, api_error  # noqa: E402
from app.orchestrator import run_research_job  # noqa: E402
from app.orchestrator import runner as _runner  # noqa: E402
from app.pipeline import PipelineError  # noqa: E402
from app.pipeline import runner as pipeline_runner  # noqa: E402
from app.pipeline._paths import install_youtube_research_alias  # noqa: E402
from app.store import run_store  # noqa: E402
from contracts.python.models import ProgressEvent, ResearchRequest  # noqa: E402

install_youtube_research_alias()
from youtube_research import youtube_api  # noqa: E402


# --------------------------------------------------------------------------- #
# helpers                                                                     #
# --------------------------------------------------------------------------- #
def _status_error(sdk, cls_name, status, message="boom", body=None):
    request = httpx2.Request("POST", "https://api.example.test/v1/x")
    response = httpx2.Response(status, request=request)
    return getattr(sdk, cls_name)(message, response=response, body=body)


def _connection_error(sdk, cls_name="APIConnectionError"):
    request = httpx2.Request("POST", "https://api.example.test/v1/x")
    if cls_name == "APITimeoutError":
        return sdk.APITimeoutError(request=request)
    return sdk.APIConnectionError(request=request)


def _http_error(status, reason=None, message="", details_reason=None):
    error = {"code": status, "message": message, "errors": []}
    if reason:
        error["errors"].append({"reason": reason, "message": message})
    if details_reason:
        error["details"] = [{"reason": details_reason}]
    resp = httplib2.Response({"status": status})
    resp.reason = "Forbidden" if status == 403 else "Bad Request"
    return HttpError(resp, json.dumps({"error": error}).encode(), uri="https://x?key=SECRET")


def _request(adapter="openai-api", model="gpt-4o"):
    return ResearchRequest.model_validate(
        dict(
            schema_version="1.0",
            query="how to promote your airbnb",
            format="longform",
            upload_date="all",
            outperformance="highest",
            analyze_titles=False,
            analyze_scripts=False,
            model={"adapter": adapter, "model": model},
            max_results=15,
        )
    )


def _last_error(run_id):
    ev = run_store.get_events(run_id)[-1]
    return ev.error if isinstance(ev, ProgressEvent) else ev.get("error")


class _RaisingAdapter:
    """Expansion yields nothing; the narrative raises ``exc``."""

    def __init__(self, exc, *, agentic):
        self.exc = exc
        self.agentic = agentic
        self.calls = 0

    def stream(self, prompt, *, model=None, cwd=None):
        self.calls += 1
        if self.calls == 1:
            return iter(['["airbnb hosting"]'])

        def gen():
            raise self.exc
            yield  # pragma: no cover

        return gen()


def _pipeline_with_videos():
    from contracts.python.models import Video
    from pathlib import Path

    fixture = json.loads(
        (Path(__file__).resolve().parents[2] / "contracts" / "fixtures" / "research-result.longform.json").read_text(encoding="utf-8")
    )
    videos = [Video.model_validate(v) for v in fixture["top_videos"]]
    return lambda request, keywords=None: (videos, dict(fixture["meta"]))


def _run(adapter, *, pipeline=None, preflight=None, request=None):
    req = request or _request()
    run_id = run_store.create_run(req)
    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=pipeline or _pipeline_with_videos(),
        verifier=lambda *a: pytest.fail("verifier must not run"),
        preflight=preflight or (lambda adapter, model: None),
    )
    return _last_error(run_id)


@pytest.fixture(autouse=True)
def _isolate():
    run_store.reset()
    _runner.reset()
    registry.reset_checks()
    youtube_api.reset_quota_flag()
    yield
    run_store.reset()
    _runner.reset()
    registry.reset_checks()
    youtube_api.reset_quota_flag()


# --------------------------------------------------------------------------- #
# Step 1: SDK exceptions -> typed AdapterError                                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sdk", [anthropic, openai], ids=["anthropic", "openai"])
@pytest.mark.parametrize(
    "make, kind",
    [
        (lambda sdk: _status_error(sdk, "AuthenticationError", 401), base.KIND_AUTH),
        (lambda sdk: _status_error(sdk, "PermissionDeniedError", 403), base.KIND_AUTH),
        (lambda sdk: _status_error(sdk, "NotFoundError", 404), base.KIND_MODEL_NOT_FOUND),
        (lambda sdk: _status_error(sdk, "RateLimitError", 429), base.KIND_RATE_LIMIT),
        (lambda sdk: _status_error(sdk, "BadRequestError", 400, "temperature is invalid"), base.KIND_BAD_REQUEST),
        (lambda sdk: _status_error(sdk, "BadRequestError", 400, "prompt is too long: 250000 tokens"), base.KIND_CONTEXT_TOO_LONG),
        (lambda sdk: _status_error(sdk, "InternalServerError", 500), base.KIND_SERVER),
        (lambda sdk: _connection_error(sdk), base.KIND_NETWORK),
        (lambda sdk: _connection_error(sdk, "APITimeoutError"), base.KIND_NETWORK),
        (lambda sdk: ValueError("odd"), base.KIND_UNKNOWN),
    ],
)
def test_api_error_kinds(sdk, make, kind):
    err = api_error(make(sdk), sdk, "Provider")
    assert isinstance(err, AdapterError)
    assert err.kind == kind
    assert str(err)


def test_api_error_ignores_lookalike_class_names():
    # Classification is by SDK type, not by class name.
    class RateLimitError(Exception):
        pass

    assert api_error(RateLimitError("429"), openai, "OpenAI").kind == base.KIND_UNKNOWN


def test_openai_context_code_and_insufficient_quota():
    ctx = _status_error(openai, "BadRequestError", 400, "too many tokens", body={"code": "context_length_exceeded"})
    assert api_error(ctx, openai, "OpenAI").kind == base.KIND_CONTEXT_TOO_LONG
    quota = _status_error(openai, "RateLimitError", 429, "quota", body={"code": "insufficient_quota"})
    err = api_error(quota, openai, "OpenAI")
    assert err.kind == base.KIND_RATE_LIMIT
    assert "billing" in str(err).lower()


def test_anthropic_overloaded_and_request_too_large():
    overloaded = _status_error(anthropic, "OverloadedError", 529)
    assert api_error(overloaded, anthropic, "Anthropic").kind == base.KIND_SERVER
    too_large = _status_error(anthropic, "RequestTooLargeError", 413)
    assert api_error(too_large, anthropic, "Anthropic").kind == base.KIND_CONTEXT_TOO_LONG


def test_output_truncated_is_output_limit_kind():
    assert OutputTruncated("OpenAI").kind == base.KIND_OUTPUT_LIMIT


# --------------------------------------------------------------------------- #
# Steps 1 + 3: kind -> ErrorCode, and "the model" vs "the agent CLI"          #
# --------------------------------------------------------------------------- #
def test_openai_rate_limit_is_not_reported_as_youtube_quota():
    exc = api_error(_status_error(openai, "RateLimitError", 429), openai, "OpenAI")
    error = _run(_RaisingAdapter(exc, agentic=False))
    assert error.code == "cli_failed"
    assert "OpenAI" in error.message and "YouTube" not in error.message
    assert "agent CLI" not in error.message


def test_auth_and_model_not_found_send_the_user_to_setup():
    for exc in (
        api_error(_status_error(anthropic, "AuthenticationError", 401), anthropic, "Anthropic"),
        api_error(_status_error(openai, "NotFoundError", 404), openai, "OpenAI"),
    ):
        assert _run(_RaisingAdapter(exc, agentic=False)).code == "cli_missing"


def test_cli_adapter_failure_still_says_agent_cli():
    error = _run(_RaisingAdapter(AdapterError("exit 1: boom"), agentic=True))
    assert error.code == "cli_failed"
    assert error.message.startswith("The agent CLI failed")


def test_cli_adapter_unknown_error_says_agent_cli():
    error = _run(_RaisingAdapter(RuntimeError("weird"), agentic=True))
    assert error.code == "cli_failed"
    assert error.message.startswith("The agent CLI failed: weird")


def test_api_adapter_unknown_error_says_the_model():
    error = _run(_RaisingAdapter(RuntimeError("weird"), agentic=False))
    assert error.code == "cli_failed"
    assert error.message.startswith("The model failed")


def test_truncated_answer_is_invalid_output():
    error = _run(_RaisingAdapter(OutputTruncated("OpenAI"), agentic=False))
    assert error.code == "invalid_output"
    assert "cut off" in error.message


@pytest.mark.parametrize(
    "code", ["quota_exceeded", "cli_missing", "cli_failed", "no_results", "invalid_output", "unknown"]
)
def test_pipeline_error_code_is_honoured(code):
    def pipeline(request, keywords=None):
        raise PipelineError("pipeline says %s" % code, code=code)

    error = _run(_RaisingAdapter(AssertionError(), agentic=False), pipeline=pipeline)
    assert error.code == code
    assert error.message == "pipeline says %s" % code


def test_missing_youtube_key_is_not_a_cli_failure():
    def pipeline(request, keywords=None):
        raise PipelineError("No YouTube API key is stored.", code="quota_exceeded")

    error = _run(_RaisingAdapter(AssertionError(), agentic=True), pipeline=pipeline)
    assert error.code == "quota_exceeded"
    assert "CLI" not in error.message


def test_unexpected_pipeline_error_is_a_search_failure():
    def pipeline(request, keywords=None):
        raise RuntimeError("HTTP 403 rate limit")  # substrings no longer decide

    error = _run(_RaisingAdapter(AssertionError(), agentic=True), pipeline=pipeline)
    assert error.code == "unknown"
    assert error.message.startswith("The YouTube search failed")


def test_unknown_adapter_id_goes_to_setup():
    req = _request(adapter="nope")
    run_id = run_store.create_run(req)

    def factory(_id):
        raise KeyError(_id)

    run_research_job(run_id, req, adapter_factory=factory, pipeline_runner=_pipeline_with_videos())
    assert _last_error(run_id).code == "cli_missing"


# --------------------------------------------------------------------------- #
# Step 2: YouTube errors by reason                                            #
# --------------------------------------------------------------------------- #
def test_quota_reason_returns_partial_and_marks_quota():
    assert youtube_api.handle_http_error(_http_error(403, "quotaExceeded"), "search") is True
    assert youtube_api.quota_was_hit() is True


@pytest.mark.parametrize(
    "status, reason, details_reason, message, needle",
    [
        (403, "accessNotConfigured", None, "", "Enable YouTube Data API v3"),
        (403, "forbidden", "SERVICE_DISABLED", "", "Enable YouTube Data API v3"),
        (400, "keyInvalid", None, "", "invalid"),
        (400, "badRequest", None, "API key not valid. Please pass a valid API key.", "invalid"),
        (403, "forbidden", None, "", "restricted"),
        (403, "ipRefererBlocked", None, "", "restricted"),
        (403, None, None, "", "restricted"),
    ],
)
def test_setup_reasons_raise_with_the_fix(status, reason, details_reason, message, needle):
    with pytest.raises(youtube_api.YouTubeSetupError) as info:
        youtube_api.handle_http_error(_http_error(status, reason, message, details_reason), "search")
    assert needle in str(info.value)
    assert "SECRET" not in str(info.value)
    assert youtube_api.quota_was_hit() is False


def test_other_errors_are_left_to_the_caller():
    assert youtube_api.handle_http_error(_http_error(400, "invalidParameter"), "search") is False


def test_search_videos_raises_on_unenabled_api(monkeypatch):
    class _Request:
        def execute(self):
            raise _http_error(403, "accessNotConfigured")

    class _Search:
        def list(self, **kw):
            return _Request()

    class _Service:
        def search(self):
            return _Search()

    monkeypatch.setattr(youtube_api, "build_service", lambda: _Service())
    monkeypatch.setattr(youtube_api.time, "sleep", lambda s: None)
    with pytest.raises(youtube_api.YouTubeSetupError):
        youtube_api.search_videos("q", "2026-01-01T00:00:00Z")


def _params():
    return pipeline_runner.map_request_to_params(_request(), keywords=["airbnb"])


def test_pipeline_maps_setup_error_to_quota_code_with_fix(monkeypatch):
    def script(params):
        raise youtube_api.YouTubeSetupError(youtube_api._NOT_ENABLED)

    monkeypatch.setattr(pipeline_runner, "_run_script", script)
    with pytest.raises(PipelineError) as info:
        pipeline_runner._run_youtube(_params())
    assert info.value.code == "quota_exceeded"
    assert "Enable YouTube Data API v3" in str(info.value)


def test_pipeline_quota_with_nothing_collected_is_the_quota_error(monkeypatch):
    def script(params):
        youtube_api.handle_http_error(_http_error(403, "quotaExceeded"), "search")
        return {"videos": []}, "longform_research", True

    monkeypatch.setattr(pipeline_runner, "_run_script", script)
    with pytest.raises(PipelineError) as info:
        pipeline_runner._run_youtube(_params())
    assert info.value.code == "quota_exceeded"
    assert "quota" in str(info.value).lower()


def test_pipeline_quota_with_partial_results_keeps_them(monkeypatch):
    def script(params):
        youtube_api.handle_http_error(_http_error(403, "dailyLimitExceeded"), "video details")
        return {"videos": [{"video_id": "abc"}]}, "longform_research", True

    monkeypatch.setattr(pipeline_runner, "_run_script", script)
    raw, _, _ = pipeline_runner._run_youtube(_params())
    assert raw["videos"] == [{"video_id": "abc"}]


def test_quota_flag_resets_per_run(monkeypatch):
    youtube_api.handle_http_error(_http_error(403, "quotaExceeded"), "search")
    monkeypatch.setattr(
        pipeline_runner, "_run_script", lambda params: ({"videos": []}, "longform_research", True)
    )
    raw, _, _ = pipeline_runner._run_youtube(_params())  # earlier run's flag is cleared
    assert raw["videos"] == []


# --------------------------------------------------------------------------- #
# Step 5: preflight before any YouTube quota is spent                         #
# --------------------------------------------------------------------------- #
class _CheckedAdapter:
    id = "fake-api"
    agentic = False

    def __init__(self, ok=True, message="Fake responded."):
        self.ok = ok
        self.message = message
        self.key = "k1"
        self.checks = 0

    def check_env(self, model=None):
        self.checks += 1
        return {"ok": self.ok, "adapter": self.id, "version": None, "message": self.message}

    def settings_fingerprint(self, model):
        return "key=" + base.key_digest(self.key)

    def stream(self, prompt, *, model=None, cwd=None):  # pragma: no cover - not reached
        return iter(())


def test_failed_check_stops_the_run_before_youtube():
    adapter = _CheckedAdapter(ok=False, message="OpenAI rejected the API key.")
    searched = []

    def pipeline(request, keywords=None):
        searched.append(True)
        return [], {}

    req = _request()
    run_id = run_store.create_run(req)
    run_research_job(run_id, req, adapter_factory=lambda _id: adapter, pipeline_runner=pipeline)
    error = _last_error(run_id)
    assert error.code == "cli_missing"
    assert "OpenAI rejected the API key." in error.message
    assert "no YouTube quota was used" in error.message
    assert searched == []


def test_passing_check_is_reused_until_settings_change():
    adapter = _CheckedAdapter()
    assert registry.ensure_checked(adapter, "gpt-4o") is None
    assert registry.ensure_checked(adapter, "gpt-4o") is None
    assert adapter.checks == 1
    assert registry.ensure_checked(adapter, "gpt-4o-mini") is None  # new model
    assert adapter.checks == 2
    adapter.key = "k2"  # new key -> new fingerprint
    assert registry.ensure_checked(adapter, "gpt-4o") is None
    assert adapter.checks == 3


def test_onboarding_check_counts_for_the_preflight(monkeypatch):
    adapter = _CheckedAdapter()
    monkeypatch.setitem(registry._ADAPTERS, "fake-api", adapter)
    assert registry.check_env("fake-api", "gpt-4o")["ok"] is True
    assert registry.has_passing_check(adapter, "gpt-4o")
    assert registry.ensure_checked(adapter, "gpt-4o") is None
    assert adapter.checks == 1


def test_failed_check_forgets_an_earlier_pass():
    adapter = _CheckedAdapter()
    registry.ensure_checked(adapter, "gpt-4o")
    adapter.ok = False
    registry._record_check(adapter, "gpt-4o", adapter.check_env("gpt-4o"))
    assert not registry.has_passing_check(adapter, "gpt-4o")


def test_output_cap_override_changes_the_fingerprint(monkeypatch):
    from app.adapters.openai_compatible import OpenAIAdapter

    impl = OpenAIAdapter()
    monkeypatch.setattr(impl, "_stored_key", lambda: "sk-test")
    monkeypatch.delenv("YUBEN_MAX_OUTPUT_TOKENS", raising=False)
    first = impl.settings_fingerprint("gpt-4o")
    monkeypatch.setenv("YUBEN_MAX_OUTPUT_TOKENS", "8000")
    assert impl.settings_fingerprint("gpt-4o") != first
    assert "sk-test" not in first
