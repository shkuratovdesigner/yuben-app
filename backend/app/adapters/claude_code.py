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
    REMEDY_INSTALL,
    REMEDY_SIGN_IN,
    AdapterError,
    AgentAdapter,
    remedy,
    run_probe,
    run_version,
    stream_process,
    which,
)

# Detection is a fast local call; the hello probe runs a real (tiny) model turn,
# so it gets a much longer ceiling (cold start + a round-trip).
_DETECT_TIMEOUT = 10.0
_PROBE_TIMEOUT = 90.0
_AUTH_STATUS_TIMEOUT = 15.0

_INSTALL_URL = "https://claude.com/claude-code"
_SIGN_IN_COMMAND = "claude auth login"

_INSTALL_HINT = (
    "We couldn't find the Claude Code CLI ('claude'). Install it from "
    "https://claude.com/claude-code, then run the environment check again."
)

# Substrings that mark a probe failure as "the CLI works, the credential doesn't"
# rather than a crash. Matched case-insensitively against the CLI's own output.
_AUTH_MARKERS = ("401", "authenticate", "unauthorized", "invalid authentication", "log in", "login")


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

    # -- authentication state ------------------------------------------------
    def auth_status(self) -> Optional[Dict[str, Any]]:
        """Parse ``claude auth status`` (JSON), or None if it can't be read.

        Worth the extra subprocess: it separates "never signed in" from "signed
        in but the credential is stale", which produce the same 401 from the
        probe yet need completely different instructions.
        """
        path = which(self.binary)
        if not path:
            return None
        try:
            proc = run_probe([path, "auth", "status"], timeout=_AUTH_STATUS_TIMEOUT)
        except Exception:
            return None
        raw = (proc.stdout or "").strip()
        if not raw:
            return None
        try:
            import json

            data = json.loads(raw)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _auth_failure(self, version: Optional[str], detail: str) -> Dict[str, Any]:
        """Explain an auth failure using what ``auth status`` actually reports."""
        status = self.auth_status()
        sign_in = remedy(
            REMEDY_SIGN_IN,
            "Sign in to Claude Code",
            command=_SIGN_IN_COMMAND,
            url=_INSTALL_URL,
        )
        if status is None:
            return self._result(
                False, version,
                "Claude Code couldn't authenticate. Sign in and run the check again.",
                remedy=sign_in,
            )
        if not status.get("loggedIn"):
            return self._result(
                False, version,
                "Claude Code isn't signed in yet. Sign in and run the check again.",
                remedy=sign_in,
            )
        # Signed in on paper, rejected in practice — the confusing case. Name the
        # account so it's obvious this isn't a "wrong tool installed" problem.
        who = status.get("email") or status.get("orgName") or "your account"
        return self._result(
            False, version,
            "Claude Code is signed in as {} but the API rejected the request "
            "({}). The saved login has gone stale — sign in again to refresh it.".format(
                who, _truncate(detail, 90)
            ),
            remedy=sign_in,
        )

    # -- live "respond hello" probe -----------------------------------------
    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        path = which(self.binary)
        if not path:
            return self._result(
                False, None, _INSTALL_HINT,
                remedy=remedy(REMEDY_INSTALL, "Install Claude Code", url=_INSTALL_URL),
            )

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
            # stdout first: Claude Code prints its user-facing failure there
            # ("Failed to authenticate. API Error: 401 …"), while stderr carries
            # only incidental warnings. Preferring stderr hid the one message the
            # user can act on. Fall back to stderr for crashes that print nothing.
            err = out or (proc.stderr or "").strip() or "exit code {}".format(proc.returncode)
            lowered = err.lower()
            if any(marker in lowered for marker in _AUTH_MARKERS):
                return self._auth_failure(version, err)
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
    def _result(
        self,
        ok: bool,
        version: Optional[str],
        message: str,
        remedy: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "ok": ok,
            "adapter": self.id,
            "version": version,
            "message": message,
            "remedy": remedy,
        }
