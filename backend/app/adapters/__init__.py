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

Claude Code is the primary adapter and is registered first; Gemini is a stub.

Registration order is display order, and it is deliberate: the key-paste API
providers come first (nothing to install, so they're the shortest path for a new
user), then the local CLIs. ``build_cli_adapters()`` expands the spec table in
``cli_agents`` — adding another agent CLI means editing that table, not this file.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from contracts.python.models import Adapter

from app.adapters.base import AdapterError, AgentAdapter
from app.adapters.claude_code import ClaudeCodeAdapter
from app.adapters.cli_agents import CLI_SPECS, CliSpec, GenericCliAdapter, build_cli_adapters
from app.adapters.direct_anthropic import DirectAnthropicAdapter
from app.adapters.gemini_cli import GeminiCliAdapter
from app.adapters.openai_compatible import (
    OllamaAdapter,
    OpenAIAdapter,
    OpenAICompatibleAdapter,
    OpenRouterAdapter,
)

__all__ = [
    "get_adapter",
    "list_adapters",
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


def list_adapters() -> List[Adapter]:
    """Detect every adapter and return ``Adapter[]`` (contracts model)."""
    out: List[Adapter] = []
    for adapter in _ADAPTERS.values():
        detected = adapter.detect()
        out.append(
            Adapter(
                id=adapter.id,
                name=adapter.name,
                installed=bool(detected.get("installed", False)),
                version=detected.get("version"),
                models=adapter.models(),
            )
        )
    return out


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
    return impl.check_env(model)
