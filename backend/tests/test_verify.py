"""B5 verification: the HARD TRUST RULE, link status, endpoints, history write.

The centerpiece is ``test_fabricated_ids_are_dropped``: it feeds an ``AgentResult``
that references the real fixture videos PLUS one fabricated 11-char id (in every
place an id can appear) and proves the fabricated id never survives into the
assembled ``ResearchResult`` — while every rendered number equals the
authoritative pipeline value. oEmbed is mocked (stub verifier / httpx
MockTransport) so nothing hits the network.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

from contracts.python.models import (
    AgentResult,
    AgentTopVideoRef,
    HistoryItem,
    HookBreakdown,
    LinkStatus,
    ResearchRequest,
    ResearchResult,
    ScriptAnalysis,
    TitleFormula,
    Video,
    WatchListItem,
)

from app.main import app
from app.store import run_store
from app.verify import OEmbedVerifier, assemble_and_verify, classify_status
from app.verify.assemble import duration_label, eng_per_1k

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"
FAB = "ZZZZZZZZZZZ"  # 11 chars: valid *shape*, but never in the pipeline set.

client = TestClient(app)


# --- stub verifier (no network) ----------------------------------------------
class StubVerifier:
    """A ``LinkVerifier`` returning a mapped status (default ``verified``)."""

    def __init__(self, mapping: Optional[dict] = None, default: Optional[LinkStatus] = "verified"):
        self.mapping = mapping or {}
        self.default = default
        self.calls: List[str] = []

    def verify(self, video_id: str) -> Optional[LinkStatus]:
        self.calls.append(video_id)
        return self.mapping.get(video_id, self.default)


def _fixture() -> ResearchResult:
    return ResearchResult.model_validate(
        json.loads((FIXTURES / "research-result.longform.json").read_text())
    )


def build_case():
    """Fresh (request, agent_result, pipeline_videos, fixture) each call.

    The agent references all 15 real ids (in order) + a fabricated one in
    top_video_ids, watch_list, hook_breakdown, and title_formulas.
    """
    rf = _fixture()
    pipeline_videos: List[Video] = list(rf.top_videos)  # authoritative universe

    top_refs = [
        AgentTopVideoRef(video_id=v.video_id, rank=i + 1)
        for i, v in enumerate(pipeline_videos)
    ]
    top_refs.append(AgentTopVideoRef(video_id=FAB, rank=len(pipeline_videos) + 1))

    watch_list = list(rf.watch_list) + [
        WatchListItem(video_id=FAB, learning_goal="fake", why="fabricated", rank=99)
    ]

    sa = rf.script_analysis
    assert sa is not None
    hooks = list(sa.hook_breakdown) + [
        HookBreakdown(rank=99, title="fake hook", hook="fabricated", video_id=FAB)
    ]
    script_analysis = ScriptAnalysis(
        duration_sweet_spot=sa.duration_sweet_spot,
        structure_patterns=sa.structure_patterns,
        hook_breakdown=hooks,
        what_to_avoid=sa.what_to_avoid,
    )

    assert rf.title_formulas is not None
    title_formulas = list(rf.title_formulas) + [
        TitleFormula(shape="fake", proof_video_id=FAB, tailored="fabricated")
    ]

    agent = AgentResult(
        schema_version="1.0",
        topic_title=rf.topic_title,
        summary=rf.summary,
        keywords=rf.meta.keywords,
        top_video_ids=top_refs,
        watch_list=watch_list,
        title_analysis=rf.title_analysis,
        script_analysis=script_analysis,
        title_formulas=title_formulas,
        game_plan=rf.game_plan,
    )
    return rf.request, agent, pipeline_videos, rf


# --- THE TRUST TEST ----------------------------------------------------------
def test_fabricated_ids_are_dropped():
    request, agent, pipeline_videos, _ = build_case()
    stub = StubVerifier()

    result = assemble_and_verify(
        request, agent, pipeline_videos, {"run_id": "r_trust"},
        verifier=stub, write_history=False,
    )

    top_ids = [v.video_id for v in result.top_videos]
    real_ids = [v.video_id for v in pipeline_videos]

    # 1. Fabricated id dropped from top_videos; the 15 real ones survive in order.
    assert FAB not in top_ids
    assert len(result.top_videos) == 15
    assert top_ids == real_ids  # the agent's rank order is honored

    # 2. Fabricated id dropped from every secondary reference.
    assert FAB not in {w.video_id for w in result.watch_list}
    assert FAB not in {h.video_id for h in result.script_analysis.hook_breakdown}
    assert FAB not in {t.proof_video_id for t in result.title_formulas}

    # 3. Frozen invariant: every watch_list ref resolves to a rendered top_video.
    assert all(w.video_id in set(top_ids) for w in result.watch_list)

    # 4. Link verification ran for the real videos only — never the fabricated id.
    assert FAB not in stub.calls
    assert set(stub.calls) == set(top_ids)

    # 5. The whole thing validates against the ResearchResult contract.
    assert isinstance(result, ResearchResult)
    ResearchResult.model_validate(result.model_dump(mode="json"))


def test_rendered_numbers_equal_authoritative_pipeline_values():
    request, agent, pipeline_videos, _ = build_case()
    result = assemble_and_verify(
        request, agent, pipeline_videos, {"run_id": "r_num"},
        verifier=StubVerifier(), write_history=False,
    )
    src = pipeline_videos[0]
    out = result.top_videos[0]
    # Numbers copied verbatim from the pipeline (the agent supplies none).
    assert out.video_id == src.video_id
    assert out.view_count == src.view_count
    assert out.like_count == src.like_count
    assert out.subscriber_count == src.subscriber_count
    assert out.vsr == src.vsr
    # Derived fields recomputed by the backend, not trusted from input.
    assert out.eng_per_1k == eng_per_1k(src.like_count, src.view_count)
    assert out.duration_label == duration_label(src.duration_seconds)
    assert out.thumbnail_url == f"https://i.ytimg.com/vi/{src.video_id}/hqdefault.jpg"
    assert out.url == f"https://www.youtube.com/watch?v={src.video_id}"


def test_backend_rederives_fields_ignoring_bogus_input():
    """Even if a pipeline video arrives with a poisoned thumbnail / eng value,
    the backend re-derives from the authoritative id + counts."""
    request, agent, pipeline_videos, _ = build_case()
    bogus = pipeline_videos[0].model_copy(
        update={
            "thumbnail_url": "https://evil.example/pwn.jpg",
            "eng_per_1k": 999.0,
            "duration_label": "BOGUS",
        }
    )
    pv = [bogus] + pipeline_videos[1:]
    result = assemble_and_verify(
        request, agent, pv, {"run_id": "r_rederive"},
        verifier=StubVerifier(), write_history=False,
    )
    out0 = result.top_videos[0]
    assert out0.thumbnail_url == f"https://i.ytimg.com/vi/{bogus.video_id}/hqdefault.jpg"
    assert out0.eng_per_1k == eng_per_1k(bogus.like_count, bogus.view_count)
    assert out0.eng_per_1k != 999.0
    assert out0.duration_label != "BOGUS"


def test_link_status_mapping_through_assembler():
    request, agent, pipeline_videos, _ = build_case()
    dead_id = pipeline_videos[2].video_id
    embed_id = pipeline_videos[3].video_id
    stub = StubVerifier(
        mapping={dead_id: "dead", embed_id: "embed_disabled"}, default="verified"
    )
    result = assemble_and_verify(
        request, agent, pipeline_videos, {"run_id": "r_links"},
        verifier=stub, write_history=False,
    )
    by_id = {v.video_id: v for v in result.top_videos}
    assert by_id[dead_id].link_status == "dead"
    assert by_id[embed_id].link_status == "embed_disabled"
    assert by_id[pipeline_videos[0].video_id].link_status == "verified"


def test_inconclusive_verification_keeps_pipeline_status():
    request, agent, pipeline_videos, _ = build_case()
    kept = pipeline_videos[0].model_copy(update={"link_status": "embed_disabled"})
    pv = [kept] + pipeline_videos[1:]
    # verifier returns None (inconclusive) for the first id.
    stub = StubVerifier(mapping={kept.video_id: None}, default="verified")
    result = assemble_and_verify(
        request, agent, pv, {"run_id": "r_incon"},
        verifier=stub, write_history=False,
    )
    by_id = {v.video_id: v for v in result.top_videos}
    assert by_id[kept.video_id].link_status == "embed_disabled"  # not downgraded


def test_analysis_tabs_null_when_toggles_off():
    request, agent, pipeline_videos, _ = build_case()
    req_off = request.model_copy(
        update={"analyze_titles": False, "analyze_scripts": False}
    )
    result = assemble_and_verify(
        req_off, agent, pipeline_videos, {"run_id": "r_off"},
        verifier=StubVerifier(), write_history=False,
    )
    assert result.title_analysis is None
    assert result.script_analysis is None


def test_analysis_tabs_present_when_toggles_on():
    request, agent, pipeline_videos, _ = build_case()
    result = assemble_and_verify(
        request, agent, pipeline_videos, {"run_id": "r_on"},
        verifier=StubVerifier(), write_history=False,
    )
    assert result.title_analysis is not None
    assert result.script_analysis is not None
    # fabricated hook dropped, real hooks kept.
    assert len(result.script_analysis.hook_breakdown) == 4


def test_meta_fallbacks_and_keywords_from_agent():
    request, agent, pipeline_videos, _ = build_case()
    # Pass only run_id → window/filter/ranking/counts fall back; keywords from agent.
    result = assemble_and_verify(
        request, agent, pipeline_videos, {"run_id": "r_meta"},
        verifier=StubVerifier(), write_history=False,
    )
    assert result.meta.window == "All time"          # upload_date "all"
    assert result.meta.filter == "long-form ≥120s"   # format longform
    assert result.meta.counts["curated"] == 15       # true rendered count
    assert result.meta.keywords == agent.keywords


# --- oEmbed classification (mocked transport, no network) ---------------------
@pytest.mark.parametrize(
    "code,expected",
    [(200, "verified"), (401, "embed_disabled"), (403, "embed_disabled"),
     (404, "dead"), (410, "dead"), (500, None), (429, None), (301, None)],
)
def test_classify_status(code, expected):
    assert classify_status(code) == expected


def test_oembed_verifier_maps_status_codes():
    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url.params.get("url", "")
        if "vid404" in url:
            return httpx.Response(404)
        if "vid403" in url:
            return httpx.Response(403)
        if "vid500" in url:
            return httpx.Response(500)
        return httpx.Response(200, json={"title": "ok"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        v = OEmbedVerifier(client=http_client)
        assert v.verify("vid200okxxx") == "verified"
        assert v.verify("vid404gone_") == "dead"
        assert v.verify("vid403embed") == "embed_disabled"
        assert v.verify("vid500errxx") is None  # 5xx inconclusive


def test_oembed_verifier_network_error_is_inconclusive():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with httpx.Client(transport=httpx.MockTransport(boom)) as http_client:
        v = OEmbedVerifier(client=http_client)
        assert v.verify("anything111") is None


def test_oembed_injected_client_is_not_closed_by_verifier():
    http_client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))
    v = OEmbedVerifier(client=http_client)
    v.close()  # verifier does not own an injected client
    assert http_client.is_closed is False
    http_client.close()


# --- history write inside assemble_and_verify --------------------------------
def test_assemble_writes_history(tmp_path, monkeypatch):
    monkeypatch.setenv("YUBEN_DATA_DIR", str(tmp_path))
    from app.store import history_store

    request, agent, pipeline_videos, _ = build_case()
    result = assemble_and_verify(
        request, agent, pipeline_videos, {"run_id": "r_hist_written"},
        verify_links=False, write_history=True,
    )
    items = {h.run_id: h for h in history_store.list_history()}
    assert "r_hist_written" in items
    h = items["r_hist_written"]
    assert h.topic_title == result.topic_title
    assert h.query == request.query
    assert h.format == request.format
    assert h.counts.get("curated") == 15
    assert h.outperformance == request.outperformance


# --- GET /api/research/{run_id} ----------------------------------------------
def test_get_research_result_returns_cached():
    run_store.reset()
    request, _, _, rf = build_case()
    rid = run_store.create_run(request.model_dump())
    run_store.set_result(rid, rf.model_copy(update={"run_id": rid}))

    resp = client.get(f"/api/research/{rid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] == rid
    assert body["schema_version"] == "1.0"
    assert len(body["top_videos"]) == 15


def test_get_research_result_status_while_running():
    run_store.reset()
    rid = run_store.create_run({"query": "x"})
    run_store.set_phase(rid, "searching")
    resp = client.get(f"/api/research/{rid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["phase"] == "searching"


def test_get_research_result_not_found_is_404():
    run_store.reset()
    resp = client.get("/api/research/r_nonexistent")
    assert resp.status_code == 404
    assert resp.json()["detail"]["status"] == "not_found"


# --- /api/history endpoints ---------------------------------------------------
def test_history_endpoints_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("YUBEN_DATA_DIR", str(tmp_path))
    from app.store import history_store

    history_store.add_history(
        HistoryItem(
            run_id="r_api_hist", topic_title="T", query="q", format="longform",
            created_at="2026-07-11T10:00:00Z", counts={"curated": 15},
            outperformance="highest",
        )
    )
    resp = client.get("/api/history")
    assert resp.status_code == 200
    assert "r_api_hist" in {h["run_id"] for h in resp.json()}

    deleted = client.delete("/api/history/r_api_hist")
    assert deleted.status_code == 200
    assert deleted.json()["ok"] is True

    # Second delete → 404 (already gone).
    assert client.delete("/api/history/r_api_hist").status_code == 404
