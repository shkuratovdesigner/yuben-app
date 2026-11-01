"""OpenAI-compatible API adapters — OpenAI, OpenRouter and Ollama.

All three speak the same wire protocol (``/v1/chat/completions``), so they share
one base class and differ only in base URL, credential source and model list.
That is the whole reason this file covers three providers in the space the
Anthropic adapter needed for one.

Like :mod:`app.adapters.direct_anthropic`, these are **not agentic**: the model
never runs the research scripts. ``run_pipeline`` still produces every fact and
the adapter carries only narrative, so the HARD TRUST RULE (PRD §8 / CONTRACTS
§7) is untouched.

* detect   : the ``openai`` SDK importable (plus the ``ollama`` binary for local).
* check_env: a cheap real "reply hello" completion, with the same output cap and
             output format mode as a run.
* stream   : one streamed completion, yielded line-by-line. The narrative step
             asks for schema-valid JSON (``response_format``) where the model
             supports it: ``json_schema`` (strict), else ``json_object``.

Ollama is the exception on the wire: it uses Ollama's native ``/api/chat``,
because only that endpoint can set the context size (``num_ctx``). The OpenAI-
compatible endpoint silently cuts a long prompt to the model's small default.

MODEL LISTS ARE FETCHED LIVE. Hardcoding ids guarantees they rot — every
provider here exposes ``GET /v1/models``, so we ask, cache for a few minutes,
and fall back to a small static list only when the fetch cannot happen (offline,
or no key stored yet). OpenRouter's and Ollama's endpoints need no credential at
all, so their lists are always live. Lists are filtered to models that can write
a report: embedding, speech, image and similar models are left out.

The ``openai`` import is LAZY in every method so this module loads even when the
SDK is absent — the same importable-or-not discipline as ``store/secrets.py``.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from app import diagnostics
from app.adapters.base import (
    AdapterError,
    KIND_AUTH,
    KIND_BAD_REQUEST,
    KIND_CONTEXT_TOO_LONG,
    KIND_MODEL_NOT_FOUND,
    KIND_NETWORK,
    KIND_NOT_INSTALLED,
    KIND_SERVER,
    KIND_UNKNOWN,
    NARRATIVE_OUTPUT_RESERVE,
    estimate_tokens,
    api_error,
    key_digest,
    AgentAdapter,
    OutputTruncated,
    output_cap_override,
    run_version,
    which,
)
from app.adapters.structured import (
    AGENT_RESULT_SCHEMA_NAME,
    PLAIN_PROBE_PROMPT,
    PROBE_PROMPT,
    PROBE_SCHEMA,
    PROBE_SCHEMA_NAME,
    agent_result_schema,
    wants_agent_result,
)

#: ``response_format`` modes, strongest first. ``None`` sends no format.
FORMAT_JSON_SCHEMA = "json_schema"
FORMAT_JSON_OBJECT = "json_object"
_DOWNGRADE = {FORMAT_JSON_SCHEMA: FORMAT_JSON_OBJECT, FORMAT_JSON_OBJECT: None}
#: A 400 naming one of these rejected the format, not the prompt: retry weaker.
_FORMAT_ERROR_HINTS = ("response_format", "json_schema", "json_object", "structured", "schema")

# One tiny real turn; headroom for cold DNS + a round-trip.
_PING_TIMEOUT = 60.0
# No output cap is sent by default: a fixed value is wrong for some model
# (GPT-4o accepts at most 16,384), and each model already defaults to its own
# maximum. YUBEN_MAX_OUTPUT_TOKENS sets one when a provider needs it.

# Live model lists are cached per adapter id — GET /api/adapters hits models()
# for every adapter on every call, and none of these lists move minute to minute.
_MODEL_TTL_SECONDS = 300.0
_MODEL_FETCH_TIMEOUT = 3.0
_model_cache: Dict[str, Tuple[float, List[str]]] = {}
# Per-model metadata some providers return with the list (OpenRouter: context
# length, supported parameters, modalities), keyed by adapter id then model id.
_model_meta: Dict[str, Dict[str, Dict[str, Any]]] = {}

_SDK_HINT = (
    "The 'openai' Python SDK isn't installed on the backend. Run "
    "'pip install openai' (or 'python yuben.py install'), then run the check again."
)


def _truncate(text: str, limit: int = 240) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sdk_version() -> Optional[str]:
    """The installed ``openai`` SDK version, or ``None`` when not importable."""
    try:
        import openai  # type: ignore
    except Exception:
        return None
    version = getattr(openai, "__version__", None)
    if version:
        return str(version)
    try:  # pragma: no cover - only when __version__ is absent
        from importlib.metadata import version as _pkg_version

        return _pkg_version("openai")
    except Exception:  # pragma: no cover
        return None


def _api_error(exc: Exception, provider: str) -> AdapterError:
    """Typed, plain-language error for a completion failure (never a stack trace)."""
    import openai  # type: ignore

    return api_error(exc, openai, provider)


def _api_error_message(exc: Exception, provider: str) -> str:
    return str(_api_error(exc, provider))


def _response_format(
    mode: Optional[str], schema: Optional[Dict[str, Any]], name: str
) -> Dict[str, Any]:
    """``response_format`` request field for ``mode`` (empty for ``None``)."""
    if mode == FORMAT_JSON_SCHEMA and schema is not None:
        return {
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            }
        }
    if mode in (FORMAT_JSON_SCHEMA, FORMAT_JSON_OBJECT):
        return {"response_format": {"type": "json_object"}}
    return {}


def _rejects_format(exc: Exception) -> bool:
    """A 400 that blames ``response_format`` rather than the prompt or model."""
    try:
        import openai  # type: ignore
    except Exception:  # pragma: no cover - SDK checked before any request
        return False
    if not isinstance(exc, openai.BadRequestError):
        return False
    text = str(getattr(exc, "message", None) or exc).lower()
    return any(hint in text for hint in _FORMAT_ERROR_HINTS)


def _create(
    client: Any,
    kwargs: Dict[str, Any],
    mode: Optional[str],
    schema: Optional[Dict[str, Any]],
    name: str,
) -> Any:
    """``chat.completions.create`` with the strongest format the model accepts.

    Starts at ``mode``; when the provider rejects that format with a 400, steps
    down (``json_schema`` → ``json_object`` → none) and retries. The request
    fails before any output, so a retry never duplicates text. Used by the check
    and the run alike, so both end up with the same format.
    """
    while True:
        try:
            response = client.chat.completions.create(
                **kwargs, **_response_format(mode, schema, name)
            )
            diagnostics.note(
                request={
                    **diagnostics.summarize_params(
                        {k: v for k, v in kwargs.items() if k != "messages"}
                    ),
                    "response_format": mode or "none",
                }
            )
            return response
        except Exception as exc:
            if mode is None or not _rejects_format(exc):
                raise
            mode = _DOWNGRADE[mode]


class OpenAICompatibleAdapter(AgentAdapter):
    """Shared behaviour for any provider speaking the OpenAI chat-completions API.

    Subclasses set the class attributes below; nothing else needs overriding
    unless the provider is unusual (Ollama overrides ``detect``/``_models_live``
    because it is a local daemon rather than a hosted API).
    """

    # -- subclass contract ---------------------------------------------------
    id = ""
    name = ""
    binary = ""  # no CLI — it's an HTTP client
    agentic = False

    #: Default API base. Overridable per-provider via the env var in ``base_url_env``.
    base_url = ""
    base_url_env = ""
    #: Human label used in error messages ("OpenAI", "OpenRouter", …).
    provider_label = ""
    #: Model used when the user leaves the picker on "default".
    default_model = ""
    #: Shown only when the live fetch can't run (offline / no key yet).
    fallback_models: List[str] = ["default"]
    #: False for providers that need no credential (Ollama).
    requires_key = True
    #: Where to get a key, surfaced in the "no key stored" hint.
    key_hint = ""
    #: Request field for the output cap. OpenAI's reasoning models reject
    #: ``max_tokens``; ``max_completion_tokens`` works on all its chat models.
    cap_param = "max_tokens"
    #: Lower-cased substrings of model ids that can't write a report.
    non_chat_markers: Tuple[str, ...] = ("embed",)

    def _stored_key(self) -> Optional[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    def _format_mode(self, model: str) -> Optional[str]:
        """Strongest ``response_format`` this model is known to take.

        ``None`` (the default) sends none and relies on the prompt and parser.
        """
        return None

    def _is_chat_model(self, model_id: str) -> bool:
        """Whether a listed model can write the report (picker filter)."""
        lowered = model_id.lower()
        return not any(marker in lowered for marker in self.non_chat_markers)

    # -- configuration -------------------------------------------------------
    def _base_url(self) -> str:
        if self.base_url_env:
            return os.environ.get(self.base_url_env, self.base_url)
        return self.base_url

    def _client(self, key: Optional[str]) -> Any:
        from openai import OpenAI  # type: ignore

        # Providers that need no credential still require a non-empty string.
        return OpenAI(api_key=key or "not-needed", base_url=self._base_url())

    # -- detection -----------------------------------------------------------
    def detect(self) -> Dict[str, Any]:
        version = _sdk_version()
        return {"installed": version is not None, "version": version}

    # -- models (live, cached) ----------------------------------------------
    def models(self) -> List[str]:
        """Current model ids, newest fetch preferred, static fallback otherwise."""
        cached = _model_cache.get(self.id)
        if cached and (time.time() - cached[0]) < _MODEL_TTL_SECONDS:
            return list(cached[1])
        try:
            live = [m for m in self._models_live() if self._is_chat_model(m)]
        except Exception:
            live = []
        result = ["default"] + live if live else list(self.fallback_models)
        if live:
            _model_cache[self.id] = (time.time(), result)
        return result

    def _models_live(self) -> List[str]:
        """Ask the provider for its model ids. Empty list ⇒ use the fallback."""
        if _sdk_version() is None:
            return []
        key = self._stored_key()
        if self.requires_key and not key:
            return []
        client = self._client(key)
        page = client.with_options(timeout=_MODEL_FETCH_TIMEOUT, max_retries=0).models.list()
        ids = [str(m.id) for m in getattr(page, "data", []) or [] if getattr(m, "id", None)]
        return sorted(ids)

    # -- live "respond hello" probe -----------------------------------------
    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        version = _sdk_version()
        if version is None:
            return self._result(False, None, _SDK_HINT)

        key = self._stored_key()
        if self.requires_key and not key:
            return self._result(False, version, self.key_hint)

        resolved = self._resolve_model(model)
        mode = self._format_mode(resolved)
        prompt = PROBE_PROMPT if mode else PLAIN_PROBE_PROMPT
        try:
            client = self._client(key)
            response = _create(
                client.with_options(timeout=_PING_TIMEOUT, max_retries=1),
                {
                    "model": resolved,
                    "messages": [{"role": "user", "content": prompt}],
                    **self._cap_kwargs(),
                },
                mode,
                PROBE_SCHEMA,
                PROBE_SCHEMA_NAME,
            )
        except Exception as exc:
            return self._result(False, version, _api_error_message(exc, self.provider_label))

        out = _text_of(response).strip()
        if not out:
            return self._result(False, version, "{} returned no text.".format(self.provider_label))
        if "hello" in out.lower():
            return self._result(
                True, version, "{} responded ({}).".format(self.provider_label, resolved)
            )
        # It answered — just not the literal we asked for. Still proves key +
        # model work, but surface the oddity rather than silently passing.
        return self._result(
            False,
            version,
            _truncate("{} responded unexpectedly: {}".format(self.provider_label, out)),
        )

    # -- headless run surface (B4) ------------------------------------------
    def stream(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Iterator[str]:
        if _sdk_version() is None:
            raise AdapterError(_SDK_HINT, kind=KIND_NOT_INSTALLED)
        key = self._stored_key()
        if self.requires_key and not key:
            raise AdapterError(self.key_hint, kind=KIND_AUTH)
        resolved = self._resolve_model(model)
        narrative = wants_agent_result(prompt)
        return _stream_text(
            self._client(key),
            resolved,
            prompt,
            self.provider_label,
            self._cap_kwargs(),
            mode=self._format_mode(resolved) if narrative else None,
            schema=agent_result_schema() if narrative else None,
        )

    def settings_fingerprint(self, model: str) -> str:
        return "{}|key={}|base={}".format(
            super().settings_fingerprint(model), key_digest(self._stored_key()), self._base_url()
        )

    # -- helpers -------------------------------------------------------------
    def _cap_kwargs(self) -> Dict[str, int]:
        """Output-cap request fields, shared by the check and the run so the
        check tests the request the run makes. Empty unless overridden."""
        cap = output_cap_override()
        return {self.cap_param: cap} if cap else {}

    def _resolve_model(self, model: Optional[str]) -> str:
        """Concrete model id for a run.

        Mirrors DirectAnthropicAdapter: the orchestrator's shared stream path
        calls ``stream(prompt)`` without a model, so honor the user's onboarding
        selection by reading it from the stored config (fresh per call →
        thread-safe across concurrent runs); "default"/unset falls back.
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
        return self.default_model

    def _result(self, ok: bool, version: Optional[str], message: str) -> Dict[str, Any]:
        return {"ok": ok, "adapter": self.id, "version": version, "message": message}


def _text_of(response: Any) -> str:
    """First choice's message content, or ''."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    return getattr(message, "content", None) or ""


def _stream_text(
    client: Any,
    model: str,
    prompt: str,
    provider: str,
    cap_kwargs: Optional[Dict[str, int]] = None,
    *,
    mode: Optional[str] = None,
    schema: Optional[Dict[str, Any]] = None,
) -> Iterator[str]:
    """Yield one streamed completion's visible text, one LINE at a time.

    Same line contract as the Anthropic adapter: deltas are buffered into whole
    lines, which B4 re-joins with "\\n" and parses once. ``mode``/``schema``
    (narrative step only) choose the ``response_format``; see :func:`_create`.

    A generator so B4's cancel path (``stream.close()`` → ``GeneratorExit``)
    tears the HTTP stream down. A ``length`` finish reason raises
    :class:`OutputTruncated`, so a cut-off answer is not reported as "no JSON".
    """
    buffer = ""
    stream = None
    finish_reason = None
    try:
        stream = _create(
            client,
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
                **(cap_kwargs or {}),
            },
            mode,
            schema,
            AGENT_RESULT_SCHEMA_NAME,
        )
        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None:
                diagnostics.note(usage=usage)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            finish_reason = getattr(choices[0], "finish_reason", None) or finish_reason
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta else None
            if not text:
                continue
            buffer += text
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line
        diagnostics.note(stop_reason=finish_reason)
        if buffer and finish_reason != "length":
            yield buffer
    except GeneratorExit:  # cooperative cancel — close the HTTP stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the orchestrator
        raise _api_error(exc, provider) from exc
    if finish_reason == "length":
        raise OutputTruncated(provider)


# --------------------------------------------------------------------------- #
# Concrete providers
# --------------------------------------------------------------------------- #


def _get(name: str) -> Callable[[], Optional[str]]:
    """Late-bound secret reader (keeps this module importable without the store)."""

    def _read() -> Optional[str]:
        try:
            from app.store import secrets
        except Exception:  # pragma: no cover - store always present in-app
            return None
        return getattr(secrets, name)()

    return _read


class OpenAIAdapter(OpenAICompatibleAdapter):
    """The OpenAI API — paste a key, no terminal."""

    id = "openai-api"
    name = "OpenAI API"
    base_url = "https://api.openai.com/v1"
    base_url_env = "YUBEN_OPENAI_BASE_URL"
    provider_label = "OpenAI"
    default_model = "gpt-4o-mini"
    fallback_models = ["default", "gpt-4o", "gpt-4o-mini"]
    key_hint = "Paste your OpenAI API key above, then run the check again."
    cap_param = "max_completion_tokens"
    # Listed by /v1/models but not chat-completions report writers: embeddings,
    # speech, images, moderation, legacy completions and Responses-only models.
    non_chat_markers = (
        "embedding", "tts", "whisper", "transcribe", "audio", "realtime",
        "dall-e", "image", "sora", "moderation", "search", "computer-use",
        "codex", "deep-research", "-instruct", "-pro",
    )

    def _stored_key(self) -> Optional[str]:
        return _get("get_openai_key")()

    def _is_chat_model(self, model_id: str) -> bool:
        return bool(_OPENAI_CHAT_IDS.match(model_id)) and super()._is_chat_model(model_id)

    def _format_mode(self, model: str) -> Optional[str]:
        # Strict json_schema arrived with gpt-4o-2024-08-06; older chat models
        # take json_object. A 400 on anything else still steps down (_create).
        if model == "gpt-4" or model.startswith(_OPENAI_JSON_OBJECT_ONLY):
            return FORMAT_JSON_OBJECT
        return FORMAT_JSON_SCHEMA


class GeminiAdapter(OpenAICompatibleAdapter):
    """Google Gemini via its OpenAI-compatible endpoint — paste a key, no terminal.

    Uses Google's official OpenAI-compatibility surface, so no google SDK is
    needed and streaming/error handling are identical to the other presets.
    """

    id = "gemini-api"
    name = "Google Gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
    base_url_env = "YUBEN_GEMINI_BASE_URL"
    provider_label = "Google Gemini"
    default_model = "gemini-2.5-flash"
    fallback_models = ["default", "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
    key_hint = "Paste your Gemini API key above, then run the check again."
    non_chat_markers = (
        "embed", "imagen", "veo", "aqa", "tts", "image", "audio", "live",
        "robotics", "computer-use",
    )

    def _stored_key(self):
        return _get("get_gemini_key")()

    def _format_mode(self, model: str) -> Optional[str]:
        # Gemini 2 and later take a JSON schema through the compatibility
        # endpoint; Gemma and older models get the prompt alone.
        match = _GEMINI_VERSION.match(model)
        if match and int(match.group(1)) >= 2:
            return FORMAT_JSON_SCHEMA
        return None


class OpenRouterAdapter(OpenAICompatibleAdapter):
    """OpenRouter — one key, hundreds of models across every major vendor.

    The single biggest lever for "as many models as possible": the model list is
    fetched live from a PUBLIC endpoint, so the picker shows whatever OpenRouter
    currently routes to, without this file ever being edited again.
    """

    id = "openrouter"
    name = "OpenRouter"
    base_url = "https://openrouter.ai/api/v1"
    base_url_env = "YUBEN_OPENROUTER_BASE_URL"
    provider_label = "OpenRouter"
    default_model = "openai/gpt-4o-mini"
    fallback_models = ["default"]
    key_hint = "Paste your OpenRouter API key above, then run the check again."

    def _stored_key(self) -> Optional[str]:
        return _get("get_openrouter_key")()

    def _models_live(self) -> List[str]:
        # OpenRouter's /models is public — list models before a key is stored so
        # the picker is useful during onboarding. Each entry also carries its
        # context length, supported parameters and modalities; keep those.
        if _sdk_version() is None:
            return []
        client = self._client(self._stored_key() or "public")
        page = client.with_options(timeout=_MODEL_FETCH_TIMEOUT, max_retries=0).models.list()
        meta: Dict[str, Dict[str, Any]] = {}
        for m in getattr(page, "data", []) or []:
            if getattr(m, "id", None):
                meta[str(m.id)] = _as_dict(m)
        _model_meta[self.id] = meta
        return sorted(meta)

    def _meta(self, model: str) -> Dict[str, Any]:
        if self.id not in _model_meta:
            self.models()  # fills the metadata as a side effect
        return _model_meta.get(self.id, {}).get(model, {})

    def _is_chat_model(self, model_id: str) -> bool:
        outputs = (self._meta(model_id).get("architecture") or {}).get("output_modalities")
        if isinstance(outputs, list) and "text" not in outputs:
            return False
        return super()._is_chat_model(model_id)

    def _format_mode(self, model: str) -> Optional[str]:
        # Sent only to models that list support (OpenRouter /models).
        supported = self._meta(model).get("supported_parameters") or []
        if "structured_outputs" in supported:
            return FORMAT_JSON_SCHEMA
        if "response_format" in supported:
            return FORMAT_JSON_OBJECT
        return None

    def context_window(self, model: Optional[str] = None) -> Optional[int]:
        try:
            value = self._meta(self._resolve_model(model)).get("context_length")
        except Exception:
            return None
        return value if isinstance(value, int) and value > 0 else None


class OllamaAdapter(OpenAICompatibleAdapter):
    """Ollama — local models, no key, no cloud, no cost.

    Detection keys off the ``ollama`` binary rather than the SDK, because the SDK
    being importable says nothing about whether a local daemon exists.

    Check and run use Ollama's native ``/api/chat``, not the OpenAI-compatible
    endpoint: only the native one takes ``num_ctx``. Many installs default to a
    2–4K context, and the narrative prompt is ~10K tokens, so without it the
    prompt is cut silently. ``num_ctx`` is sized from the prompt, up to the
    model's own maximum from ``/api/show``. The narrative also sends the
    AgentResult schema as Ollama's ``format``.
    """

    id = "ollama"
    name = "Ollama"
    binary = "ollama"
    base_url = "http://localhost:11434/v1"
    base_url_env = "YUBEN_OLLAMA_BASE_URL"
    provider_label = "Ollama"
    # Only a hint: Ollama can run any model, and which ones exist is entirely up
    # to what the user has pulled — see _resolve_model, which prefers those.
    default_model = "llama3.2"
    fallback_models = ["default"]
    requires_key = False
    key_hint = ""
    non_chat_markers = ("embed", "bge-", "minilm", "rerank")

    def _stored_key(self) -> Optional[str]:
        return None

    def _resolve_model(self, model: Optional[str]) -> str:
        """Prefer a model the user has actually pulled.

        Every other provider can assume its default id exists; Ollama can't —
        the local library is whatever ``ollama pull`` was run for, so a static
        default 404s on most machines. Fall back to the first installed model
        and only then to the static hint.
        """
        resolved = super()._resolve_model(model)
        if resolved != self.default_model:
            return resolved
        local = [m for m in self.models() if m != "default"]
        return local[0] if local else self.default_model

    def detect(self) -> Dict[str, Any]:
        path = which(self.binary)
        if not path:
            return {"installed": False, "version": None}
        return {"installed": True, "version": run_version(path, timeout=10.0)}

    def _native_url(self) -> str:
        """The daemon root (``/api/...``) behind the configured ``/v1`` base."""
        return re.sub(r"/v1/?$", "", self._base_url().rstrip("/"))

    def context_window(self, model: Optional[str] = None) -> Optional[int]:
        """The model's maximum context from ``/api/show`` (cached)."""
        try:
            resolved = self._resolve_model(model)
        except Exception:
            return None
        cached = _ollama_context.get(resolved)
        if cached and (time.time() - cached[0]) < _MODEL_TTL_SECONDS:
            return cached[1]
        try:
            import httpx

            response = httpx.post(
                self._native_url() + "/api/show",
                json={"model": resolved},
                timeout=_MODEL_FETCH_TIMEOUT,
            )
            response.raise_for_status()
            info = response.json().get("model_info") or {}
        except Exception:
            return None
        window = next(
            (
                value
                for key, value in info.items()
                if key.endswith(".context_length") and isinstance(value, int) and value > 0
            ),
            None,
        )
        if window:
            _ollama_context[resolved] = (time.time(), window)
        return window

    def _options(self, prompt: str, model: str) -> Dict[str, Any]:
        """``num_ctx`` for the prompt plus answer room, and the output cap."""
        needed = estimate_tokens(prompt) + NARRATIVE_OUTPUT_RESERVE
        num_ctx = max(_OLLAMA_MIN_CTX, -(-needed // 2048) * 2048)
        window = self.context_window(model)
        if window:
            num_ctx = min(num_ctx, window)
        options: Dict[str, Any] = {"num_ctx": num_ctx}
        cap = output_cap_override()
        if cap:
            options["num_predict"] = cap
        return options

    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        if not which(self.binary):
            return self._result(
                False,
                None,
                "We couldn't find Ollama. Install it from https://ollama.com, "
                "run 'ollama serve', then run the check again.",
            )
        version = run_version(which(self.binary) or self.binary, timeout=10.0)
        resolved = self._resolve_model(model)
        try:
            out = "".join(
                _ollama_chat(
                    self._native_url(),
                    resolved,
                    PROBE_PROMPT,
                    self._options(PROBE_PROMPT, resolved),
                    PROBE_SCHEMA,
                    timeout=_PING_TIMEOUT,
                )
            ).strip()
        except AdapterError as exc:
            return self._result(False, version, str(exc))
        if not out:
            return self._result(False, version, "Ollama returned no text.")
        if "hello" in out.lower():
            return self._result(True, version, "Ollama responded ({}).".format(resolved))
        return self._result(
            False, version, _truncate("Ollama responded unexpectedly: {}".format(out))
        )

    def stream(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
    ) -> Iterator[str]:
        resolved = self._resolve_model(model)
        schema = agent_result_schema() if wants_agent_result(prompt) else None
        return _ollama_chat(
            self._native_url(), resolved, prompt, self._options(prompt, resolved), schema
        )


# Ollama defaults to 2–4K on many installs; never ask for less than this.
_OLLAMA_MIN_CTX = 8192
# Generous: a local model on a laptop can take minutes to load and answer.
_OLLAMA_TIMEOUT = 900.0
_ollama_context: Dict[str, Tuple[float, int]] = {}


def _ollama_error(status: int, body: str) -> AdapterError:
    """Typed error for a failed ``/api/chat`` call."""
    try:
        detail = str(json.loads(body).get("error") or body)
    except Exception:
        detail = body
    detail = _truncate(detail or "HTTP {}".format(status))
    lowered = detail.lower()
    if status == 404 or "not found" in lowered:
        return AdapterError(
            "That model isn't pulled in Ollama. Run 'ollama pull <model>' or pick "
            "another model.",
            kind=KIND_MODEL_NOT_FOUND,
        )
    if "context" in lowered and ("exceed" in lowered or "too long" in lowered):
        return AdapterError(
            "The research prompt is longer than this model's context window. "
            "Pick a model with a larger context window.",
            kind=KIND_CONTEXT_TOO_LONG,
        )
    if status >= 500:
        return AdapterError("Ollama failed: {}".format(detail), kind=KIND_SERVER)
    if status >= 400:
        return AdapterError("Ollama rejected the request: {}".format(detail), kind=KIND_BAD_REQUEST)
    return AdapterError("Ollama error: {}".format(detail), kind=KIND_UNKNOWN)


def _ollama_chat(
    root: str,
    model: str,
    prompt: str,
    options: Dict[str, Any],
    schema: Optional[Dict[str, Any]] = None,
    *,
    timeout: float = _OLLAMA_TIMEOUT,
) -> Iterator[str]:
    """Stream one native ``/api/chat`` answer, one LINE at a time.

    Same line contract as :func:`_stream_text`. Ollama streams NDJSON: each line
    carries ``message.content``; the last has ``done: true`` and a
    ``done_reason``, where ``length`` means the answer hit the cap.
    """
    import httpx

    body: Dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "options": options,
    }
    if schema is not None:
        body["format"] = schema
    diagnostics.note(
        request=diagnostics.summarize_params({k: v for k, v in body.items() if k != "messages"})
    )
    buffer = ""
    done_reason = None
    try:
        with httpx.stream(
            "POST", root + "/api/chat", json=body, timeout=httpx.Timeout(timeout, connect=10.0)
        ) as response:
            if response.status_code >= 400:
                raise _ollama_error(response.status_code, response.read().decode("utf-8", "replace"))
            for raw in response.iter_lines():
                if not raw.strip():
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if event.get("error"):
                    raise _ollama_error(0, json.dumps(event))
                text = (event.get("message") or {}).get("content") or ""
                if text:
                    buffer += text
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        yield line
                if event.get("done"):
                    done_reason = event.get("done_reason")
                    diagnostics.note(
                        stop_reason=done_reason,
                        usage={
                            k: event.get(k)
                            for k in ("prompt_eval_count", "eval_count", "total_duration")
                            if k in event
                        },
                    )
                    break
        if buffer and done_reason != "length":
            yield buffer
    except GeneratorExit:  # cooperative cancel — the with-block closes the stream
        raise
    except AdapterError:
        raise
    except httpx.TimeoutException as exc:
        raise AdapterError(
            "Ollama didn't answer in time. The model may still be loading; try again.",
            kind=KIND_NETWORK,
        ) from exc
    except httpx.TransportError as exc:
        raise AdapterError(
            "Couldn't reach Ollama. Make sure 'ollama serve' is running.", kind=KIND_NETWORK
        ) from exc
    if done_reason == "length":
        raise OutputTruncated("Ollama")


def _as_dict(obj: Any) -> Dict[str, Any]:
    """A listed model as a plain dict, including provider-specific fields."""
    if isinstance(obj, dict):
        return obj
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        try:
            return dict(dump())
        except Exception:
            pass
    return dict(getattr(obj, "__dict__", {}) or {})


# OpenAI chat models: gpt-*, chatgpt-*, the o-series and fine-tunes of them.
_OPENAI_CHAT_IDS = re.compile(r"^(ft:)?(gpt-|chatgpt-|o\d)")
# Chat models that predate strict json_schema output.
_OPENAI_JSON_OBJECT_ONLY = ("gpt-3.5", "gpt-4-", "gpt-4o-2024-05-13")
# "gemini-2.5-flash" or "models/gemini-2.5-flash" -> major version 2.
_GEMINI_VERSION = re.compile(r"^(?:models/)?gemini-(\d+)")
