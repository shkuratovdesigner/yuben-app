"""B4 verification: prompt builder, run loop, SSE, cancel — with fakes.

The B2 adapter / B3 pipeline / B5 verify seams are DOCUMENTED but not built yet,
so every test here injects fakes:
  * fake adapter  -> yields a canned AgentResult as Claude-Code stream-json lines
  * fake pipeline -> returns the fixture ``Video[]`` + meta
  * stub verifier -> returns a ready ``ResearchResult`` (the join is B5's job)

The run loop is exercised two ways: directly (``run_research_job`` with injected
deps — deterministic, no threads) and end-to-end over HTTP+SSE (monkeypatching
the lazy ``_default_*`` resolvers so ``launch`` uses fakes).
"""
import json
import os
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("YUBEN_DATA_DIR", tempfile.mkdtemp(prefix="yuben-orch-test-"))
os.environ.setdefault("YUBEN_FORCE_FILE_SECRET", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from contracts.python.models import (  # noqa: E402
    AgentResult,
    ProgressEvent,
    ResearchRequest,
    ResearchResult,
    Video,
)

from app.main import app  # noqa: E402
from app.store import run_store  # noqa: E402
from app.orchestrator import (  # noqa: E402
    build_narrative_prompt,
    build_repair_prompt,
    map_filters,
    request_cancel,
    run_research_job,
)
from app.orchestrator import runner as _runner  # noqa: E402
from app.orchestrator.events import make_event  # noqa: E402
from app.orchestrator.parse import StreamCollector, find_last_json_object  # noqa: E402

client = TestClient(app)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE = json.loads(
    (_REPO_ROOT / "contracts" / "fixtures" / "research-result.longform.json").read_text()
)


# --------------------------------------------------------------------------- #
# fixtures / fakes                                                            #
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _isolate_runs():
    run_store.reset()
    _runner.reset()
    yield
    run_store.reset()
    _runner.reset()


def _request(**over) -> ResearchRequest:
    base = dict(
        schema_version="1.0",
        query="how to promote your airbnb",
        format="longform",
        upload_date="all",
        outperformance="highest",
        analyze_titles=True,
        analyze_scripts=True,
        model={"adapter": "claude-code", "model": "default"},
        max_results=15,
    )
    base.update(over)
    return ResearchRequest.model_validate(base)


def _agent_result_dict(*, titles=True, scripts=True) -> dict:
    return {
        "schema_version": "1.0",
        "topic_title": _FIXTURE["topic_title"],
        "summary": _FIXTURE["summary"],
        "keywords": _FIXTURE["meta"]["keywords"],
        "top_video_ids": [
            {"video_id": v["video_id"], "rank": i + 1}
            for i, v in enumerate(_FIXTURE["top_videos"])
        ],
        "watch_list": _FIXTURE["watch_list"],
        "title_analysis": _FIXTURE["title_analysis"] if titles else None,
        "script_analysis": _FIXTURE["script_analysis"] if scripts else None,
    }


def _streamjson_lines(agent_obj) -> list:
    """A realistic Claude-Code ``--output-format stream-json`` transcript whose
    final ``result`` event carries the agent's JSON as a string."""
    return [
        json.dumps({"type": "system", "subtype": "init", "tools": ["bash"]}),
        json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Expanding keywords."}]}}
        ),
        json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "bash", "input": {}}]}}
        ),
        json.dumps({"type": "result", "subtype": "success", "result": json.dumps(agent_obj)}),
    ]


def _streamjson_text(answer: str) -> list:
    """A stream-json transcript whose answer is a bare string (not an object).

    The keyword step returns a JSON *array*, and the CLI hands it over as a string
    inside a ``result`` event — its brackets live inside a JSON string literal, so
    scanning the raw line for an array finds nothing. The collector has to unwrap.
    """
    return [
        json.dumps({"type": "system", "subtype": "init", "tools": ["bash"]}),
        json.dumps({"type": "result", "subtype": "success", "result": answer}),
    ]


class FakeAdapter:
    """A stream-json CLI adapter, driven through the run loop's two LLM steps.

    Call 1 is keyword expansion — the array comes back wrapped in a ``result``
    event, exactly as the real CLI frames it. Calls 2+ are the AgentResult
    narrative; each may use a different canned transcript (repair retry).
    """

    def __init__(self, transcripts, keyword_lines=None):
        self._transcripts = list(transcripts)
        self._keyword_lines = (
            keyword_lines
            if keyword_lines is not None
            else _streamjson_text('["ai agents", "agent orchestration"]')
        )
        self.calls = 0
        self.prompts = []
        self.stream_kwargs = []

    def stream(self, prompt, *, model=None, cwd=None):
        self.prompts.append(prompt)
        self.stream_kwargs.append({"model": model, "cwd": cwd})
        self.calls += 1
        if self.calls == 1:
            lines = self._keyword_lines
        else:
            idx = min(self.calls - 2, len(self._transcripts) - 1)
            lines = self._transcripts[idx]

        def gen():
            for line in lines:
                yield line

        return gen()

    @property
    def narrative_prompts(self):
        """The prompts after the expansion call — what ``_run_agent`` sent."""
        return self.prompts[1:]


def _fake_pipeline(videos=None, meta=None):
    vids = videos if videos is not None else [Video.model_validate(v) for v in _FIXTURE["top_videos"]]
    m = meta if meta is not None else dict(_FIXTURE["meta"])

    def runner(request, keywords=None):
        return vids, m

    return runner


def _fake_verifier(request, agent_result, videos, meta):
    data = dict(_FIXTURE)
    data["request"] = request.model_dump()
    return ResearchResult.model_validate(data)


def _events(run_id):
    return run_store.get_events(run_id)


def _phases(run_id):
    return [e.phase if isinstance(e, ProgressEvent) else e.get("phase") for e in _events(run_id)]


def _last_error(run_id):
    ev = _events(run_id)[-1]
    return ev.error if isinstance(ev, ProgressEvent) else ev.get("error")


def _wait_until(pred, timeout=5.0, interval=0.02):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return pred()


# --------------------------------------------------------------------------- #
# prompt builder + filter mapping                                            #
# --------------------------------------------------------------------------- #
def test_map_filters_maps_ui_to_script_params():
    f = map_filters(_request(upload_date="7d", outperformance="5x", format="shorts"))
    assert f["script"] == "shorts_research.py"
    assert f["days"] == 7
    assert f["floor_iso"] is not None  # a concrete ISO floor was computed
    assert f["window_label"] == "Last 7 days"
    assert f["outperformance"]["threshold"] == 5.0
    assert f["max_results"] == 15

    f_all = map_filters(_request(upload_date="all", outperformance="highest"))
    assert f_all["days"] is None and f_all["floor_iso"] is None
    assert f_all["outperformance"]["mode"] == "sort"


def test_narrative_prompt_embeds_trust_and_filters():
    prompt = build_narrative_prompt(
        _request(upload_date="7d", outperformance="5x", format="longform"),
        _fixture_videos(),
    )
    # HARD TRUST RULE baked in (CONTRACTS §7 / PRD §8).
    assert "MUST NOT invent" in prompt
    assert "narrative only" in prompt
    assert "video_id" in prompt
    assert "DROPS" in prompt
    # Mapped filters surfaced to the agent.
    assert "Last 7 days" in prompt
    assert "5× and up" in prompt or "VSR ≥ 5.0" in prompt
    assert "max_results = 15" in prompt
    # Output contract present.
    assert "schema_version" in prompt and "top_video_ids" in prompt


def test_narrative_prompt_never_asks_the_agent_to_research():
    """The bug this replaced: an agentic CLI ran its own search, and B5 dropped
    every id it returned because they weren't in the pipeline's set."""
    prompt = build_narrative_prompt(_request(), _fixture_videos())
    assert "longform_research.py" not in prompt
    assert "shorts_research.py" not in prompt
    assert "Do NOT run scripts" in prompt
    # The only ids it may cite are the collected ones, and they are all present.
    assert "COLLECTED VIDEOS" in prompt
    for video in _fixture_videos():
        assert video.video_id in prompt


def test_narrative_prompt_toggles_control_null_sections():
    vids = _fixture_videos()
    on = build_narrative_prompt(_request(analyze_titles=True, analyze_scripts=True), vids)
    assert "Titles Analytic: ON" in on and "Script analytics: ON" in on
    off = build_narrative_prompt(_request(analyze_titles=False, analyze_scripts=False), vids)
    assert "Titles Analytic: OFF" in off and "Script analytics: OFF" in off
    assert "Set title_analysis to null" in off
    assert "Set script_analysis to null" in off


def test_repair_prompt_is_error_correcting():
    rp = build_repair_prompt("orig", {"schema_version": "1.0"}, "missing field 'summary'")
    assert "REPAIR REQUEST" in rp
    assert "missing field 'summary'" in rp
    assert "MUST NOT invent" in rp  # trust rule re-stated


def test_repair_prompt_restates_the_output_contract():
    """The repair is a fresh invocation: without the contract the agent is asked
    to match a schema it was never shown."""
    rp = build_repair_prompt("orig", {"schema_version": "1.0"}, "bad shape")
    assert "OUTPUT CONTRACT" in rp
    # The nested shapes the agent has to get right, not just the top-level keys.
    for key in ("proof_video_id", "tailored", "thumbnail_concepts"):
        assert key in rp


def test_repair_prompt_echoes_a_whole_agent_result():
    """Truncating the echo strands the only copy of the research the repair has."""
    big = _agent_result_dict()
    big["summary"] = "x" * 8000  # well past the old 2000-char window
    rp = build_repair_prompt("orig", big, "bad shape")
    last_id = _FIXTURE["top_videos"][-1]["video_id"]
    assert last_id in rp, "ids past the echo limit were dropped from the repair"


def test_output_contract_documents_every_nested_shape():
    """Fields the contract names but never describes get invented by the agent."""
    prompt = build_narrative_prompt(_request(), _fixture_videos())
    for key in ("shape", "proof_video_id", "tailored", "title_options", "thumbnail_concepts"):
        assert key in prompt, "%s is emitted but its shape is undocumented" % key


# --------------------------------------------------------------------------- #
# tolerant AgentResult / requested-analysis gap                                #
# --------------------------------------------------------------------------- #
def test_agent_result_accepts_omitted_null_sections():
    """CLIs drop null keys; omitted and null mean the same thing here."""
    payload = _agent_result_dict()
    payload.pop("title_analysis")
    payload.pop("script_analysis")
    result = AgentResult.model_validate(payload)
    assert result.title_analysis is None and result.script_analysis is None


def test_requested_analysis_gap_flags_only_toggled_on_sections():
    result = AgentResult.model_validate(_agent_result_dict(titles=False, scripts=False))

    both_off = _runner._requested_analysis_gap(
        _request(analyze_titles=False, analyze_scripts=False), result
    )
    assert both_off == "", "a section the user did not ask for is not a gap"

    titles_on = _runner._requested_analysis_gap(
        _request(analyze_titles=True, analyze_scripts=False), result
    )
    assert "title_analysis" in titles_on and "script_analysis" not in titles_on

    both_on = _runner._requested_analysis_gap(
        _request(analyze_titles=True, analyze_scripts=True), result
    )
    assert "title_analysis" in both_on and "script_analysis" in both_on


def test_requested_analysis_gap_silent_when_sections_present():
    result = AgentResult.model_validate(_agent_result_dict())
    assert _runner._requested_analysis_gap(_request(), result) == ""


# --------------------------------------------------------------------------- #
# stream parsing / extraction                                                #
# --------------------------------------------------------------------------- #
def test_find_last_json_object_ignores_prose_and_braces_in_strings():
    text = 'noise {"a": 1} more {"b": "has } brace", "c": 2} tail'
    blob = find_last_json_object(text)
    assert json.loads(blob) == {"b": "has } brace", "c": 2}


def test_collector_extracts_from_streamjson_result_event():
    agent = _agent_result_dict()
    collector = StreamCollector()
    details = [collector.feed(line) for line in _streamjson_lines(agent)]
    assert "Running research tools" in details  # tool_use surfaced as progress
    assert collector.extract()["topic_title"] == agent["topic_title"]


def test_collector_extracts_from_fenced_plain_text():
    agent = _agent_result_dict()
    collector = StreamCollector()
    collector.feed("Here is the result:")
    collector.feed("```json")
    collector.feed(json.dumps(agent))
    collector.feed("```")
    assert collector.extract()["summary"] == agent["summary"]


# --------------------------------------------------------------------------- #
# run loop (direct, injected fakes)                                          #
# --------------------------------------------------------------------------- #
def test_run_loop_happy_path_reaches_done_with_result():
    req = _request()
    run_id = run_store.create_run(req)
    adapter = FakeAdapter([_streamjson_lines(_agent_result_dict())])
    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=_fake_pipeline(),
        verifier=_fake_verifier,
    )
    phases = _phases(run_id)
    # Ordered loader timeline ending in the terminal done.
    for expected in ["queued", "expanding", "searching", "enriching", "scoring", "analyzing", "verifying", "done"]:
        assert expected in phases, "missing phase %s in %s" % (expected, phases)
    assert phases[-1] == "done"
    assert run_store.get_status(run_id)["status"] == "done"
    result = run_store.get_result(run_id)
    assert isinstance(result, ResearchResult)
    # expansion (1) + narrative (2) — the same two steps every adapter runs.
    assert adapter.calls == 2
    assert "COLLECTED VIDEOS" in adapter.narrative_prompts[0]


def test_invalid_agent_output_triggers_one_repair_then_succeeds():
    req = _request()
    run_id = run_store.create_run(req)
    invalid = {"schema_version": "1.0", "topic_title": "x"}  # missing required fields
    adapter = FakeAdapter(
        [_streamjson_lines(invalid), _streamjson_lines(_agent_result_dict())]
    )
    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=_fake_pipeline(),
        verifier=_fake_verifier,
    )
    assert adapter.calls == 3  # expansion + first attempt + one repair
    assert "REPAIR REQUEST" in adapter.narrative_prompts[1]
    assert run_store.get_status(run_id)["status"] == "done"


def test_invalid_output_twice_yields_invalid_output_error():
    req = _request()
    run_id = run_store.create_run(req)
    invalid = {"schema_version": "1.0", "topic_title": "x"}
    adapter = FakeAdapter([_streamjson_lines(invalid), _streamjson_lines(invalid)])
    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=_fake_pipeline(),
        verifier=_fake_verifier,
    )
    assert adapter.calls == 3  # expansion + two failed narrative attempts
    assert _phases(run_id)[-1] == "error"
    assert _last_error(run_id).code == "invalid_output"


def test_no_json_in_output_triggers_repair_and_errors():
    req = _request()
    run_id = run_store.create_run(req)
    prose = ["I could not find anything useful.", "Sorry!"]
    adapter = FakeAdapter([prose, prose])
    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=_fake_pipeline(),
        verifier=_fake_verifier,
    )
    assert adapter.calls == 3  # expansion + two failed narrative attempts
    assert _last_error(run_id).code == "invalid_output"


def test_empty_pipeline_yields_no_results_error():
    req = _request()
    run_id = run_store.create_run(req)
    adapter = FakeAdapter([_streamjson_lines(_agent_result_dict())])
    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=_fake_pipeline(videos=[], meta={"counts": {"found": 0}}),
        verifier=_fake_verifier,
    )
    assert _phases(run_id)[-1] == "error"
    assert _last_error(run_id).code == "no_results"


def test_missing_cli_yields_cli_missing_error():
    req = _request()
    run_id = run_store.create_run(req)

    def missing_factory(_id):
        raise FileNotFoundError("claude: command not found")

    run_research_job(
        run_id,
        req,
        adapter_factory=missing_factory,
        pipeline_runner=_fake_pipeline(),
        verifier=_fake_verifier,
    )
    assert _last_error(run_id).code == "cli_missing"


def test_quota_error_from_pipeline_maps_to_quota_exceeded():
    req = _request()
    run_id = run_store.create_run(req)

    def quota_pipeline(request, keywords=None):
        raise RuntimeError("HTTP 403: quota exceeded for youtube.data")

    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: FakeAdapter([[]]),
        pipeline_runner=quota_pipeline,
        verifier=_fake_verifier,
    )
    assert _last_error(run_id).code == "quota_exceeded"


def test_pipeline_dict_rows_are_coerced_to_video_models():
    # B3's run_pipeline returns Video-shaped *dicts*; B5's assemble_and_verify
    # needs Video *models*. B4 (the glue) must coerce before the verifier.
    req = _request()
    run_id = run_store.create_run(req)
    dict_rows = list(_FIXTURE["top_videos"])  # plain dicts, like real B3 output
    seen_types = {}

    def checking_verifier(request, agent_result, videos, meta):
        seen_types["all_models"] = bool(videos) and all(isinstance(v, Video) for v in videos)
        return _fake_verifier(request, agent_result, videos, meta)

    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: FakeAdapter([_streamjson_lines(_agent_result_dict())]),
        pipeline_runner=lambda r, keywords=None: (dict_rows, dict(_FIXTURE["meta"])),
        verifier=checking_verifier,
    )
    assert seen_types.get("all_models") is True
    assert run_store.get_status(run_id)["status"] == "done"


def test_agentic_adapter_curates_from_the_pipeline_not_its_own_search():
    """The regression this file exists for.

    An agentic CLI used to be told to run the research scripts itself while the
    pipeline searched in parallel; B5 then joined two unrelated result sets and
    routinely kept nothing, rendering "Top 0 Highest-Performed Videos" over a run
    that had really collected videos. Now the CLI expands keywords, the pipeline
    searches THOSE, and the CLI curates the ids it was handed.
    """
    req = _request()
    run_id = run_store.create_run(req)
    seen = {}

    def pipeline(request, keywords=None):
        seen["keywords"] = keywords
        return _fixture_videos(), dict(_FIXTURE["meta"])

    adapter = FakeAdapter(
        [_streamjson_lines(_agent_result_dict())],
        keyword_lines=_streamjson_text('["ai agents", "build an ai agent"]'),
    )
    run_research_job(
        run_id, req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=pipeline,
        verifier=_fake_verifier,
    )
    # The CLI's keywords drove the deterministic search — not the raw query alone.
    assert seen["keywords"] == ["ai agents", "build an ai agent"]
    # And it curated from the collected set rather than being sent off to research.
    narrative = adapter.narrative_prompts[0]
    assert "COLLECTED VIDEOS" in narrative
    assert "longform_research.py" not in narrative
    assert run_store.get_status(run_id)["status"] == "done"


def test_stream_receives_the_requested_model_and_the_repo_root():
    """The CLI ran on whatever model it defaulted to, from the server's own cwd,
    because neither was ever passed."""
    req = _request(model={"adapter": "claude-code", "model": "claude-opus-5"})
    run_id = run_store.create_run(req)
    adapter = FakeAdapter([_streamjson_lines(_agent_result_dict())])
    run_research_job(
        run_id, req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=_fake_pipeline(),
        verifier=_fake_verifier,
    )
    assert adapter.stream_kwargs, "stream was never called"
    for kwargs in adapter.stream_kwargs:
        assert kwargs["model"] == "claude-opus-5"
        assert kwargs["cwd"] == str(_REPO_ROOT)


def test_run_id_is_stamped_into_meta_for_the_verifier():
    """B5 mints a random run_id when meta has none, which keyed the history row
    and the stored result to different ids — History could never reopen a run."""
    req = _request()
    run_id = run_store.create_run(req)
    seen = {}

    def checking_verifier(request, agent_result, videos, meta):
        seen["run_id"] = meta.get("run_id") if isinstance(meta, dict) else None
        return _fake_verifier(request, agent_result, videos, meta)

    run_research_job(
        run_id, req,
        adapter_factory=lambda _id: FakeAdapter([_streamjson_lines(_agent_result_dict())]),
        pipeline_runner=_fake_pipeline(meta={"counts": {"found": 3}}),
        verifier=checking_verifier,
    )
    assert seen["run_id"] == run_id


# --------------------------------------------------------------------------- #
# direct (non-agentic) adapter path — same two LLM steps, plain-text stream     #
# --------------------------------------------------------------------------- #
class FakeDirectAdapter:
    """A non-agentic adapter (``agentic=False``): call 1 is keyword expansion
    (yields a JSON array), calls 2+ are the AgentResult narrative (yields the
    JSON as plain text lines, like the real Messages stream).

    Deliberately keeps the bare ``stream(prompt)`` signature — the run loop passes
    ``model``/``cwd`` now, and adapters that don't take them must still work.
    """

    agentic = False

    def __init__(self, keyword_lines, narrative_transcripts):
        self._keyword_lines = keyword_lines
        self._narrative = list(narrative_transcripts)
        self.calls = 0
        self.prompts = []

    def stream(self, prompt):
        self.prompts.append(prompt)
        self.calls += 1
        if self.calls == 1:
            lines = self._keyword_lines
        else:
            idx = min(self.calls - 2, len(self._narrative) - 1)
            lines = self._narrative[idx]

        def gen():
            for line in lines:
                yield line

        return gen()


def _fixture_videos():
    return [Video.model_validate(v) for v in _FIXTURE["top_videos"]]


def test_direct_adapter_two_step_flow_reaches_done():
    req = _request(model={"adapter": "anthropic-api", "model": "default"})
    run_id = run_store.create_run(req)
    seen = {}

    def pipeline(request, keywords=None):
        seen["keywords"] = keywords
        return _fixture_videos(), dict(_FIXTURE["meta"])

    adapter = FakeDirectAdapter(
        keyword_lines=['["ai agents", "agent orchestration", "multi agent systems"]'],
        narrative_transcripts=[[json.dumps(_agent_result_dict())]],
    )
    run_research_job(
        run_id, req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=pipeline,
        verifier=_fake_verifier,
    )
    # Step 1 keywords were parsed and fed to the deterministic pipeline.
    assert seen["keywords"] == ["ai agents", "agent orchestration", "multi agent systems"]
    # Two LLM calls: expansion + narrative (no repair needed).
    assert adapter.calls == 2
    # The narrative prompt embedded the collected videos (direct, not "run scripts").
    assert "COLLECTED VIDEOS" in adapter.prompts[1]
    assert run_store.get_status(run_id)["status"] == "done"
    assert _phases(run_id)[-1] == "done"


def test_direct_adapter_bad_expansion_falls_back_to_raw_query():
    req = _request(model={"adapter": "anthropic-api", "model": "default"})
    run_id = run_store.create_run(req)
    seen = {}

    def pipeline(request, keywords=None):
        seen["keywords"] = keywords
        return _fixture_videos(), dict(_FIXTURE["meta"])

    adapter = FakeDirectAdapter(
        keyword_lines=["Sorry, I can't help with that."],  # no JSON array
        narrative_transcripts=[[json.dumps(_agent_result_dict())]],
    )
    run_research_job(
        run_id, req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=pipeline,
        verifier=_fake_verifier,
    )
    # Unparseable expansion → pipeline falls back to the raw query (keywords=None).
    assert seen["keywords"] is None
    assert run_store.get_status(run_id)["status"] == "done"


def test_direct_adapter_trust_guard_drops_fabricated_id():
    """The HARD TRUST RULE holds on the direct path: a fabricated video_id the
    model emits is dropped by the REAL assemble_and_verify — every rendered id
    resolves to a collected pipeline video."""
    from app.verify import assemble_and_verify

    req = _request(model={"adapter": "anthropic-api", "model": "default"})
    run_id = run_store.create_run(req)
    videos = _fixture_videos()
    real_ids = [v.video_id for v in videos]

    # AgentResult that references a fabricated id at rank 1 (would render first if
    # the guard failed), then the real ids.
    agent = _agent_result_dict()
    agent["top_video_ids"] = [{"video_id": "FAKE1234567", "rank": 1}] + [
        {"video_id": vid, "rank": i + 2} for i, vid in enumerate(real_ids)
    ]

    def real_verifier(request, agent_result, vids, meta):
        # Real join + drop; skip network link-verify and history writes.
        return assemble_and_verify(
            request, agent_result, vids, meta, verify_links=False, write_history=False
        )

    run_research_job(
        run_id, req,
        adapter_factory=lambda _id: FakeDirectAdapter(
            keyword_lines=['["a", "b"]'],
            narrative_transcripts=[[json.dumps(agent)]],
        ),
        pipeline_runner=lambda request, keywords=None: (videos, dict(_FIXTURE["meta"])),
        verifier=real_verifier,
    )

    result = run_store.get_result(run_id)
    assert isinstance(result, ResearchResult)
    rendered = [v.video_id for v in result.top_videos]
    assert "FAKE1234567" not in rendered  # fabricated id dropped, not rendered
    assert all(vid in real_ids for vid in rendered)  # every rendered id is real


def test_direct_adapter_narrative_repair_then_succeeds():
    req = _request(model={"adapter": "anthropic-api", "model": "default"})
    run_id = run_store.create_run(req)
    invalid = {"schema_version": "1.0", "topic_title": "x"}  # missing fields
    adapter = FakeDirectAdapter(
        keyword_lines=['["a", "b"]'],
        narrative_transcripts=[[json.dumps(invalid)], [json.dumps(_agent_result_dict())]],
    )
    run_research_job(
        run_id, req,
        adapter_factory=lambda _id: adapter,
        pipeline_runner=lambda request, keywords=None: (_fixture_videos(), dict(_FIXTURE["meta"])),
        verifier=_fake_verifier,
    )
    # expand (1) + narrative invalid (2) + one repair (3).
    assert adapter.calls == 3
    assert "REPAIR REQUEST" in adapter.prompts[2]
    assert run_store.get_status(run_id)["status"] == "done"


def test_cancel_midrun_yields_cancelled_terminal():
    req = _request()
    run_id = run_store.create_run(req)

    def cancelling_pipeline(request, keywords=None):
        run_store.cancel_run(run_id)  # flip status mid-run
        return [Video.model_validate(v) for v in _FIXTURE["top_videos"]], dict(_FIXTURE["meta"])

    run_research_job(
        run_id,
        req,
        adapter_factory=lambda _id: FakeAdapter([_streamjson_lines(_agent_result_dict())]),
        pipeline_runner=cancelling_pipeline,
        verifier=_fake_verifier,
    )
    assert _phases(run_id)[-1] == "error"
    assert _last_error(run_id).code == "cancelled"
    assert run_store.get_status(run_id)["status"] == "cancelled"


# --------------------------------------------------------------------------- #
# HTTP + SSE (end-to-end, monkeypatched lazy seams)                          #
# --------------------------------------------------------------------------- #
def _collect_sse(run_id, timeout=8.0):
    events = []
    with client.stream("GET", "/api/research/%s/events" % run_id) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            events.append(json.loads(line[len("data:") :].strip()))
            if events[-1].get("phase") in ("done", "error"):
                break
    return events


def test_start_returns_run_id_fast_and_sse_streams_to_done(monkeypatch):
    adapter = FakeAdapter([_streamjson_lines(_agent_result_dict())])
    monkeypatch.setattr(_runner, "_default_adapter_factory", lambda _id: adapter)
    monkeypatch.setattr(_runner, "_default_pipeline_runner", _fake_pipeline())
    monkeypatch.setattr(_runner, "_default_verifier", _fake_verifier)

    resp = client.post("/api/research", json=_request().model_dump())
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert run_id.startswith("r_")

    events = _collect_sse(run_id)
    phases = [e["phase"] for e in events]
    assert phases[-1] == "done"
    assert "searching" in phases and "analyzing" in phases and "verifying" in phases
    assert _wait_until(lambda: run_store.get_status(run_id)["status"] == "done")
    assert run_store.get_result(run_id) is not None


def test_post_research_rejects_invalid_body():
    assert client.post("/api/research", json={}).status_code == 422
    assert client.post("/api/research", json={"query": ""}).status_code == 422


def test_sse_replays_already_recorded_events_on_connect():
    # Simulate a run that progressed before the client connected (page refresh).
    run_id = run_store.create_run(_request())
    run_store.append_event(run_id, make_event(run_id, "queued"))
    run_store.append_event(run_id, make_event(run_id, "searching", counts={"found": 412}))
    run_store.append_event(run_id, make_event(run_id, "done"))

    events = _collect_sse(run_id)
    phases = [e["phase"] for e in events]
    assert phases == ["queued", "searching", "done"]
    assert events[1]["counts"] == {"found": 412}


def test_events_unknown_run_returns_404():
    assert client.get("/api/research/r_nope/events").status_code == 404


def test_cancel_unknown_run_returns_404():
    assert client.post("/api/research/r_nope/cancel").status_code == 404


def test_cancel_endpoint_ends_run_with_cancelled(monkeypatch):
    # Answer the keyword step immediately, then crawl, so the run parks in
    # "analyzing" and cancel lands mid-flight.
    class SlowAdapter:
        def __init__(self):
            self.calls = 0

        def stream(self, prompt, *, model=None, cwd=None):
            self.calls += 1
            if self.calls == 1:
                return iter(_streamjson_text('["ai agents"]'))

            def crawl():
                for i in range(500):
                    yield json.dumps(
                        {"type": "assistant", "message": {"content": [{"type": "text", "text": "step %d" % i}]}}
                    )
                    time.sleep(0.01)

            return crawl()

    monkeypatch.setattr(_runner, "_default_adapter_factory", lambda _id: SlowAdapter())
    monkeypatch.setattr(_runner, "_default_pipeline_runner", _fake_pipeline())
    monkeypatch.setattr(_runner, "_default_verifier", _fake_verifier)

    run_id = client.post("/api/research", json=_request().model_dump()).json()["run_id"]
    # Wait until the worker is streaming analysis, then cancel.
    assert _wait_until(lambda: "analyzing" in _phases(run_id))
    resp = client.post("/api/research/%s/cancel" % run_id)
    assert resp.status_code == 200
    assert resp.json()["cancelled"] is True

    assert _wait_until(lambda: run_store.get_status(run_id)["status"] == "cancelled")
    assert _wait_until(lambda: _phases(run_id)[-1] == "error")
    assert _last_error(run_id).code == "cancelled"
