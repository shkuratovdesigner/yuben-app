"""Spec-driven adapters for local agent CLIs (Codex, Cursor, opencode, …).

Every one of these tools does the same thing from YuBen's point of view: take a
prompt on argv, print text on stdout, exit. The only differences are the binary
name, the sub-command or flag that means "one-shot, non-interactive", and how to
name a model. So they are ROWS IN A TABLE, not classes — adding another agent is
one ``CliSpec`` entry, which is what the README's "adding your own is one small
class" promise should have meant all along.

``ClaudeCodeAdapter`` deliberately stays hand-written: it is the primary adapter,
its stream surface is the one B4 was built against, and it carries behaviour
(stream-json, --verbose) the generic path shouldn't have to model.

VERIFICATION STATUS. The invocations for Codex, Cursor and opencode are taken
from their published non-interactive docs. Qwen, Copilot and Amp follow the
conventions of the CLIs they descend from but have NOT been run end-to-end here
— none of these tools were installed on the machine this shipped from. They are
marked ``verified=False`` and the UI labels them experimental. If one is wrong,
the fix is a single field in the table below, not a code change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.adapters.base import (
    AdapterError,
    AgentAdapter,
    run_probe,
    run_version,
    stream_process,
    which,
)

_DETECT_TIMEOUT = 10.0
_PROBE_TIMEOUT = 90.0


def _truncate(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


@dataclass(frozen=True)
class CliSpec:
    """Everything that distinguishes one agent CLI from another."""

    id: str
    name: str
    binary: str
    #: Argv that precedes the prompt — a sub-command ("exec", "run") or a flag ("-p").
    prompt_args: Tuple[str, ...]
    install_url: str
    #: Flag that selects a model, or None when the CLI has no such flag.
    model_flag: Optional[str] = None
    #: Argv appended after the prompt (e.g. forcing plain-text output).
    extra_args: Tuple[str, ...] = ()
    #: Selectable models. Most agent CLIs use whatever the user configured, so
    #: "default" alone is the honest answer rather than a list that goes stale.
    models_list: List[str] = field(default_factory=lambda: ["default"])
    #: True once the headless invocation has actually been run against the tool.
    verified: bool = False


#: The agent fleet. Order here is display order after the hand-written adapters.
CLI_SPECS: List[CliSpec] = [
    CliSpec(
        id="codex-cli",
        name="Codex CLI",
        binary="codex",
        # `codex exec` is the documented non-interactive mode: streams progress to
        # stderr, prints only the final agent message to stdout.
        prompt_args=("exec",),
        model_flag="-m",
        install_url="https://developers.openai.com/codex",
        verified=True,
    ),
    CliSpec(
        id="cursor-cli",
        name="Cursor CLI",
        binary="cursor-agent",
        # Print mode; --output-format text keeps stdout free of JSON envelopes.
        prompt_args=("-p",),
        model_flag="--model",
        extra_args=("--output-format", "text"),
        install_url="https://cursor.com/docs/cli/headless",
        verified=True,
    ),
    CliSpec(
        id="opencode-cli",
        name="opencode",
        binary="opencode",
        prompt_args=("run",),
        model_flag="--model",
        install_url="https://opencode.ai/docs/cli/",
        verified=True,
    ),
    CliSpec(
        id="qwen-cli",
        name="Qwen Code",
        binary="qwen",
        # A Gemini-CLI fork, so it inherits -p / --model. Unconfirmed here.
        prompt_args=("-p",),
        model_flag="--model",
        install_url="https://github.com/QwenLM/qwen-code",
    ),
    CliSpec(
        id="copilot-cli",
        name="GitHub Copilot CLI",
        binary="copilot",
        prompt_args=("-p",),
        model_flag="--model",
        install_url="https://docs.github.com/copilot/concepts/agents/about-copilot-cli",
    ),
    CliSpec(
        id="amp-cli",
        name="Amp",
        binary="amp",
        prompt_args=("-x",),
        install_url="https://ampcode.com/manual",
    ),
]


class GenericCliAdapter(AgentAdapter):
    """An :class:`AgentAdapter` built from a :class:`CliSpec`.

    Behaviour mirrors ``ClaudeCodeAdapter`` — detect via ``which`` + ``--version``,
    prove the CLI answers with a tiny real turn, stream stdout lines for B4 —
    including its stdout-before-stderr error precedence, because these CLIs also
    print the actionable failure (auth, quota) to stdout while stderr carries
    incidental warnings.
    """

    agentic = True

    def __init__(self, spec: CliSpec) -> None:
        self.spec = spec
        self.id = spec.id
        self.name = spec.name
        self.binary = spec.binary

    # -- detection -----------------------------------------------------------
    def models(self) -> List[str]:
        return list(self.spec.models_list)

    def detect(self) -> Dict[str, Any]:
        path = which(self.binary)
        if not path:
            return {"installed": False, "version": None}
        return {"installed": True, "version": run_version(path, timeout=_DETECT_TIMEOUT)}

    # -- argv ----------------------------------------------------------------
    def _build_cmd(self, path: str, prompt: str, model: Optional[str]) -> List[str]:
        cmd = [path, *self.spec.prompt_args, prompt, *self.spec.extra_args]
        if model and model != "default" and self.spec.model_flag:
            cmd += [self.spec.model_flag, model]
        return cmd

    def _install_hint(self) -> str:
        return (
            "We couldn't find the {} CLI ('{}'). Install it from {}, then run the "
            "environment check again.".format(self.name, self.binary, self.spec.install_url)
        )

    # -- live "respond hello" probe -----------------------------------------
    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        path = which(self.binary)
        if not path:
            return self._result(False, None, self._install_hint())

        version = run_version(path, timeout=_DETECT_TIMEOUT)
        cmd = self._build_cmd(path, "Reply with exactly: hello", model)

        try:
            proc = run_probe(cmd, timeout=_PROBE_TIMEOUT)
        except Exception as exc:
            import subprocess

            if isinstance(exc, subprocess.TimeoutExpired):
                return self._result(
                    False,
                    version,
                    "{} did not respond within {:.0f}s.".format(self.name, _PROBE_TIMEOUT),
                )
            return self._result(False, version, "Failed to run {}: {}".format(self.name, exc))

        out = (proc.stdout or "").strip()
        if proc.returncode != 0:
            # stdout first — see ClaudeCodeAdapter.check_env for why.
            err = out or (proc.stderr or "").strip() or "exit code {}".format(proc.returncode)
            return self._result(False, version, _truncate(self.name + " CLI error: " + err))
        if not out:
            return self._result(False, version, "{} ran but returned no output.".format(self.name))

        if "hello" in out.lower():
            msg = "{} responded".format(self.name)
            msg += " (v{}).".format(version) if version else "."
            if not self.spec.verified:
                msg += " This adapter is experimental — please report anything odd."
            return self._result(True, version, msg)
        return self._result(
            False, version, _truncate("{} responded unexpectedly: {}".format(self.name, out))
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
            raise AdapterError(self._install_hint())
        return stream_process(self._build_cmd(path, prompt, model), cwd=cwd)

    # -- helper --------------------------------------------------------------
    def _result(self, ok: bool, version: Optional[str], message: str) -> Dict[str, Any]:
        return {"ok": ok, "adapter": self.id, "version": version, "message": message}


def build_cli_adapters() -> List[GenericCliAdapter]:
    """One adapter per row of :data:`CLI_SPECS`, in table order."""
    return [GenericCliAdapter(spec) for spec in CLI_SPECS]
