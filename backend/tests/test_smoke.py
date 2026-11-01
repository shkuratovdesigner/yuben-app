"""The no-quota smoke command (app/smoke.py), reliability plan Phase 5 item 3.

Every test here runs with sockets disabled: a fake adapter stands in for the
model, and the smoke command's own seams (bundled videos, no link checks) must
not touch the network at all. The launcher side (``yuben.py smoke``) is in
test_launcher.py.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from app import smoke
from app.orchestrator import runner
from app.store import history_store, result_store, run_store

_ROOT = Path(__file__).resolve().parents[2]
_LONGFORM = smoke.bundled("longform")


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("the smoke command opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    run_store.reset()
    runner.reset()
    yield
    run_store.reset()
    runner.reset()


def _answer(data=_LONGFORM) -> str:
    return json.dumps({
        "schema_version": "1.0",
        "topic_title": data["topic_title"],
        "summary": data["summary"],
        "keywords": data["meta"]["keywords"],
        "top_video_ids": [
            {"video_id": v["video_id"], "rank": i + 1} for i, v in enumerate(data["top_videos"])
        ],
        "watch_list": data["watch_list"],
        "title_analysis": data["title_analysis"],
        "script_analysis": None,
    }, indent=2)


class _Model:
    """An API-style adapter: call 1 is expansion, calls 2+ the narrative."""

    agentic = False

    def __init__(self, keywords='["grow a channel", "youtube hooks"]', narratives=None):
        self.keywords = keywords
        self.narratives = list(narratives or [_answer()])
        self.prompts = []
        self.models = []

    def stream(self, prompt, *, model=None, cwd=None):
        self.prompts.append(prompt)
        self.models.append(model)
        if len(self.prompts) == 1:
            text = self.keywords
        else:
            text = self.narratives[min(len(self.prompts) - 2, len(self.narratives) - 1)]
        return iter(text.splitlines())


def _run(model, *, fmt="longform", preflight=lambda _a, _m: None, **kw):
    lines = []
    code = smoke.run_smoke(
        "openai-api", "gpt-4o", fmt=fmt, out=lines.append,
        adapter_factory=lambda _id: model, preflight=preflight, **kw
    )
    return code, "\n".join(lines)


def test_both_steps_pass_on_bundled_videos():
    model = _Model()
    code, out = _run(model)
    assert code == 0, out
    assert "Expansion:  ok, 2 search terms" in out
    assert "Narrative:  ok, " in out and "Result:     PASS" in out
    assert model.models == ["gpt-4o", "gpt-4o"]
    # The narrative saw the bundled videos, not a YouTube search.
    assert _LONGFORM["top_videos"][0]["video_id"] in model.prompts[1]


def test_nothing_reaches_history_or_the_results_table(monkeypatch):
    saved, history = [], []
    monkeypatch.setattr(result_store, "save_result", lambda *a, **k: saved.append(a))
    monkeypatch.setattr(history_store, "add_history", lambda *a, **k: history.append(a))
    code, out = _run(_Model())
    assert code == 0, out
    assert saved == [] and history == []
    # The swap is undone afterwards: the server's own runs still persist.
    result_store.save_result("r_x", {})
    assert saved == [("r_x", {})]


def test_expansion_failure_fails_the_smoke_test_even_though_the_run_continues():
    code, out = _run(_Model(keywords="I cannot help with that."))
    assert code == 1
    assert "Expansion:  FAILED" in out
    assert "Narrative:  ok" in out  # the run itself still completed
    assert "Result:     FAIL (expansion)" in out


def test_a_repaired_narrative_passes_and_says_so():
    model = _Model(narratives=["Here is a summary without any JSON.", _answer()])
    code, out = _run(model)
    assert code == 0, out
    assert "ok after one repair" in out
    assert len(model.prompts) == 3


def test_invalid_narrative_twice_fails():
    code, out = _run(_Model(narratives=['{"not": "a report"}']))
    assert code == 1
    assert "Narrative:  FAILED (invalid_output)" in out


def test_failed_model_check_stops_before_any_model_call():
    model = _Model()
    code, out = _run(model, preflight=lambda _a, _m: "Invalid API key.")
    assert code == 1
    assert "Setup:      FAILED (cli_missing)" in out and "Invalid API key." in out
    assert model.prompts == []


def test_unknown_adapter_is_a_setup_failure():
    lines = []
    code = smoke.run_smoke("no-such-adapter", out=lines.append)
    assert code == 1
    assert "Result:     FAIL (setup)" in lines


def test_shorts_uses_the_bundled_shorts_set():
    shorts = smoke.bundled("shorts")
    model = _Model(narratives=[_answer(shorts)])
    code, out = _run(model, fmt="shorts")
    assert code == 0, out
    assert shorts["top_videos"][0]["video_id"] in model.prompts[1]


def test_request_skips_script_analysis_and_keeps_the_bundled_filters():
    req = smoke.smoke_request("ollama", None, query="как набрать подписчиков")
    assert req.model.adapter == "ollama" and req.model.model == "default"
    assert req.query == "как набрать подписчиков"
    assert req.analyze_scripts is False and req.analyze_titles is True
    assert req.max_results == _LONGFORM["request"]["max_results"]


def test_module_runs_as_a_command_from_the_backend_folder():
    """`python -m app.smoke` must find `contracts` without the test conftest."""
    out = subprocess.run(
        [sys.executable, "-m", "app.smoke", "--adapter", "no-such-adapter"],
        cwd=str(_ROOT / "backend"), capture_output=True, encoding="utf-8", timeout=60,
    )
    assert out.returncode == 1, out.stderr
    assert "Result:     FAIL (setup)" in out.stdout
