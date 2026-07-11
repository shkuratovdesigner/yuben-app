"""B3 pipeline verification — no network, no YouTube quota.

Covers:
  * import-plumbing quirk fixed: `import app.pipeline` makes
    `import youtube_research.youtube_api` / `.config` resolve to the repo-root
    scripts (no sibling repo, no on-disk symlink), and config.py is repo-relative.
  * normalizer parity: our live normalizer matches contracts/build_fixtures.py
    row-for-row on the real data/*.json, and every row validates as `Video`.
  * filter -> param mapping + outperformance filter/sort.
  * run_pipeline end-to-end with the Gen-2 script mocked (deterministic dict in,
    contract-valid Video[] + ResultMeta-shaped meta out); missing-key path.
  * test_youtube_key: missing key, success, and 403/quota — googleapiclient mocked.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from contracts.python.models import ResultMeta, Video

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "data"

# The raw pipeline outputs these parity tests replay are local research
# artifacts and are not bundled in the repo. Without a data/ dir the
# data-driven tests skip; everything else runs from committed fixtures.
requires_raw_data = pytest.mark.skipif(
    not DATA.is_dir(),
    reason="raw data/*.json not bundled; produced by live pipeline runs",
)


def _load(name):
    return json.loads((DATA / name).read_text())


# ---------------------------------------------------------------------------
# 1. Import-plumbing quirk fixed
# ---------------------------------------------------------------------------
def test_import_plumbing_resolves_youtube_research(monkeypatch):
    # A dummy key keeps config.py quiet; it must NOT be required for the import.
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-plumbing")

    import app.pipeline  # noqa: F401  (side effect: installs the namespace shim)
    import youtube_research.config as cfg
    import youtube_research.youtube_api as yta

    assert hasattr(yta, "build_service")
    assert hasattr(yta, "search_videos")
    assert hasattr(yta, "get_video_details")

    # Repo-relative now — the hardcoded /Users/.../Business Automation path is gone.
    assert Path(cfg.PROJECT_ROOT).resolve() == REPO_ROOT
    assert "Business Automation" not in str(cfg.PROJECT_ROOT)


def test_transcript_module_resolves(monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-plumbing")
    import app.pipeline  # noqa: F401
    import youtube_research.transcript as tr

    assert hasattr(tr, "get_transcripts_batch")


# ---------------------------------------------------------------------------
# 2. Normalizer parity with contracts/build_fixtures.py
# ---------------------------------------------------------------------------
def _build_fixtures_module():
    import importlib

    return importlib.import_module("contracts.build_fixtures")


@pytest.mark.parametrize(
    "filename,keep_multiplier",
    [("property_raw.json", True), ("airbnb_promo_raw.json", False)],
)
@requires_raw_data
def test_normalizer_matches_build_fixtures(filename, keep_multiplier):
    from app.pipeline.normalize import normalize_video

    bf = _build_fixtures_module()
    src = _load(filename)
    raw_rows = src.get("videos", [])
    assert raw_rows, f"{filename} has no videos"

    matched = 0
    for raw in raw_rows:
        mine = normalize_video(raw, keep_multiplier=keep_multiplier)
        theirs = bf.normalize_video(raw, keep_multiplier=keep_multiplier)
        assert mine == theirs, f"drift on {raw.get('video_id')}"
        if mine is not None:
            matched += 1
    assert matched > 0


@pytest.mark.parametrize(
    "filename,keep_multiplier",
    [("property_raw.json", True), ("airbnb_promo_raw.json", False)],
)
@requires_raw_data
def test_normalized_rows_are_valid_videos_and_derive_fields(filename, keep_multiplier):
    from app.pipeline.normalize import normalize_videos

    src = _load(filename)
    rows = normalize_videos(src.get("videos", []), keep_multiplier=keep_multiplier)
    assert rows

    # ranked by views desc (matches build_fixtures.load_videos)
    views = [r["view_count"] for r in rows]
    assert views == sorted(views, reverse=True)

    for r in rows:
        Video(**r)  # raises on any contract violation
        assert r["thumbnail_url"] == f"https://i.ytimg.com/vi/{r['video_id']}/hqdefault.jpg"
        assert r["url"] == f"https://www.youtube.com/watch?v={r['video_id']}"
        # eng_per_1k / engagement_flag agree
        if r["like_count"] and r["view_count"]:
            expected = round(r["like_count"] / r["view_count"] * 1000, 2)
            assert r["eng_per_1k"] == expected
        assert r["engagement_flag"] == ("promoted" if r["eng_per_1k"] < 1.5 else "ok")
        # multiplier only kept for longform
        if not keep_multiplier:
            assert r["multiplier"] is None


def test_duration_label_boundaries():
    from app.pipeline.normalize import duration_label

    assert duration_label(0) == "0:00"
    assert duration_label(65) == "1:05"
    assert duration_label(399) == "6:39"
    assert duration_label(3661) == "1:01:01"


# ---------------------------------------------------------------------------
# 3. Filter -> param mapping
# ---------------------------------------------------------------------------
def _request(**overrides):
    base = {
        "schema_version": "1.0",
        "query": "how to promote your airbnb",
        "format": "longform",
        "upload_date": "all",
        "outperformance": "highest",
        "analyze_titles": True,
        "analyze_scripts": True,
        "model": {"adapter": "claude-code", "model": "default"},
        "max_results": 15,
    }
    base.update(overrides)
    return base


def test_map_upload_date_to_days_and_window():
    from app.pipeline.params import map_request_to_params

    cases = {
        "all": ("All time", 36500),
        "24h": ("Last 24 hours", 1),
        "7d": ("Last 7 days", 7),
        "30d": ("Last 30 days", 30),
        "90d": ("Last 90 days", 90),
        "6m": ("Last 6 months", 183),
        "1y": ("Last 12 months", 365),
    }
    for upload_date, (window, days) in cases.items():
        p = map_request_to_params(_request(upload_date=upload_date))
        assert p.window_label == window
        assert p.days == days
        assert p.floor == "1970-01-01T00:00:00Z"


def test_map_format_and_outperformance():
    from app.pipeline.params import map_request_to_params

    lf = map_request_to_params(_request(format="longform", outperformance="highest"))
    assert lf.filter_label == "long-form ≥120s"
    assert lf.vsr_floor is None
    assert "VSR" in lf.ranking_label

    sh = map_request_to_params(_request(format="shorts", outperformance="2x"))
    assert sh.filter_label == "Shorts ≤65s"
    assert sh.vsr_floor == 2.0
    assert "2×" in sh.ranking_label

    any_ = map_request_to_params(_request(outperformance="any"))
    assert any_.vsr_floor is None
    assert any_.ranking_label == "by views; VSR shown"


def test_keywords_fallback_and_injection():
    from app.pipeline.params import map_request_to_params

    p_default = map_request_to_params(_request(query="ai agents"))
    assert p_default.keywords == ["ai agents"]

    p_injected = map_request_to_params(
        _request(query="ai agents"), keywords=["ai agents", "agent orchestration"]
    )
    assert p_injected.keywords == ["ai agents", "agent orchestration"]


# ---------------------------------------------------------------------------
# 4. Outperformance filter/sort
# ---------------------------------------------------------------------------
def _v(video_id, views, vsr):
    return {"video_id": video_id, "view_count": views, "vsr": vsr}


def test_apply_outperformance_threshold_and_sort():
    from app.pipeline.params import apply_outperformance, map_request_to_params

    rows = [
        _v("aaaaaaaaaaa", 1000, 0.5),
        _v("bbbbbbbbbbb", 900, 6.0),
        _v("ccccccccccc", 800, None),  # hidden subs -> unknown VSR
        _v("ddddddddddd", 700, 3.0),
    ]

    # 5x -> keep vsr>=5 only, ranked by views
    p5 = map_request_to_params(_request(outperformance="5x"))
    out5 = apply_outperformance(rows, p5)
    assert [r["video_id"] for r in out5] == ["bbbbbbbbbbb"]

    # 2x -> keep vsr>=2 (drops unknown-VSR row), ranked by views desc
    p2 = map_request_to_params(_request(outperformance="2x"))
    out2 = apply_outperformance(rows, p2)
    assert [r["video_id"] for r in out2] == ["bbbbbbbbbbb", "ddddddddddd"]

    # highest -> no filter, VSR desc, unknown VSR last
    ph = map_request_to_params(_request(outperformance="highest"))
    outh = apply_outperformance(rows, ph)
    assert [r["video_id"] for r in outh] == [
        "bbbbbbbbbbb",
        "ddddddddddd",
        "aaaaaaaaaaa",
        "ccccccccccc",
    ]

    # any -> no filter, views desc
    pa = map_request_to_params(_request(outperformance="any"))
    outa = apply_outperformance(rows, pa)
    assert [r["view_count"] for r in outa] == [1000, 900, 800, 700]


# ---------------------------------------------------------------------------
# 5. run_pipeline end-to-end (Gen-2 script mocked; no network)
# ---------------------------------------------------------------------------
def _install_fake_script(monkeypatch, name, raw_result):
    mod = types.ModuleType(name)

    def run(*args, **kwargs):
        return raw_result

    mod.run = run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, name, mod)


@requires_raw_data
def test_run_pipeline_longform(monkeypatch):
    import app.pipeline as pipeline

    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: "k")
    _install_fake_script(monkeypatch, "longform_research", _load("property_raw.json"))

    request = _request(format="longform", outperformance="highest", analyze_scripts=False)
    videos, meta = pipeline.run_pipeline(request, keywords=["how to promote your airbnb"])

    assert videos
    for v in videos:
        Video(**v)  # every emitted row is contract-valid

    # meta top level == ResultMeta shape (extra=forbid model accepts the subset)
    subset = {k: meta[k] for k in ("window", "filter", "keywords", "ranking", "counts")}
    ResultMeta(**subset)
    assert meta["filter"] == "long-form ≥120s"
    assert meta["window"] == "All time"
    assert meta["counts"]["curated"] == min(len(videos), 15)
    assert "longform" in meta["counts"]
    assert meta["pipeline"]["script"] == "longform_research"
    assert meta["pipeline"]["transcripts"] is None  # analyze_scripts off


@requires_raw_data
def test_run_pipeline_shorts_selects_shorts_script(monkeypatch):
    import app.pipeline as pipeline

    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: "k")
    _install_fake_script(monkeypatch, "shorts_research", _load("airbnb_promo_raw.json"))

    request = _request(format="shorts", outperformance="highest", analyze_scripts=False)
    videos, meta = pipeline.run_pipeline(request, keywords=["aesthetic airbnb tour"])

    assert videos
    assert meta["filter"] == "Shorts ≤65s"
    assert "shorts" in meta["counts"]
    assert meta["pipeline"]["script"] == "shorts_research"
    # shorts never carry a multiplier
    assert all(v["multiplier"] is None for v in videos)


def test_run_pipeline_missing_key_raises(monkeypatch):
    import app.pipeline as pipeline

    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: None)
    with pytest.raises(pipeline.PipelineError) as exc:
        pipeline.run_pipeline(_request(), keywords=["x"])
    assert exc.value.code == "quota_exceeded"


@requires_raw_data
def test_run_pipeline_fetches_transcripts_when_enabled(monkeypatch):
    import app.pipeline as pipeline

    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: "k")
    _install_fake_script(monkeypatch, "longform_research", _load("property_raw.json"))

    captured = {}

    def fake_batch(video_ids):
        captured["ids"] = list(video_ids)
        return {vid: f"transcript for {vid}" for vid in video_ids}

    # runner imports youtube_research.transcript.get_transcripts_batch lazily
    fake_tr = types.ModuleType("youtube_research.transcript")
    fake_tr.get_transcripts_batch = fake_batch  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "youtube_research.transcript", fake_tr)

    request = _request(format="longform", analyze_scripts=True, max_results=3)
    videos, meta = pipeline.run_pipeline(request, keywords=["airbnb"])

    tr = meta["pipeline"]["transcripts"]
    assert tr is not None
    assert len(captured["ids"]) == min(3, len(videos))
    assert all(v.startswith("transcript for ") for v in tr.values())


# ---------------------------------------------------------------------------
# 6. test_youtube_key (googleapiclient mocked)
# ---------------------------------------------------------------------------
def test_key_test_missing_key(monkeypatch):
    from app.pipeline import test_youtube_key

    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: None)
    out = test_youtube_key()
    assert out["ok"] is False
    assert "No YouTube API key" in out["message"]


class _FakeExec:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._result


class _FakeVideos:
    def __init__(self, exec_obj):
        self._exec = exec_obj

    def list(self, **kwargs):
        return self._exec


class _FakeService:
    def __init__(self, exec_obj):
        self._exec = exec_obj

    def videos(self):
        return _FakeVideos(self._exec)


def _patch_build(monkeypatch, exec_obj):
    monkeypatch.setattr(
        "googleapiclient.discovery.build",
        lambda *a, **k: _FakeService(exec_obj),
    )


def test_key_test_success(monkeypatch):
    from app.pipeline import test_youtube_key

    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: "good-key")
    _patch_build(monkeypatch, _FakeExec(result={"items": [{"id": "dQw4w9WgXcQ"}]}))
    out = test_youtube_key()
    assert out["ok"] is True
    assert "valid" in out["message"].lower()


def _make_http_error(status, reason):
    from googleapiclient.errors import HttpError

    class _Resp:
        def __init__(self, s):
            self.status = s
            self.reason = "error"

    content = json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return HttpError(resp=_Resp(status), content=content)


def test_key_test_quota_exceeded(monkeypatch):
    from app.pipeline import test_youtube_key

    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: "k")
    _patch_build(monkeypatch, _FakeExec(error=_make_http_error(403, "quotaExceeded")))
    out = test_youtube_key()
    assert out["ok"] is False
    assert "quota" in out["message"].lower()


def test_key_test_forbidden_key(monkeypatch):
    from app.pipeline import test_youtube_key

    monkeypatch.setattr("app.store.secrets.get_youtube_key", lambda: "k")
    _patch_build(monkeypatch, _FakeExec(error=_make_http_error(403, "forbidden")))
    out = test_youtube_key()
    assert out["ok"] is False
    assert "403" in out["message"]
