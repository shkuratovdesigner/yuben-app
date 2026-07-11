"""Orchestrator (B4): prompt build, run loop, CLI stream -> ProgressEvents, validation/repair.

Public surface (consumed by ``app.api.research``):
    launch(run_id, request, **deps) -> starts the background worker
    request_cancel(run_id) -> cancels + emits terminal error{cancelled}
    run_research_job(run_id, request, *, adapter_factory, pipeline_runner, verifier)
    build_prompt / map_filters / build_repair_prompt
    make_event / make_error_event / phase_label / PHASE_SEQUENCE
"""
from __future__ import annotations

from app.orchestrator.events import (
    PHASE_SEQUENCE,
    make_error_event,
    make_event,
    phase_label,
)
from app.orchestrator.prompts import (
    TRUST_INSTRUCTION,
    build_direct_prompt,
    build_expand_prompt,
    build_prompt,
    build_repair_prompt,
    map_filters,
)
from app.orchestrator.runner import (
    emit_terminal,
    is_cancelled,
    launch,
    request_cancel,
    reset,
    run_research_job,
)

__all__ = [
    "PHASE_SEQUENCE",
    "TRUST_INSTRUCTION",
    "build_direct_prompt",
    "build_expand_prompt",
    "build_prompt",
    "build_repair_prompt",
    "emit_terminal",
    "is_cancelled",
    "launch",
    "make_error_event",
    "make_event",
    "map_filters",
    "phase_label",
    "request_cancel",
    "reset",
    "run_research_job",
]
