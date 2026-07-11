"""GeminiCliAdapter — STUB behind the same AgentAdapter interface.

Per the frozen decision (PHASE1_HANDOFF "Frozen decisions", PRD §12): ship Claude
Code first, stub Gemini behind the same interface and feature-detect.

* detect   : real — ``shutil.which("gemini")`` + ``gemini --version`` (so the
             onboarding screen shows an accurate installed/version state).
* check_env: graceful — reports "not fully supported yet" instead of running a
             probe (the headless run path isn't wired for Gemini yet).
* stream   : raises :class:`NotImplementedError`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from app.adapters.base import AgentAdapter, run_version, which

_DETECT_TIMEOUT = 10.0

_INSTALL_HINT = (
    "We couldn't find the Gemini CLI ('gemini'). Install it, then run the "
    "environment check again."
)
_NOT_SUPPORTED = (
    "Gemini CLI support isn't fully wired yet — Claude Code is the supported "
    "adapter for now. Detection works, but the live probe and runs are pending."
)


class GeminiCliAdapter(AgentAdapter):
    id = "gemini-cli"
    name = "Gemini CLI"
    binary = "gemini"

    # Left empty until the adapter is fully wired; the onboarding model select
    # falls back to "default" when this is empty.
    _MODELS: List[str] = []

    def models(self) -> List[str]:
        return list(self._MODELS)

    def detect(self) -> Dict[str, Any]:
        path = which(self.binary)
        if not path:
            return {"installed": False, "version": None}
        return {"installed": True, "version": run_version(path, timeout=_DETECT_TIMEOUT)}

    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        path = which(self.binary)
        version = run_version(path, timeout=_DETECT_TIMEOUT) if path else None
        message = _NOT_SUPPORTED if path else _INSTALL_HINT
        # Graceful: never a hard pass. ok=False keeps the UI from gating "Continue"
        # on an adapter that can't actually run a research job yet.
        return {"ok": False, "adapter": self.id, "version": version, "message": message}

    def stream(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Iterator[str]:
        raise NotImplementedError(
            "GeminiCliAdapter.stream is not implemented yet; use the Claude Code "
            "adapter for headless runs."
        )
