"""Run orchestration (B4) — the background job + cancellation registry.

One run = one background thread (:func:`launch`). The thread walks the loader
phases (CONTRACTS §3 / PRD §4.4), calls the deterministic pipeline (B3) for the
authoritative videos, spawns the agent adapter (B2), translates its CLI stream
into ProgressEvents, validates the ``AgentResult`` (with one repair retry), then
hands the agent's *narrative + refs* plus the *authoritative videos* to B5's
``assemble_and_verify`` — which owns the join and drops fabricated IDs. The
orchestrator NEVER merges agent-typed numbers into the result (HARD TRUST RULE).

Threading choice: the pipeline call and the adapter stream are blocking, so the
job runs on a daemon thread; the SSE endpoint (async) tails ``run_store`` events.
The B2/B3/B5 seams are resolved by LAZY import (``_default_*``) so ``app.main``
imports even while those units are still stubs, and so tests can inject fakes.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from contracts.python.models import AgentResult, ResearchRequest, Video
from app.adapters.base import terminate_for_thread
from app.redact import redact
from app.store import run_store

from app.orchestrator.events import make_error_event, make_event
from app.orchestrator.parse import StreamCollector, find_json_array, validate_agent_result
from app.orchestrator.prompts import (
    build_direct_prompt,
    build_expand_prompt,
    build_prompt,
    build_repair_prompt,
    map_filters,
)

_UNSET = object()
_TERMINAL_STATUSES = {"done", "error", "cancelled"}

# Cap the direct adapter's expanded keywords so one run can't balloon YouTube
# quota (each keyword is a 100-unit search.list). Aligned with the cost meter's
# "typical" ≈ 14 terms; the model is asked for 6–12.
_MAX_EXPANDED_KEYWORDS = 15


# --- internal control-flow exceptions (mapped to ErrorCode terminal events) ---
class _Cancelled(Exception):
    pass


class _NoResults(Exception):
    pass


class _CliMissing(Exception):
    pass


class _CliFailed(Exception):
    pass


class _QuotaExceeded(Exception):
    pass


class _InvalidOutput(Exception):
    pass


# --- per-run handle registry (cancellation + terminal-emit guard) -------------
@dataclass
class _Handle:
    run_id: str
    cancelled: threading.Event
    closer: Optional[Callable[[], None]] = None
    terminal_emitted: bool = False
    thread: Optional[threading.Thread] = None


_HANDLES: Dict[str, _Handle] = {}
_HLOCK = threading.Lock()


def _get_handle(run_id: str) -> Optional[_Handle]:
    with _HLOCK:
        return _HANDLES.get(run_id)


def is_cancelled(run_id: str) -> bool:
    handle = _get_handle(run_id)
    if handle is not None and handle.cancelled.is_set():
        return True
    return run_store.get_status(run_id).get("status") == "cancelled"


def emit_terminal(run_id: str, event: Any) -> bool:
    """Append a terminal event at most once per run (idempotent).

    Both the worker (on completion / caught error) and the cancel endpoint may
    race to end a run; the first terminal event wins, later ones are dropped.
    """
    with _HLOCK:
        handle = _HANDLES.get(run_id)
        if handle is not None:
            if handle.terminal_emitted:
                return False
            handle.terminal_emitted = True
    run_store.append_event(run_id, event)
    return True


# --- default (lazy) dependency resolvers — real B2/B3/B5 seams ----------------
def _default_adapter_factory(adapter_id: str) -> Any:
    from app.adapters import get_adapter  # B2

    return get_adapter(adapter_id)


def _default_pipeline_runner(
    request: ResearchRequest, *, keywords: Optional[List[str]] = None
) -> Any:
    from app.pipeline import run_pipeline  # B3

    return run_pipeline(request, keywords=keywords)


def _default_verifier(
    request: ResearchRequest, agent_result: AgentResult, videos: List[Any], meta: Any
) -> Any:
    from app.verify import assemble_and_verify  # B5

    return assemble_and_verify(request, agent_result, videos, meta)


# --- helpers ------------------------------------------------------------------
def _emit(
    run_id: str,
    phase: str,
    *,
    detail: Optional[str] = None,
    counts: Optional[Dict[str, int]] = None,
    pct=_UNSET,
    label: Optional[str] = None,
) -> None:
    # Forward pct only when explicitly given, so make_event applies its own
    # phase default (our _UNSET is a different object than events'._UNSET).
    kwargs: Dict[str, Any] = {"detail": detail, "counts": counts, "label": label}
    if pct is not _UNSET:
        kwargs["pct"] = pct
    run_store.append_event(run_id, make_event(run_id, phase, **kwargs))


def _check_cancel(run_id: str) -> None:
    if is_cancelled(run_id):
        raise _Cancelled()


def _classify_external_error(exc: Exception) -> Exception:
    """Map an adapter/pipeline exception to a typed control-flow error."""
    if isinstance(exc, FileNotFoundError):
        return _CliMissing(
            "We couldn't find the agent CLI. Install it, then run the "
            "environment check again."
        )
    msg = str(exc).lower()
    if any(tok in msg for tok in ("quota", "429", "403", "rate limit", "ratelimit")):
        return _QuotaExceeded(
            "YouTube's daily quota is used up. Try again after it resets, or use "
            "a different key."
        )
    if any(
        tok in msg
        for tok in (
            "command not found",
            "no such file",
            "not installed",
            "cannot find",
            "not found",
            "unknown adapter",
            "no adapter",
            "install",
        )
    ):
        return _CliMissing(
            "We couldn't find the agent CLI. Install it, then run the "
            "environment check again."
        )
    # Never interpolate a raw external exception: googleapiclient's HttpError
    # repr carries the request URI, which carries the API key. `redact` strips
    # it; `make_error_event` scrubs again on the way out (app/redact.py).
    return _CliFailed(
        "The agent CLI failed: %s" % (redact(str(exc)) or type(exc).__name__)
    )


def _coerce_videos(rows: Any) -> List[Video]:
    """Normalize the pipeline's rows to ``Video`` model instances.

    B3's ``run_pipeline`` returns *Video-shaped dicts*; B5's
    ``assemble_and_verify`` consumes ``List[Video]`` *models* (attribute access
    on ``v.video_id``). B4 is the glue between them, so we coerce here. Rows that
    fail validation are dropped (belt-and-suspenders — B3 already validates)."""
    out: List[Video] = []
    for row in rows or []:
        if isinstance(row, Video):
            out.append(row)
        elif isinstance(row, dict):
            try:
                out.append(Video.model_validate(row))
            except Exception:
                continue
        elif hasattr(row, "video_id"):
            out.append(row)  # already model-like
    return out


def _unpack_pipeline(out: Any) -> Tuple[List[Video], Any]:
    """Accept ``(videos, meta)``, an object with ``.videos``/``.meta``, or a
    bare video list; return ``(List[Video], meta)``."""
    if isinstance(out, tuple) and len(out) == 2:
        return _coerce_videos(out[0]), out[1]
    videos = getattr(out, "videos", None)
    if videos is not None:
        return _coerce_videos(videos), getattr(out, "meta", {})
    if isinstance(out, list):
        return _coerce_videos(out), {}
    raise _CliFailed("pipeline returned an unrecognized shape: %r" % type(out))


def _counts_from(meta: Any, videos: List[Any]) -> Dict[str, int]:
    source: Dict[str, Any] = {}
    if isinstance(meta, dict):
        inner = meta.get("counts")
        source = inner if isinstance(inner, dict) else meta

    def pick(*keys: str) -> Optional[int]:
        for key in keys:
            val = source.get(key)
            if isinstance(val, bool):
                continue
            if isinstance(val, int):
                return val
        return None

    counts: Dict[str, int] = {}
    found = pick("found", "unique", "total")
    longform = pick("longform", "long_form")
    curated = pick("curated", "kept", "selected")
    if found is None:
        found = len(videos)
    counts["found"] = found
    if longform is not None:
        counts["longform"] = longform
    counts["curated"] = curated if curated is not None else len(videos)
    return counts


def _result_counts(result: Any) -> Optional[Dict[str, int]]:
    meta = result.get("meta") if isinstance(result, dict) else getattr(result, "meta", None)
    counts = meta.get("counts") if isinstance(meta, dict) else getattr(meta, "counts", None)
    if isinstance(counts, dict):
        return {k: int(v) for k, v in counts.items() if isinstance(v, int) and not isinstance(v, bool)}
    return None


def _safe_close(obj: Any) -> None:
    closer = getattr(obj, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            pass


def _try_validate(obj: Optional[Dict[str, Any]]) -> Tuple[Optional[AgentResult], str]:
    if obj is None:
        return None, "No JSON object was found in the agent output."
    try:
        return validate_agent_result(obj), ""
    except ValidationError as exc:
        errors = exc.errors()[:4]
        return None, "AgentResult schema validation failed: %s" % errors


# --- agent streaming ----------------------------------------------------------
def _stream_and_extract(
    run_id: str,
    adapter: Any,
    prompt: str,
    counts: Dict[str, int],
) -> Optional[Dict[str, Any]]:
    collector = StreamCollector()
    try:
        stream = adapter.stream(prompt)
    except Exception as exc:  # noqa: BLE001 - classified below
        raise _classify_external_error(exc)

    handle = _get_handle(run_id)
    stream_closer = getattr(stream, "close", None)
    if handle is not None and callable(stream_closer):
        handle.closer = stream_closer
    try:
        for line in stream:
            _check_cancel(run_id)
            detail = collector.feed(line if isinstance(line, str) else str(line))
            if detail:
                _emit(run_id, "analyzing", detail=detail, counts=counts)
    except _Cancelled:
        _safe_close(stream)
        raise
    except Exception as exc:  # noqa: BLE001 - classified below
        _safe_close(stream)
        raise _classify_external_error(exc)
    finally:
        if handle is not None:
            handle.closer = None
        _safe_close(stream)
    return collector.extract()


def _run_agent(
    run_id: str,
    request: ResearchRequest,
    prompt: str,
    adapter: Any,
    counts: Dict[str, int],
) -> AgentResult:
    """Stream ``prompt`` through the (already-resolved) ``adapter``, validate the
    AgentResult, and repair once on failure. Shared by the agentic + direct paths
    (only the prompt differs)."""
    obj = _stream_and_extract(run_id, adapter, prompt, counts)
    agent_result, err = _try_validate(obj)
    if agent_result is not None:
        return agent_result

    # ONE error-correcting repair retry (PRD FR-7 / CONTRACTS §7).
    _check_cancel(run_id)
    _emit(run_id, "analyzing", detail="Agent output invalid — repairing", counts=counts)
    repair_prompt = build_repair_prompt(prompt, obj, err)
    obj2 = _stream_and_extract(run_id, adapter, repair_prompt, counts)
    agent_result2, err2 = _try_validate(obj2)
    if agent_result2 is not None:
        return agent_result2
    raise _InvalidOutput(err2 or err or "Agent produced no valid output.")


def _expand_keywords(
    run_id: str, adapter: Any, request: ResearchRequest
) -> Optional[List[str]]:
    """Direct-path LLM step 1: expand the topic into search keywords for the
    deterministic pipeline.

    Best-effort: any failure (bad JSON, API hiccup) returns ``None`` so the
    pipeline falls back to the raw query — a flaky expansion never sinks a run.
    Cancellation propagates. Never lets an agent-typed string become a fact — the
    keywords only choose what the pipeline *searches*; every id/number still comes
    from the pipeline.
    """
    prompt = build_expand_prompt(request)
    parts: List[str] = []
    try:
        stream = adapter.stream(prompt)
    except _Cancelled:
        raise
    except Exception:  # noqa: BLE001 - expansion is optional; fall back to [query]
        return None

    handle = _get_handle(run_id)
    stream_closer = getattr(stream, "close", None)
    if handle is not None and callable(stream_closer):
        handle.closer = stream_closer
    try:
        for chunk in stream:
            _check_cancel(run_id)
            parts.append(chunk if isinstance(chunk, str) else str(chunk))
    except _Cancelled:
        _safe_close(stream)
        raise
    except Exception:  # noqa: BLE001 - fall back to [query] on any stream error
        _safe_close(stream)
        return None
    finally:
        if handle is not None:
            handle.closer = None
        _safe_close(stream)

    keywords = _parse_keywords("\n".join(parts))
    if not keywords:
        return None
    keywords = keywords[:_MAX_EXPANDED_KEYWORDS]
    _emit(run_id, "expanding", detail="Expanded into %d search terms" % len(keywords))
    return keywords


def _parse_keywords(text: str) -> List[str]:
    """Recover the search-phrase list from the model's text (a JSON array)."""
    blob = find_json_array(text)
    if blob is None:
        return []
    try:
        arr = json.loads(blob)
    except Exception:
        return []
    out: List[str] = []
    seen = set()
    for item in arr if isinstance(arr, list) else []:
        if isinstance(item, str):
            phrase = item.strip()
            key = phrase.lower()
            if phrase and key not in seen:
                seen.add(key)
                out.append(phrase)
    return out


# --- the background job -------------------------------------------------------
def run_research_job(
    run_id: str,
    request: ResearchRequest,
    *,
    adapter_factory: Optional[Callable[[str], Any]] = None,
    pipeline_runner: Optional[Callable[[ResearchRequest], Any]] = None,
    verifier: Optional[Callable[..., Any]] = None,
) -> None:
    """Execute one research run start-to-terminal. Emits ProgressEvents through
    ``run_store``; on success sets the result BEFORE the terminal ``done`` event
    (so the result is ready the instant ``done`` fires, per CONTRACTS §3)."""
    adapter_factory = adapter_factory or _default_adapter_factory
    pipeline_runner = pipeline_runner or _default_pipeline_runner
    verifier = verifier or _default_verifier

    try:
        _emit(run_id, "queued")
        _check_cancel(run_id)

        # Resolve the adapter up front so we know its execution style. Agentic
        # adapters (the CLIs) run the research scripts themselves; the direct API
        # adapter can't, so B4 feeds it the collected videos and drives the two LLM
        # steps (keyword expansion, then narrative) explicitly.
        try:
            adapter = adapter_factory(request.model.adapter)
        except Exception as exc:  # noqa: BLE001 - classified below
            raise _classify_external_error(exc)
        if adapter is None:
            raise _CliMissing(
                "No adapter is installed for '%s'. Install it and re-check."
                % request.model.adapter
            )
        agentic = bool(getattr(adapter, "agentic", True))
        filters = map_filters(request)

        # Phase: expanding.
        _emit(run_id, "expanding", detail='Expanding "%s"' % (request.query[:60]))
        _check_cancel(run_id)
        if agentic:
            # The agentic CLI expands keywords + runs the scripts itself.
            prompt = build_prompt(request, filters=filters)
            keywords: Optional[List[str]] = None
        else:
            # Direct API — LLM step 1: expand keywords to broaden the search.
            keywords = _expand_keywords(run_id, adapter, request)
            prompt = None
        _check_cancel(run_id)

        # Phases: searching -> enriching -> scoring — deterministic pipeline (B3).
        _emit(run_id, "searching")
        try:
            if agentic:
                pipeline_out = pipeline_runner(request)
            else:
                pipeline_out = pipeline_runner(request, keywords=keywords)
        except (_Cancelled,):
            raise
        except Exception as exc:  # noqa: BLE001 - classified below
            raise _classify_external_error(exc)
        videos, meta = _unpack_pipeline(pipeline_out)
        counts = _counts_from(meta, videos)
        _emit(run_id, "enriching", counts=counts)
        _check_cancel(run_id)
        _emit(run_id, "scoring", counts=counts)
        if not videos:
            raise _NoResults(
                "No standout videos matched those filters. Try a broader date "
                "range or lower the outperformance bar."
            )
        _check_cancel(run_id)

        # Phase: analyzing — collect + validate the AgentResult (narrative only).
        _emit(run_id, "analyzing", counts=counts)
        if agentic:
            agent_result = _run_agent(run_id, request, prompt, adapter, counts)
        else:
            # Direct API — LLM step 2: narrate over the collected videos.
            direct_prompt = build_direct_prompt(request, videos, meta, filters=filters)
            agent_result = _run_agent(run_id, request, direct_prompt, adapter, counts)

        # Phase: verifying — join refs -> authoritative videos + link verify (B5).
        _check_cancel(run_id)
        _emit(run_id, "verifying", counts=counts)
        result = verifier(request, agent_result, videos, meta)

        # Terminal: done — result ready before the event fires.
        _check_cancel(run_id)
        run_store.set_result(run_id, result)
        emit_terminal(
            run_id,
            make_event(run_id, "done", counts=_result_counts(result) or counts),
        )
    except _Cancelled:
        emit_terminal(run_id, make_error_event(run_id, "cancelled", "Run cancelled."))
    except _NoResults as exc:
        emit_terminal(run_id, make_error_event(run_id, "no_results", str(exc)))
    except _CliMissing as exc:
        emit_terminal(run_id, make_error_event(run_id, "cli_missing", str(exc)))
    except _QuotaExceeded as exc:
        emit_terminal(run_id, make_error_event(run_id, "quota_exceeded", str(exc)))
    except _InvalidOutput as exc:
        emit_terminal(run_id, make_error_event(run_id, "invalid_output", str(exc)))
    except _CliFailed as exc:
        emit_terminal(run_id, make_error_event(run_id, "cli_failed", str(exc)))
    except Exception as exc:  # noqa: BLE001 - last-resort catch-all
        emit_terminal(
            run_id,
            make_error_event(run_id, "unknown", "%s: %s" % (type(exc).__name__, exc)),
        )


# --- public lifecycle API (consumed by app/api/research.py) -------------------
def launch(run_id: str, request: ResearchRequest, **deps: Any) -> _Handle:
    """Register a run and start its background worker thread. Returns the handle."""
    handle = _Handle(run_id=run_id, cancelled=threading.Event())
    with _HLOCK:
        _HANDLES[run_id] = handle
    thread = threading.Thread(
        target=run_research_job,
        args=(run_id, request),
        kwargs=deps,
        daemon=True,
        name="yuben-run-%s" % run_id,
    )
    handle.thread = thread
    thread.start()
    return handle


def request_cancel(run_id: str) -> bool:
    """Cancel a running job: flip the store status, signal the worker, terminate
    the adapter subprocess, and emit a terminal ``error{code:"cancelled"}``
    (idempotent). No-op if already finished.

    The subprocess is terminated by handle, not by closing the stream generator.
    Cancel arrives on the API thread while the worker sits blocked reading the
    child's stdout, and closing a generator that another thread is executing
    raises ``ValueError`` — so the old ``closer()`` call could never do the one
    thing it was there for. Killing the child instead lands EOF on stdout and
    lets the worker unwind through ``stream_process``'s own cleanup."""
    if not run_store.has_run(run_id):
        return False
    status = run_store.get_status(run_id).get("status")
    if status in ("done", "error"):
        return False  # already terminal; nothing to cancel

    handle = _get_handle(run_id)
    already = handle.terminal_emitted if handle is not None else False

    run_store.cancel_run(run_id)  # sticky "cancelled" status
    if handle is not None:
        handle.cancelled.set()
        # Kill the child first: it is what the worker is blocked on.
        thread = handle.thread
        terminate_for_thread(thread.ident if thread is not None else None)
        # Still close the generator when we can. It is a no-op mid-iteration
        # (the ValueError below), but it is the correct unwind if the worker is
        # between lines, and it keeps non-subprocess adapters cancellable.
        closer = handle.closer
        if closer is not None:
            try:
                closer()
            except (ValueError, RuntimeError):
                pass  # generator already executing / already closed
            except Exception:
                pass
    if not already:
        emit_terminal(run_id, make_error_event(run_id, "cancelled", "Run cancelled."))
    return True


def reset() -> None:
    """Test helper: clear the handle registry."""
    with _HLOCK:
        _HANDLES.clear()
