"""Adapter registry (B2).

Public surface consumed by the rest of the backend:

* ``get_adapter(adapter_id) -> AgentAdapter`` — the concrete adapter (B4 uses
  this to reach ``.stream()``). Tolerant of a few id spellings.
* ``list_adapters() -> list[Adapter]`` — detect installed + version + models for
  every adapter, serialized as the frozen ``contracts.python.models.Adapter``.
  Backs ``GET /api/adapters``.
* ``check_env(adapter, model=None) -> dict`` — dispatch a live "respond hello"
  probe to the right adapter. **This is the exact symbol B1's
  ``app/api/config.py`` imports** (`from app.adapters import check_env`).

Claude Code is the primary adapter. Gemini CLI is a stub, registered so a stored
config still resolves, but left out of ``list_adapters`` until it can run.

Registration order is display order, and it is deliberate: the key-paste API
providers come first (nothing to install, so they're the shortest path for a new
user), then the local CLIs. ``build_cli_adapters()`` expands the spec table in
``cli_agents`` — adding another agent CLI means editing that table, not this file.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from contracts.python.models import Adapter

from app.adapters.base import AdapterError, AgentAdapter
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.cli_agents import CLI_SPECS, CliSpec, GenericCliAdapter, build_cli_adapters
from app.adapters.direct_anthropic import DirectAnthropicAdapter
from app.adapters.gemini_cli import GeminiCliAdapter
from app.adapters.openai_compatible import (
    GeminiAdapter,
    OllamaAdapter,
    OpenAIAdapter,
    OpenAICompatibleAdapter,
    OpenRouterAdapter,
)

__all__ = [
    "get_adapter",
    "list_adapters",
    "forget_detection",
    "check_env",
    "AgentAdapter",
    "AdapterError",
    "ClaudeCodeAdapter",
    "DirectAnthropicAdapter",
    "GeminiCliAdapter",
    "OpenAIAdapter",
    "OpenAICompatibleAdapter",
    "OpenRouterAdapter",
    "OllamaAdapter",
    "GenericCliAdapter",
    "CliSpec",
    "CLI_SPECS",
    "PRIMARY_ADAPTER_ID",
]

#: The env-check fallback for an empty adapter id — the CLI probe is a safe,
#: side-effect-free default (the direct adapter's probe needs a stored key).
PRIMARY_ADAPTER_ID = "claude-code"

# Insertion order is the display order. The terminal-free Anthropic API path is
# surfaced first (Phase 4), then the local CLIs.
_ADAPTERS: "Dict[str, AgentAdapter]" = {}


def _register(adapter: AgentAdapter) -> None:
    _ADAPTERS[adapter.id] = adapter


# Key-paste API providers first (nothing to install), then the local CLIs.
_register(DirectAnthropicAdapter())
_register(OpenAIAdapter())
_register(GeminiAdapter())
_register(OpenRouterAdapter())
_register(OllamaAdapter())
_register(ClaudeCodeAdapter())
_register(GeminiCliAdapter())
for _cli in build_cli_adapters():
    _register(_cli)

# Tolerate a few id spellings the UI / stored config might send.
_ALIASES: Dict[str, str] = {
    "claude": "claude-code",
    "claude_code": "claude-code",
    "claudecode": "claude-code",
    "gemini": "gemini-cli",
    "gemini_cli": "gemini-cli",
    "geminicli": "gemini-cli",
    "anthropic": "anthropic-api",
    "anthropic_api": "anthropic-api",
    "anthropicapi": "anthropic-api",
    "api": "anthropic-api",
    "openai": "openai-api",
    "openai_api": "openai-api",
    "openaiapi": "openai-api",
    "gpt": "openai-api",
    "gemini_api": "gemini-api",
    "geminiapi": "gemini-api",
    "google": "gemini-api",
    "open_router": "openrouter",
    "openrouter_api": "openrouter",
    "router": "openrouter",
    "local": "ollama",
    "codex": "codex-cli",
    "cursor": "cursor-cli",
    "cursor_agent": "cursor-cli",
    "cursor-agent": "cursor-cli",
    "opencode": "opencode-cli",
    "qwen": "qwen-cli",
    "qwen_code": "qwen-cli",
    "copilot": "copilot-cli",
    "github_copilot": "copilot-cli",
    "amp": "amp-cli",
}


def _canonical(adapter_id: Optional[str]) -> Optional[str]:
    if not adapter_id:
        return None
    key = adapter_id.strip().lower()
    if key in _ADAPTERS:
        return key
    return _ALIASES.get(key)


def get_adapter(adapter_id: str) -> AgentAdapter:
    """Return the concrete adapter for ``adapter_id``.

    Raises :class:`KeyError` for an unknown id (callers that prefer a graceful
    result — like ``check_env`` — catch it).
    """
    canon = _canonical(adapter_id)
    if canon is None:
        raise KeyError("unknown adapter: {!r}".format(adapter_id))
    return _ADAPTERS[canon]


#: How long one adapter's detection (``--version`` and any live model list) is
#: reused. Short, so installing a CLI shows up on the next look; long enough
#: that the picker's repeated ``GET /api/adapters`` calls don't respawn every
#: CLI each time (reliability R2). Saving a key clears it.
DETECT_TTL_SECONDS = 15.0

_DETECTED: Dict[str, Tuple[float, Adapter]] = {}
_DETECT_LOCK = threading.Lock()


def _describe(adapter: AgentAdapter) -> Adapter:
    detected = adapter.detect()
    return Adapter(
        id=adapter.id,
        name=adapter.name,
        installed=bool(detected.get("installed", False)),
        version=detected.get("version"),
        models=adapter.models(),
    )


def list_adapters() -> List[Adapter]:
    """Detect every adapter and return ``Adapter[]`` (contracts model).

    Adapters not detected in the last :data:`DETECT_TTL_SECONDS` are detected
    in parallel, so the slowest CLI or model fetch bounds the call, not their sum.
    """
    shown = [a for a in _ADAPTERS.values() if getattr(a, "selectable", True)]
    now = time.monotonic()
    with _DETECT_LOCK:
        fresh = {
            a.id: entry[1]
            for a in shown
            for entry in [_DETECTED.get(a.id)]
            if entry is not None and now - entry[0] < DETECT_TTL_SECONDS
        }
    stale = [a for a in shown if a.id not in fresh]
    if stale:
        with ThreadPoolExecutor(max_workers=len(stale), thread_name_prefix="yuben-detect") as pool:
            described = list(pool.map(_describe, stale))
        done_at = time.monotonic()
        with _DETECT_LOCK:
            for item in described:
                _DETECTED[item.id] = (done_at, item)
                fresh[item.id] = item
    return [fresh[a.id] for a in shown]


def forget_detection() -> None:
    """Drop cached detection, e.g. after a key change alters a model list."""
    with _DETECT_LOCK:
        _DETECTED.clear()


def check_env(adapter: str, model: Optional[str] = None) -> Dict[str, Any]:
    """Dispatch a live env-check probe to the requested adapter.

    Returns the EnvCheckResult dict ``{ok, adapter, version, message}``. Never
    raises: an empty adapter id falls back to the primary adapter, and an unknown
    id is a graceful ``ok:false`` so B1's config router surfaces a clean message.
    """
    requested = adapter or PRIMARY_ADAPTER_ID
    try:
        impl = get_adapter(requested)
    except KeyError:
        return {
            "ok": False,
            "adapter": adapter or "",
            "version": None,
            "message": "Unknown adapter {!r}. Available: {}.".format(
                adapter, ", ".join(_ADAPTERS)
            ),
        }
    result = impl.check_env(model)
    _record_check(impl, model, result)
    return result


# --------------------------------------------------------------------------- #
# Preflight — a passing check per (adapter, model, settings)
# --------------------------------------------------------------------------- #
#
# A run spends YouTube quota before the model's narrative step. A model that
# cannot answer must fail before that, so the orchestrator asks
# :func:`ensure_checked` first. Passing checks are remembered in memory for the
# exact adapter, resolved model and settings fingerprint they ran with; a new
# key, base URL, model or output cap means a new check.

_PASSED_CHECKS: Dict[Tuple[str, str, str], bool] = {}
_CHECK_LOCK = threading.Lock()


def _check_key(impl: Any, model: Optional[str]) -> Optional[Tuple[str, str, str]]:
    try:
        resolve = getattr(impl, "_resolve_model", None)
        resolved = resolve(model) if callable(resolve) else (model or "default")
        fingerprint = getattr(impl, "settings_fingerprint", None)
        settings = fingerprint(resolved) if callable(fingerprint) else ""
    except Exception:  # an unreadable store means "not checked", not a crash
        return None
    return (getattr(impl, "id", type(impl).__name__), resolved or "default", settings)


def _record_check(impl: Any, model: Optional[str], result: Any) -> None:
    key = _check_key(impl, model)
    if key is None or not isinstance(result, dict):
        return
    with _CHECK_LOCK:
        if result.get("ok"):
            _PASSED_CHECKS[key] = True
        else:
            _PASSED_CHECKS.pop(key, None)


def has_passing_check(impl: Any, model: Optional[str]) -> bool:
    key = _check_key(impl, model)
    with _CHECK_LOCK:
        return key is not None and key in _PASSED_CHECKS


def ensure_checked(impl: Any, model: Optional[str]) -> Optional[str]:
    """Run the model check unless one already passed for these settings.

    Returns ``None`` when the model is ready, else the failed check's message.
    Adapters without a ``check_env`` (test fakes) are treated as ready.
    """
    check = getattr(impl, "check_env", None)
    if not callable(check) or has_passing_check(impl, model):
        return None
    try:
        result = check(model)
    except Exception as exc:  # check_env must not raise; be safe anyway
        return str(exc) or type(exc).__name__
    _record_check(impl, model, result)
    if isinstance(result, dict) and result.get("ok"):
        return None
    message = result.get("message") if isinstance(result, dict) else None
    return message or "The model check did not pass."


def reset_checks() -> None:
    """Test helper: forget every passing check."""
    with _CHECK_LOCK:
        _PASSED_CHECKS.clear()
