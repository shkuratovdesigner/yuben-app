"""No-quota smoke test: one model through both LLM steps of a real run.

    python yuben.py smoke --adapter openai-api --model gpt-4o
    (or, from backend/:  python -m app.smoke --adapter openai-api --model gpt-4o)

Runs the real run loop (``run_research_job``) with the real adapter: the model
check, keyword expansion, the narrative and its repair retry, parsing and
validation. Only the two YouTube-facing seams are replaced. The pipeline
returns the bundled demo videos (``contracts/fixtures/research-result.*.json``,
real ids, representative counts), and link verification is skipped. So the run
spends no YouTube quota and makes no request to youtube.com; the only network
traffic is to the model's own provider. Nothing is written to History.

Reliability plan Phase 5, item 3: lets anyone test a model in about a minute.
Exit code 0 when both steps succeed, 1 when either fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

# Run as ``python -m app.smoke`` the repo root (for ``contracts``) is not on
# sys.path yet; importing _paths puts it there, as app.main does for the server.
from app.pipeline import _paths  # noqa: F401
from contracts.python.models import ProgressEvent, ResearchRequest, Video
from app.orchestrator import runner
from app.store import result_store, run_store

_FIXTURES = Path(__file__).resolve().parents[2] / "contracts" / "fixtures"

#: Narrative detail lines that mean the first answer did not validate.
_REPAIR_DETAIL = "Agent output invalid"


def bundled(fmt: str) -> Dict[str, Any]:
    """The bundled demo result for ``fmt``: its request, videos and meta."""
    path = _FIXTURES / ("research-result.%s.json" % fmt)
    return json.loads(path.read_text(encoding="utf-8"))


def smoke_request(adapter: str, model: Optional[str], fmt: str = "longform",
                  query: Optional[str] = None) -> ResearchRequest:
    """A request shaped like the bundled run, for ``adapter``/``model``.

    Script analysis is off: the bundled set has no transcripts, and the
    narrative step is what is being tested.
    """
    data = dict(bundled(fmt)["request"])
    data.update(
        query=query or data["query"],
        analyze_titles=True,
        analyze_scripts=False,
        model={"adapter": adapter, "model": model or "default"},
    )
    return ResearchRequest.model_validate(data)


def bundled_pipeline(fmt: str, seen: Dict[str, Any]) -> Callable[..., Tuple[List[Video], Dict[str, Any]]]:
    """A pipeline runner that returns the bundled videos instead of searching."""
    data = bundled(fmt)

    def pipeline(request: ResearchRequest, *, keywords: Optional[List[str]] = None):
        seen["keywords"] = keywords
        meta = dict(data["meta"])
        meta["keywords"] = list(keywords or [request.query])
        return [Video.model_validate(v) for v in data["top_videos"]], meta

    return pipeline


def offline_verifier(request: ResearchRequest, agent_result: Any, videos: List[Any], meta: Any) -> Any:
    """Join the answer against the bundled videos without checking links."""
    from app.verify import assemble_and_verify

    return assemble_and_verify(
        request, agent_result, videos, meta, verify_links=False, write_history=False
    )


@contextmanager
def _results_not_saved() -> Iterator[None]:
    """Keep the smoke result out of the results table that History reads."""
    original = result_store.save_result
    result_store.save_result = lambda *_a, **_k: None  # type: ignore[assignment]
    try:
        yield
    finally:
        result_store.save_result = original  # type: ignore[assignment]


def _event_dict(event: Any) -> Dict[str, Any]:
    if isinstance(event, ProgressEvent):
        return event.model_dump()
    return dict(event)


def run_smoke(
    adapter: str,
    model: Optional[str] = None,
    *,
    fmt: str = "longform",
    query: Optional[str] = None,
    out: Callable[[str], None] = print,
    adapter_factory: Optional[Callable[[str], Any]] = None,
    preflight: Optional[Callable[[Any, Optional[str]], Optional[str]]] = None,
) -> int:
    """Run the smoke test and print progress. Returns the process exit code."""
    request = smoke_request(adapter, model, fmt, query)
    run_id = run_store.create_run(request)
    seen: Dict[str, Any] = {}
    started = time.monotonic()
    out("Smoke test: %s / %s, %s, bundled videos (no YouTube quota)"
        % (adapter, model or "default", fmt))

    job = threading.Thread(
        target=runner.run_research_job,
        args=(run_id, request),
        kwargs=dict(
            adapter_factory=adapter_factory,
            pipeline_runner=bundled_pipeline(fmt, seen),
            verifier=offline_verifier,
            preflight=preflight,
        ),
        daemon=True,
    )
    printed = 0
    events: List[Dict[str, Any]] = []
    with _results_not_saved():
        job.start()
        while True:
            alive = job.is_alive()
            batch = run_store.get_events(run_id)
            for event in batch[printed:]:
                data = _event_dict(event)
                events.append(data)
                line = "  %5.1fs  %-10s" % (time.monotonic() - started, data.get("phase"))
                if data.get("detail"):
                    line += "  " + str(data["detail"])
                out(line)
            printed = len(batch)
            if not alive:
                break
            time.sleep(0.2)

    return _report(run_id, events, seen, time.monotonic() - started, out)


def _report(run_id: str, events: List[Dict[str, Any]], seen: Dict[str, Any],
            elapsed: float, out: Callable[[str], None]) -> int:
    terminal = events[-1] if events else {}
    keywords = seen.get("keywords")
    repaired = any(_REPAIR_DETAIL in str(e.get("detail") or "") for e in events)
    failures: List[str] = []

    error = terminal.get("error") or {}
    out("")
    if "keywords" not in seen:
        # Stopped before the model ran: unknown adapter, missing key, failed check.
        out("Setup:      FAILED (%s) %s" % (error.get("code", "no result"), error.get("message", "")))
        out("Time:       %.1fs" % elapsed)
        out("Result:     FAIL (setup)")
        return 1
    if keywords:
        out("Expansion:  ok, %d search terms" % len(keywords))
    else:
        out("Expansion:  FAILED, the run fell back to the topic itself")
        failures.append("expansion")

    if terminal.get("phase") == "done":
        result = run_store.get_result(run_id)
        top = len(getattr(result, "top_videos", []) or [])
        watch = len(getattr(result, "watch_list", []) or [])
        note = " after one repair" if repaired else ""
        out("Narrative:  ok%s, %d ranked videos, %d on the watch list" % (note, top, watch))
    else:
        out("Narrative:  FAILED (%s) %s" % (error.get("code", "no result"), error.get("message", "")))
        failures.append("narrative")

    out("Time:       %.1fs" % elapsed)
    if failures:
        out("Result:     FAIL (%s)" % ", ".join(failures))
        return 1
    out("Result:     PASS")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.smoke", description=__doc__.split("\n")[0])
    parser.add_argument("--adapter", required=True, help="adapter id, e.g. openai-api or claude-code")
    parser.add_argument("--model", help="model id; the adapter's default when omitted")
    parser.add_argument("--format", dest="fmt", choices=("longform", "shorts"), default="longform")
    parser.add_argument("--query", help="topic to expand; the bundled run's topic when omitted")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")
    return run_smoke(args.adapter, args.model, fmt=args.fmt, query=args.query,
                     out=lambda line: print(line, flush=True))


if __name__ == "__main__":
    sys.exit(main())
