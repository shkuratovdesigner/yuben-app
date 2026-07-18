"""Config router (B1) — CONTRACTS.md §1 / §6, PRD FR-1.

Endpoints:
  GET  /api/config           -> Config
  PUT  /api/config           -> Config   (partial update of adapter/model/settings)
  POST /api/config/key       -> {"ok": true}    (write-only YouTube key store)
  POST /api/config/env-check -> EnvCheckResult   (adapter probe; B2 wires it)
  POST /api/config/key-test  -> KeyTestResult    (one cheap YT call; B3 wires it)

Secrets rule (PRD §8): the YouTube key is write-only through the API — never
returned, logged, or placed in a URL / query string. The env-check and key-test
endpoints delegate to the adapter/pipeline layers via DEFENSIVE imports so this
router works standalone in Wave 1 and "lights up" once B2/B3 land in Wave 2.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from contracts.python.models import Config

from app.store import config_store, secrets

router = APIRouter(prefix="/api", tags=["config"])


# --- request / response models not present in contracts/python/models.py ----
class ConfigUpdate(BaseModel):
    """PUT body. Lenient (``extra="ignore"``): an echoed ``youtube_key_present``
    or ``schema_version`` is ignored; only the fields below are persisted."""

    model_config = ConfigDict(extra="ignore")

    adapter: Optional[str] = None
    model: Optional[str] = None
    onboarding_complete: Optional[bool] = None
    settings: Optional[Dict[str, Any]] = None


class KeyBody(BaseModel):
    """POST /api/config/key body. Field name is ``key``.

    ``provider`` selects which secret to write — ``"youtube"`` (default, backward
    compatible) or ``"anthropic"`` (the Phase 4 direct-adapter key). Both are
    write-only and stored in the local secret store.
    """

    model_config = ConfigDict(extra="ignore")
    key: str = Field(min_length=1)
    provider: Optional[str] = None


class EnvCheckBody(BaseModel):
    """POST /api/config/env-check body (optional). Adapter defaults to config."""

    model_config = ConfigDict(extra="ignore")
    adapter: Optional[str] = None
    model: Optional[str] = None


class EnvCheckRemedy(BaseModel):
    """What the user should DO about a failed check (see adapters/base.remedy)."""

    model_config = ConfigDict(extra="forbid")
    #: "install" | "sign_in"
    kind: str
    label: str
    #: Server-defined command the remedy endpoint may run. Never client-supplied.
    command: Optional[str] = None
    url: Optional[str] = None


class EnvCheckResult(BaseModel):
    """Mirror of the TS ``EnvCheckResult`` (frontend/src/lib/types.ts)."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    adapter: str = ""
    version: Optional[str] = None
    message: str
    remedy: Optional[EnvCheckRemedy] = None


class KeyTestResult(BaseModel):
    """Mirror of the TS ``KeyTestResult``."""

    model_config = ConfigDict(extra="forbid")
    ok: bool
    message: str


class OkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool


# --- endpoints --------------------------------------------------------------
@router.get("/config", response_model=Config)
def read_config() -> Config:
    return config_store.get_config()


@router.put("/config", response_model=Config)
def update_config(body: ConfigUpdate) -> Config:
    return config_store.save_config(
        adapter=body.adapter,
        model=body.model,
        onboarding_complete=body.onboarding_complete,
        settings=body.settings,
    )


# Which stored secret each provider id writes to. Ids not listed here fall back
# to the YouTube key, preserving the original single-provider behaviour.
_KEY_WRITERS = {
    "anthropic": secrets.set_anthropic_key,
    "anthropic-api": secrets.set_anthropic_key,
    "claude": secrets.set_anthropic_key,
    "openai": secrets.set_openai_key,
    "openai-api": secrets.set_openai_key,
    "gpt": secrets.set_openai_key,
    "openrouter": secrets.set_openrouter_key,
    "open-router": secrets.set_openrouter_key,
}


@router.post("/config/key", response_model=OkResponse)
def set_key(body: KeyBody) -> OkResponse:
    # Write-only: store and acknowledge. Never echo or log the key value.
    provider = (body.provider or "youtube").strip().lower()
    write = _KEY_WRITERS.get(provider, secrets.set_youtube_key)
    try:
        write(body.key)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return OkResponse(ok=True)


@router.post("/config/env-check", response_model=EnvCheckResult)
def env_check(body: Optional[EnvCheckBody] = None) -> EnvCheckResult:
    requested = (body.adapter if body else None) or config_store.get_config().adapter or ""
    model = body.model if body else None
    # Defensive import — B2 implements app.adapters.check_env(adapter, model) in Wave 2.
    try:
        from app.adapters import check_env  # type: ignore
    except Exception:
        return EnvCheckResult(
            ok=False, adapter=requested, version=None,
            message="adapter probe not wired yet",
        )
    try:
        raw = check_env(requested, model)
    except Exception as exc:  # never leak a stack trace to the UI
        return EnvCheckResult(ok=False, adapter=requested, version=None, message=str(exc))
    return _coerce_env_check(raw, requested)


class RemedyBody(BaseModel):
    """POST /api/config/remedy body — an adapter id, never a command."""

    model_config = ConfigDict(extra="ignore")
    adapter: Optional[str] = None


class RemedyResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    message: str
    #: Echoed so the UI can offer "copy this and run it yourself" when ok is false.
    command: Optional[str] = None


@router.post("/config/remedy", response_model=RemedyResult)
def run_remedy(body: Optional[RemedyBody] = None) -> RemedyResult:
    """Run the selected adapter's sign-in command in a terminal the user can see.

    SAFETY: the request carries only an adapter id. The command is whatever that
    adapter's own ``check_env`` remedy declared (``adapters/base.remedy``), so
    this endpoint cannot be coaxed into running arbitrary input. Auth flows are
    interactive by design — the point is to hand the user a ready terminal, not
    to authenticate on their behalf.
    """
    requested = (body.adapter if body else None) or config_store.get_config().adapter or ""
    try:
        from app.adapters import check_env  # type: ignore
    except Exception:
        return RemedyResult(ok=False, message="Adapter layer unavailable.")

    try:
        raw = check_env(requested, None)
    except Exception as exc:
        return RemedyResult(ok=False, message=str(exc))

    result = _coerce_env_check(raw, requested)
    if result.ok:
        return RemedyResult(ok=True, message="Already connected — nothing to do.")
    if not result.remedy or not result.remedy.command:
        return RemedyResult(
            ok=False,
            message=result.message or "There's no automatic fix for this one.",
        )

    command = result.remedy.command
    from app.adapters.terminal import launch_in_terminal

    launched, message = launch_in_terminal(command)
    return RemedyResult(ok=launched, message=message, command=command)


@router.post("/config/key-test", response_model=KeyTestResult)
def key_test() -> KeyTestResult:
    # Defensive import — B3 implements app.pipeline.test_youtube_key() in Wave 2.
    # (It reads the stored key itself via secrets.get_youtube_key — the key is
    # never passed through the API.)
    try:
        from app.pipeline import test_youtube_key  # type: ignore
    except Exception:
        return KeyTestResult(ok=False, message="key test not wired yet")
    try:
        raw = test_youtube_key()
    except Exception as exc:
        return KeyTestResult(ok=False, message=str(exc))
    return _coerce_key_test(raw)


# --- coercion helpers: accept a dict, a pydantic model, or a plain object ----
def _as_dict(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:
            pass
    return {
        k: getattr(raw, k)
        for k in ("ok", "adapter", "version", "message", "remedy")
        if hasattr(raw, k)
    }


def _coerce_env_check(raw: Any, requested: str) -> EnvCheckResult:
    data = _as_dict(raw)
    raw_remedy = data.get("remedy")
    parsed: Optional[EnvCheckRemedy] = None
    if isinstance(raw_remedy, dict) and raw_remedy.get("kind"):
        try:
            parsed = EnvCheckRemedy(**raw_remedy)
        except Exception:  # a malformed remedy must never break the check itself
            parsed = None
    return EnvCheckResult(
        ok=bool(data.get("ok", False)),
        adapter=str(data.get("adapter") or requested or ""),
        version=data.get("version"),
        message=str(data.get("message", "")),
        remedy=parsed,
    )


def _coerce_key_test(raw: Any) -> KeyTestResult:
    data = _as_dict(raw)
    return KeyTestResult(ok=bool(data.get("ok", False)), message=str(data.get("message", "")))
