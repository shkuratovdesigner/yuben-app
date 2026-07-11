"""ClaudeCodeAdapter — headless Claude Code CLI (``claude``).

* detect   : ``shutil.which("claude")`` + ``claude --version``.
* check_env: ``claude -p "Reply with exactly: hello"`` (a tiny real turn) and
             confirm the CLI actually responded.
* stream   : ``claude -p <prompt> --output-format stream-json --verbose`` — the
             headless event stream B4's orchestrator consumes.

Ships first (BUILD_PLAN B2 / PRD §12: "ship Claude Code first").
"""
from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional

from app.adapters.base import (
    AdapterError,
    AgentAdapter,
    run_probe,
    run_version,
    stream_process,
    which,
)

# Detection is a fast local call; the hello probe runs a real (tiny) model turn,
# so it gets a much longer ceiling (cold start + a round-trip).
_DETECT_TIMEOUT = 10.0
_PROBE_TIMEOUT = 90.0

_INSTALL_HINT = (
    "We couldn't find the Claude Code CLI ('claude'). Install it from "
    "https://claude.com/claude-code, then run the environment check again."
)


def _truncate(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class ClaudeCodeAdapter(AgentAdapter):
    id = "claude-code"
    name = "Claude Code"
    binary = "claude"

    # Current Claude model ids (docs/PHASE1_HANDOFF B2 row). "default" leaves the
    # model unset so the CLI uses whatever the user configured.
    _MODELS: List[str] = [
        "default",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5",
        "claude-fable-5",
    ]

    # -- detection -----------------------------------------------------------
    def models(self) -> List[str]:
        return list(self._MODELS)

    def detect(self) -> Dict[str, Any]:
        path = which(self.binary)
        if not path:
            return {"installed": False, "version": None}
        return {"installed": True, "version": run_version(path, timeout=_DETECT_TIMEOUT)}

    # -- live "respond hello" probe -----------------------------------------
    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        path = which(self.binary)
        if not path:
            return self._result(False, None, _INSTALL_HINT)

        version = run_version(path, timeout=_DETECT_TIMEOUT)

        cmd = [path, "-p", "Reply with exactly: hello"]
        if model and model != "default":
            cmd += ["--model", model]

        try:
            proc = run_probe(cmd, timeout=_PROBE_TIMEOUT)
        except Exception as exc:  # TimeoutExpired, OSError, ...
            import subprocess

            if isinstance(exc, subprocess.TimeoutExpired):
                return self._result(
                    False, version,
                    "Claude Code did not respond within {:.0f}s.".format(_PROBE_TIMEOUT),
                )
            return self._result(False, version, "Failed to run Claude Code: {}".format(exc))

        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            err = (proc.stderr or "").strip() or out or "exit code {}".format(proc.returncode)
            return self._result(False, version, _truncate("Claude Code CLI error: " + err))
        if not out:
            return self._result(False, version, "Claude Code ran but returned no output.")

        if "hello" in out.lower():
            msg = "Claude Code responded"
            msg += " (v{}).".format(version) if version else "."
            return self._result(True, version, msg)
        # It responded — just not the literal we asked for. Still proves the CLI
        # + auth work, but surface the oddity rather than silently passing.
        return self._result(
            False, version,
            _truncate("Claude Code responded unexpectedly: " + out),
        )

    # -- headless run surface (B4) ------------------------------------------
    def stream(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Iterator[str]:
        path = which(self.binary)
        if not path:
            raise AdapterError(_INSTALL_HINT)
        cmd = [
            path,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--verbose",  # required companion of stream-json in headless mode
        ]
        if model and model != "default":
            cmd += ["--model", model]
        return stream_process(cmd, cwd=cwd)

    # -- helper --------------------------------------------------------------
    def _result(self, ok: bool, version: Optional[str], message: str) -> Dict[str, Any]:
        return {"ok": ok, "adapter": self.id, "version": version, "message": message}
