"""DirectAnthropicAdapter — the Anthropic Messages API as an AgentAdapter (no CLI).

Terminal-free onboarding (Phase 4): the user pastes their OWN Anthropic API key
(stored write-only in the local secret store, mirroring the YouTube-key path) and
YuBen talks to the public Messages API directly — no ``claude login``, no CLI.

There is **no agentic tool loop** here: the model NEVER runs the research scripts.
``run_pipeline`` (B3) still produces every fact; this adapter carries only the
LLM's *narrative* + real ``video_id`` references, so the HARD TRUST RULE (PRD §8 /
CONTRACTS §7) is byte-for-byte unchanged. Because the model can't run tools, the
adapter is marked ``agentic = False`` — B4's orchestrator feeds it the already
collected videos and drives the two LLM steps explicitly (keyword expansion, then
the AgentResult narrative) instead of one "go run the scripts" prompt.

* detect   : the ``anthropic`` SDK importable + its version (no CLI to find).
* check_env: a cheap real Messages "reply hello" ping with the stored key.
* stream   : stream one Messages request's visible text (``text_stream``), yielded
             chunk-by-chunk so B4's ``StreamCollector`` recovers the final JSON.

The ``anthropic`` import is LAZY in every method so this module loads even when the
SDK is absent (``detect`` then reports ``installed: False`` and ``check_env`` hints
to install it) — the same importable-or-not discipline as ``store/secrets.py``.
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

from app.adapters.base import (
    KIND_AUTH,
    KIND_NOT_INSTALLED,
    AdapterError,
    AgentAdapter,
    OutputTruncated,
    api_error,
    key_digest,
    output_cap_override,
)

# The Messages default model (claude-api skill: default to Opus 5 unless the
# user names another). "default" in the UI maps here.
_DEFAULT_MODEL = "claude-opus-5"

# Current selectable Claude model ids — mirrors ClaudeCodeAdapter so the onboarding
# model select is identical whichever path the user connects through.
_MODELS: List[str] = [
    "default",
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
    "claude-fable-5",
]

# The hello probe runs one tiny real turn; a headroom ceiling covers cold DNS +
# a round-trip.
_PING_TIMEOUT = 60.0
# Output cap when the Models API can't be reached. Every selectable model
# accepts it (the smallest cap, Haiku 4.5's, is 64,000), and it fits a full
# AgentResult + analysis. Requests always stream, so a large cap is safe.
_FALLBACK_MAX_TOKENS = 32000

# Models that predate adaptive thinking (it arrived with the 4.6 generation).
# Used only when the Models API can't say; such models get no thinking param,
# because a fixed budget would be a second tuning knob for one fallback path.
_NO_ADAPTIVE_PREFIXES = (
    "claude-3",
    "claude-haiku-4",
    "claude-sonnet-4-0",
    "claude-sonnet-4-2",
    "claude-sonnet-4-5",
    "claude-opus-4-0",
    "claude-opus-4-1",
    "claude-opus-4-2",
    "claude-opus-4-5",
)

# Models API lookups (output cap + adaptive-thinking support), cached per id.
_MODEL_TTL_SECONDS = 300.0
_MODEL_FETCH_TIMEOUT = 5.0
_model_info_cache: Dict[str, Tuple[float, Optional[int], Optional[bool]]] = {}

_INSTALL_HINT = (
    "The 'anthropic' Python SDK isn't installed on the backend. Run "
    "'pip install anthropic' (or 'make install'), then run the check again."
)
_MISSING_KEY_HINT = "Paste your Anthropic API key above, then run the check again."


def _truncate(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sdk_version() -> Optional[str]:
    """The installed ``anthropic`` SDK version, or ``None`` when it isn't importable."""
    try:
        import anthropic  # type: ignore
    except Exception:
        return None
    version = getattr(anthropic, "__version__", None)
    if version:
        return str(version)
    try:  # pragma: no cover - only when __version__ is absent
        from importlib.metadata import version as _pkg_version

        return _pkg_version("anthropic")
    except Exception:  # pragma: no cover
        return None


def _stored_key() -> Optional[str]:
    """The user's Anthropic API key from the local secret store (never over HTTP)."""
    try:
        from app.store.secrets import get_anthropic_key
    except Exception:  # pragma: no cover - store always present in-app
        return None
    return get_anthropic_key()


def _base_url() -> str:
    """The Messages API base URL.

    Defaults to the PUBLIC Anthropic API so a pasted user key works with its own
    credentials — deliberately ignoring any ``ANTHROPIC_BASE_URL`` a sandbox/gateway
    may have exported (that gateway 401s a user key; see PHASE2_HANDOFF). Overridable
    via ``YUBEN_ANTHROPIC_BASE_URL`` for self-hosted proxies.
    """
    return os.environ.get("YUBEN_ANTHROPIC_BASE_URL", "https://api.anthropic.com")


def _text_of(response: Any) -> str:
    """Concatenate the ``text`` content blocks of a Messages response."""
    parts: List[str] = []
    for block in getattr(response, "content", None) or []:
        if getattr(block, "type", None) == "text" and getattr(block, "text", None):
            parts.append(block.text)
    return "\n".join(parts)


def _api_error(exc: Exception) -> AdapterError:
    """Typed, plain-language error for a Messages API failure, classified by the
    SDK's own exception classes (never a stack trace)."""
    import anthropic  # type: ignore

    return api_error(exc, anthropic, "Anthropic")


def _api_error_message(exc: Exception) -> str:
    return str(_api_error(exc))


class DirectAnthropicAdapter(AgentAdapter):
    id = "anthropic-api"
    name = "Anthropic API"
    binary = ""  # no CLI — it's an HTTP client
    # The model can't run tools, so the orchestrator feeds it facts + drives the
    # two LLM steps itself (see module docstring / runner.py).
    agentic = False

    def models(self) -> List[str]:
        return list(_MODELS)

    # -- detection (SDK presence stands in for "installed") ------------------
    def detect(self) -> Dict[str, Any]:
        version = _sdk_version()
        return {"installed": version is not None, "version": version}

    # -- live "respond hello" probe (a real, tiny Messages turn) -------------
    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        version = _sdk_version()
        if version is None:
            return self._result(False, None, _INSTALL_HINT)

        key = _stored_key()
        if not key:
            return self._result(False, version, _MISSING_KEY_HINT)

        resolved = self._resolve_model(model)
        try:
            client = self._client(key)
            # Same thinking + cap as the run, so a model that rejects them
            # fails here instead of after YouTube quota is spent. Streamed
            # because the SDK refuses large caps on non-streaming calls.
            with client.with_options(
                timeout=_PING_TIMEOUT, max_retries=1
            ).messages.stream(
                messages=[{"role": "user", "content": "Reply with exactly: hello"}],
                **_request_params(client, resolved),
            ) as stream:
                response = stream.get_final_message()
        except Exception as exc:  # AuthenticationError, APIConnectionError, ...
            return self._result(False, version, _api_error_message(exc))

        out = _text_of(response).strip()
        if not out:
            return self._result(False, version, "Anthropic API returned no text.")
        if "hello" in out.lower():
            return self._result(True, version, "Anthropic API responded ({}).".format(resolved))
        # It answered — just not the literal we asked for. Still proves key + model
        # work, but surface the oddity rather than silently passing.
        return self._result(
            False, version, _truncate("Anthropic API responded unexpectedly: " + out)
        )

    # -- headless run surface (B4) — stream the model's visible text --------
    def stream(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Iterator[str]:
        if _sdk_version() is None:
            raise AdapterError(_INSTALL_HINT, kind=KIND_NOT_INSTALLED)
        key = _stored_key()
        if not key:
            raise AdapterError(
                "No Anthropic API key is stored. Add it in onboarding, then re-run.",
                kind=KIND_AUTH,
            )
        resolved = self._resolve_model(model)
        client = self._client(key)
        return _stream_text(client, resolved, prompt)

    def settings_fingerprint(self, model: str) -> str:
        return "{}|key={}|base={}".format(
            super().settings_fingerprint(model), key_digest(_stored_key()), _base_url()
        )

    # -- helpers -------------------------------------------------------------
    def _resolve_model(self, model: Optional[str]) -> str:
        """Concrete model id for a run.

        The orchestrator's shared stream path calls ``stream(prompt)`` without a
        model, so honor the user's onboarding selection by reading it from the
        stored config (fresh per call → thread-safe across concurrent runs);
        ``"default"``/unset falls back to ``_DEFAULT_MODEL``.
        """
        if model and model != "default":
            return model
        try:
            from app.store import config_store

            cfg_model = config_store.get_config().model
        except Exception:  # pragma: no cover - config always present in-app
            cfg_model = None
        if cfg_model and cfg_model != "default":
            return cfg_model
        return _DEFAULT_MODEL

    def _client(self, key: str) -> Any:
        import anthropic  # type: ignore

        return anthropic.Anthropic(api_key=key, base_url=_base_url())

    def _result(self, ok: bool, version: Optional[str], message: str) -> Dict[str, Any]:
        return {"ok": ok, "adapter": self.id, "version": version, "message": message}


def _model_info(client: Any, model: str) -> Tuple[Optional[int], Optional[bool]]:
    """``(output cap, adaptive thinking supported)`` from the Models API.

    ``(None, None)`` when the lookup fails (offline, old SDK, unknown alias);
    callers then fall back to static defaults. Cached for a few minutes.
    """
    cached = _model_info_cache.get(model)
    if cached and (time.time() - cached[0]) < _MODEL_TTL_SECONDS:
        return cached[1], cached[2]
    try:
        info = client.with_options(
            timeout=_MODEL_FETCH_TIMEOUT, max_retries=0
        ).models.retrieve(model)
    except Exception:
        return None, None
    cap = getattr(info, "max_tokens", None)
    cap = cap if isinstance(cap, int) and cap > 0 else None
    # SDK releases differ: some type ``capabilities`` as models, others as a
    # plain dict. Walk either.
    node: Any = getattr(info, "capabilities", None)
    for key in ("thinking", "types", "adaptive", "supported"):
        node = node.get(key) if isinstance(node, dict) else getattr(node, key, None)
    adaptive: Optional[bool] = node if isinstance(node, bool) else None
    _model_info_cache[model] = (time.time(), cap, adaptive)
    return cap, adaptive


def _request_params(client: Any, model: str) -> Dict[str, Any]:
    """Model, output cap and thinking config for one Messages request.

    Adaptive thinking is sent only to models that take it: Claude Haiku 4.5 and
    other pre-4.6 models reject it. The cap is the model's own maximum (Models
    API) unless ``YUBEN_MAX_OUTPUT_TOKENS`` overrides it.
    """
    api_cap, adaptive = _model_info(client, model)
    if adaptive is None:
        adaptive = not model.startswith(_NO_ADAPTIVE_PREFIXES)
    params: Dict[str, Any] = {
        "model": model,
        "max_tokens": output_cap_override() or api_cap or _FALLBACK_MAX_TOKENS,
    }
    if adaptive:
        params["thinking"] = {"type": "adaptive"}
    return params


def _stream_text(client: Any, model: str, prompt: str) -> Iterator[str]:
    """Yield the visible text of one streamed Messages request, one LINE at a time.

    ``text_stream`` yields only ``text_delta`` content (not thinking), but at
    arbitrary token boundaries. B4's ``StreamCollector`` strips each item and
    re-joins with ``"\\n"``, so yielding raw deltas could split a JSON string and
    inject a raw newline (invalid JSON). We therefore buffer deltas and emit
    complete lines — a JSON string never spans a newline, so line boundaries are
    always safe and the collector reconstructs the object losslessly. Adaptive
    thinking is on for analysis quality where the model supports it (see
    :func:`_request_params`); it never reaches the stream because display
    defaults to omitted. A ``max_tokens`` stop reason raises
    :class:`OutputTruncated`.

    A generator so B4's cancel path (``stream.close()`` → ``GeneratorExit``) exits
    the ``with`` block and tears down the SDK stream. Any API failure surfaces as
    an ``AdapterError`` the orchestrator classifies.
    """
    buffer = ""
    stop_reason = None
    try:
        with client.messages.stream(
            messages=[{"role": "user", "content": prompt}],
            **_request_params(client, model),
        ) as stream:
            for text in stream.text_stream:
                if not text:
                    continue
                buffer += text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    yield line
            final = getattr(stream, "get_final_message", None)
            if callable(final):
                stop_reason = getattr(final(), "stop_reason", None)
            if buffer and stop_reason != "max_tokens":
                yield buffer
    except GeneratorExit:  # cooperative cancel — let the with-block close the stream
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the orchestrator
        raise _api_error(exc) from exc
    if stop_reason == "max_tokens":
        raise OutputTruncated("Claude")
