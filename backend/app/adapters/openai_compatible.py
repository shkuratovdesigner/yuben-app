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
* check_env: a cheap real "reply hello" completion against the provider.
* stream   : one streamed completion, yielded line-by-line for B4's collector.

MODEL LISTS ARE FETCHED LIVE. Hardcoding ids guarantees they rot — every
provider here exposes ``GET /v1/models``, so we ask, cache for a few minutes,
and fall back to a small static list only when the fetch cannot happen (offline,
or no key stored yet). OpenRouter's and Ollama's endpoints need no credential at
all, so their lists are always live.

The ``openai`` import is LAZY in every method so this module loads even when the
SDK is absent — the same importable-or-not discipline as ``store/secrets.py``.
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from app.adapters.base import AdapterError, AgentAdapter, run_version, which

# One tiny real turn; headroom for cold DNS + a round-trip.
_PING_TIMEOUT = 60.0
_PING_MAX_TOKENS = 32
_STREAM_MAX_TOKENS = 32000

# Live model lists are cached per adapter id — GET /api/adapters hits models()
# for every adapter on every call, and none of these lists move minute to minute.
_MODEL_TTL_SECONDS = 300.0
_MODEL_FETCH_TIMEOUT = 3.0
_model_cache: Dict[str, Tuple[float, List[str]]] = {}

_SDK_HINT = (
    "The 'openai' Python SDK isn't installed on the backend. Run "
    "'pip install openai' (or 'make install'), then run the check again."
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


def _api_error_message(exc: Exception, provider: str) -> str:
    """Plain-language message for a completion failure (never a stack trace)."""
    name = type(exc).__name__
    detail = getattr(exc, "message", None) or str(exc)
    if "Authentication" in name or "PermissionDenied" in name:
        return "{} rejected the API key. Check that it's correct and active.".format(provider)
    if "NotFound" in name:
        return "That model isn't available on {}. Pick another model.".format(provider)
    if "RateLimit" in name:
        return "{}'s rate limit was hit. Wait a moment and try again.".format(provider)
    if "Connection" in name or "Timeout" in name:
        return "Couldn't reach {}. Check your connection and try again.".format(provider)
    return _truncate("{} API error: {}".format(provider, detail))


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

    def _stored_key(self) -> Optional[str]:  # pragma: no cover - overridden
        raise NotImplementedError

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
            live = self._models_live()
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
        try:
            client = self._client(key)
            response = client.with_options(
                timeout=_PING_TIMEOUT, max_retries=1
            ).chat.completions.create(
                model=resolved,
                max_tokens=_PING_MAX_TOKENS,
                messages=[{"role": "user", "content": "Reply with exactly: hello"}],
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
            raise AdapterError(_SDK_HINT)
        key = self._stored_key()
        if self.requires_key and not key:
            raise AdapterError(self.key_hint)
        return _stream_text(
            self._client(key), self._resolve_model(model), prompt, self.provider_label
        )

    # -- helpers -------------------------------------------------------------
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


def _stream_text(client: Any, model: str, prompt: str, provider: str) -> Iterator[str]:
    """Yield one streamed completion's visible text, one LINE at a time.

    Line buffering matters for the same reason as the Anthropic adapter: B4's
    ``StreamCollector`` strips each item and re-joins with "\\n", so emitting raw
    token deltas could split a JSON string and inject a newline (invalid JSON).
    A JSON string never spans a newline, so line boundaries are always safe.

    A generator so B4's cancel path (``stream.close()`` → ``GeneratorExit``)
    tears the HTTP stream down.
    """
    buffer = ""
    stream = None
    try:
        stream = client.chat.completions.create(
            model=model,
            max_tokens=_STREAM_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
            stream=True,
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            text = getattr(delta, "content", None) if delta else None
            if not text:
                continue
            buffer += text
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line
        if buffer:
            yield buffer
    except GeneratorExit:  # cooperative cancel — close the HTTP stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        raise
    except Exception as exc:  # noqa: BLE001 - classified by the orchestrator
        raise AdapterError(_api_error_message(exc, provider)) from exc


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

    def _stored_key(self) -> Optional[str]:
        return _get("get_openai_key")()


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
        # the picker is useful during onboarding.
        if _sdk_version() is None:
            return []
        client = self._client(self._stored_key() or "public")
        page = client.with_options(timeout=_MODEL_FETCH_TIMEOUT, max_retries=0).models.list()
        ids = [str(m.id) for m in getattr(page, "data", []) or [] if getattr(m, "id", None)]
        return sorted(ids)


class OllamaAdapter(OpenAICompatibleAdapter):
    """Ollama — local models, no key, no cloud, no cost.

    Detection keys off the ``ollama`` binary rather than the SDK, because the SDK
    being importable says nothing about whether a local daemon exists.
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

    def check_env(self, model: Optional[str] = None) -> Dict[str, Any]:
        if not which(self.binary):
            return self._result(
                False,
                None,
                "We couldn't find Ollama. Install it from https://ollama.com, "
                "run 'ollama serve', then run the check again.",
            )
        return super().check_env(model)
