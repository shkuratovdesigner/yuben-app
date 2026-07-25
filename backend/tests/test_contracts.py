"""W0.2 verification: every fixture loads cleanly into the Pydantic models.

This is the Python half of the contract cross-check (the JSON-Schema half runs
in contracts/normalize_reference.py). If a fixture and the models disagree, this
fails — the same guard the backend gets for free when validating agent output.
"""
import json
from pathlib import Path

import pytest

from contracts.python.models import (
    Adapter,
    Config,
    HistoryItem,
    ProgressEvent,
    ResearchResult,
)

FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.mark.parametrize("name", ["research-result.longform.json", "research-result.shorts.json"])
def test_research_result_fixture_loads(name):
    result = ResearchResult.model_validate(_load(name))
    assert result.schema_version == "1.0"
    assert len(result.top_videos) == 15
    # Trust rule: every referenced video_id resolves to a real, collected video.
    ids = {v.video_id for v in result.top_videos}
    for item in result.watch_list:
        assert item.video_id in ids, f"watch_list ref {item.video_id} not in top_videos"


def test_shorts_fixture_has_null_script_analysis():
    # analyze_scripts was off -> the tab must be disabled (null), title present.
    result = ResearchResult.model_validate(_load("research-result.shorts.json"))
    assert result.script_analysis is None
    assert result.title_analysis is not None


def test_config_fixture_loads():
    cfg = Config.model_validate(_load("config.json"))
    assert cfg.youtube_key_present is True


def test_adapters_fixture_loads():
    adapters = [Adapter.model_validate(a) for a in _load("adapters.json")]
    assert any(a.id == "claude-code" and a.installed for a in adapters)


def test_history_fixture_loads():
    # The demo ships a single seeded run (the long-form one) — mock mode adds
    # any further rows at runtime as you research.
    items = [HistoryItem.model_validate(h) for h in _load("history.json")]
    assert len(items) == 1


def test_progress_events_fixture_loads():
    lines = (FIXTURES / "progress-events.jsonl").read_text().strip().splitlines()
    events = [ProgressEvent.model_validate(json.loads(line)) for line in lines]
    assert events[0].phase == "queued"
    assert events[-1].phase == "done"
