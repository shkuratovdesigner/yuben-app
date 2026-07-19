"""Cancel really terminates the child, and probes do not inherit the YouTube key.

Both are regressions of the "reports success while doing nothing" kind, so each
test asserts the observable end state (process is dead / variable is absent)
rather than that a function was called.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import pytest

from app.adapters import base


def _run_stream_on_thread(cmd, started: threading.Event, box: dict):
    """Consume `stream_process` on a worker thread, like the orchestrator does."""

    def _worker():
        box["ident"] = threading.get_ident()
        gen = base.stream_process(cmd)
        box["gen"] = gen
        try:
            for line in gen:
                box.setdefault("lines", []).append(line)
                started.set()
        except Exception as exc:  # the CLI being killed is an expected end
            box["exc"] = exc
        finally:
            box["finished"] = True

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread


def test_cancel_terminates_the_child_process() -> None:
    """The bug: closing the generator cross-thread raises, so the CLI lived on."""
    # Prints one line (so we know it is up), then sleeps far longer than the test.
    cmd = [
        sys.executable,
        "-u",
        "-c",
        "print('ready', flush=True); import time; time.sleep(120)",
    ]
    started = threading.Event()
    box: dict = {}
    thread = _run_stream_on_thread(cmd, started, box)

    assert started.wait(timeout=20), "child never produced its first line"

    with base._LIVE_LOCK:
        procs = list(base._LIVE.get(box["ident"], ()))
    assert len(procs) == 1, "the child should be registered against its thread"
    proc = procs[0]
    assert proc.poll() is None, "precondition: child is running"

    # Cancel arrives on a *different* thread — this is the case that used to fail.
    assert threading.get_ident() != box["ident"]
    killed = base.terminate_for_thread(box["ident"])
    assert killed == 1

    thread.join(timeout=20)
    assert box.get("finished"), "worker did not unwind after the child was killed"
    assert proc.poll() is not None, "child survived cancel"


def test_closing_generator_cross_thread_raises() -> None:
    """Documents *why* the handle-based path exists, so nobody reverts it."""
    cmd = [
        sys.executable,
        "-u",
        "-c",
        "print('ready', flush=True); import time; time.sleep(120)",
    ]
    started = threading.Event()
    box: dict = {}
    thread = _run_stream_on_thread(cmd, started, box)
    assert started.wait(timeout=20)

    with pytest.raises(ValueError):
        box["gen"].close()  # "generator already executing"

    base.terminate_for_thread(box["ident"])
    thread.join(timeout=20)


def test_terminate_for_thread_is_safe_when_nothing_is_running() -> None:
    assert base.terminate_for_thread(threading.get_ident()) == 0
    assert base.terminate_for_thread(None) == 0
    assert base.terminate_for_thread(-1) == 0


def test_registry_is_emptied_after_a_normal_run() -> None:
    cmd = [sys.executable, "-u", "-c", "print('one'); print('two')"]
    ident = threading.get_ident()
    lines = list(base.stream_process(cmd))
    assert lines == ["one", "two"]
    with base._LIVE_LOCK:
        assert ident not in base._LIVE, "registry leaked after a clean run"


# ---------------------------------------------------------------------------
# Probe environment
# ---------------------------------------------------------------------------


def test_probe_env_drops_the_youtube_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOUTUBE_API_KEY", "AIzaSyD-should-not-reach-a-cli")
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))
    env = base._probe_env()
    assert "YOUTUBE_API_KEY" not in env
    assert "PATH" in env, "probes still need a working environment"


def test_probe_env_keeps_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """A vendor CLI legitimately reads its own credential — do not break auth."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-example")
    assert base._probe_env().get("ANTHROPIC_API_KEY") == "sk-ant-example"


def test_run_probe_child_cannot_see_the_youtube_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: the value never reaches an actual spawned process."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "AIzaSyD-should-not-reach-a-cli")
    proc = base.run_probe(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('YOUTUBE_API_KEY', '<absent>'))",
        ],
        timeout=30,
    )
    assert proc.stdout.strip() == "<absent>"


def test_stream_process_child_still_sees_the_youtube_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agentic path must keep it: the CLI shells out to the research scripts,
    which read YOUTUBE_API_KEY at import (config.py:60)."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "AIzaSyD-needed-by-the-agent")
    lines = list(
        base.stream_process(
            [
                sys.executable,
                "-u",
                "-c",
                "import os; print(os.environ.get('YOUTUBE_API_KEY', '<absent>'))",
            ]
        )
    )
    assert lines == ["AIzaSyD-needed-by-the-agent"]
