"""Structured output shared by every adapter that can constrain generation.

One strict JSON Schema for the ``AgentResult`` narrative, built from the
Pydantic contract. Codex receives it as ``--output-schema``, Anthropic as
``output_config.format``, the OpenAI-compatible providers as ``response_format``
and Ollama as its native ``format``. Each provider accepts a different subset
of JSON Schema, so the schema here is the common subset:

* ``$ref`` is inlined (the contract has no recursion), so no ``$defs``.
* Every object has ``additionalProperties: false`` and lists every property as
  required. Optional sections are already ``anyOf [..., null]``, so "required"
  only means "say null explicitly".
* ``default``, ``title`` and value constraints (``pattern``, ``minimum`` …) are
  dropped. Anthropic rejects the constraints and OpenAI strict mode rejects
  ``default``; Pydantic still enforces all of them when the answer is validated.
* ``const`` becomes a one-value ``enum``.

The schema constrains the model only. Trust is unchanged: every id and number
in the answer is still checked against the pipeline.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Optional

#: Marks the narrative and repair prompts (see ``orchestrator/prompts.py``).
#: Only those ask for an AgentResult; keyword expansion returns a plain array.
AGENT_RESULT_MARKER = "OUTPUT CONTRACT"

#: Name sent with OpenAI-style ``json_schema`` formats.
AGENT_RESULT_SCHEMA_NAME = "agent_result"

_DROPPED = frozenset(
    {
        "default",
        "title",
        "examples",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "uniqueItems",
    }
)

#: The model check asks for this tiny object with the same format mode as the
#: run, so a provider that rejects structured output fails before quota is spent.
PROBE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"reply": {"type": "string"}},
    "required": ["reply"],
    "additionalProperties": False,
}
PROBE_SCHEMA_NAME = "check"
PROBE_PROMPT = 'Reply with exactly this JSON object: {"reply": "hello"}'
PLAIN_PROBE_PROMPT = "Reply with exactly: hello"

_cached: Optional[Dict[str, Any]] = None


def wants_agent_result(prompt: str) -> bool:
    """True for the narrative and repair prompts, which expect an AgentResult."""
    return AGENT_RESULT_MARKER in (prompt or "")


def strict_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """The provider-safe strict form of a Pydantic JSON Schema (a new dict)."""
    defs = schema.get("$defs") or {}

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return resolve(defs[ref[len("#/$defs/"):]])
        out: Dict[str, Any] = {}
        for key, value in node.items():
            if key in _DROPPED or key == "$defs":
                continue
            if key == "properties" and isinstance(value, dict):
                # Keys here are property NAMES (one is "title"), never keywords.
                out[key] = {name: resolve(sub) for name, sub in value.items()}
            elif key == "const":
                out["enum"] = [value]
            else:
                out[key] = resolve(value)
        if out.get("type") == "object" or "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out.get("properties", {}))
        return out

    return resolve(schema)


def agent_result_schema() -> Dict[str, Any]:
    """Strict AgentResult schema, built once; each caller gets its own copy."""
    global _cached
    if _cached is None:
        from contracts.python.models import AgentResult

        _cached = strict_schema(AgentResult.model_json_schema())
    return copy.deepcopy(_cached)


def prune_unknown_keys(value: Any, schema: Dict[str, Any]) -> Any:
    """Copy of ``value`` without object keys the (strict) ``schema`` doesn't name.

    Models sometimes add a harmless extra key. The contract forbids extras, so
    one stray key used to cost a repair call; dropping it first keeps the strict
    check for everything that matters. Values that don't match the schema's
    shape are returned unchanged for the validator to report.
    """
    if isinstance(value, dict):
        node = _branch(schema, "properties")
        props = node.get("properties") if node else None
        if not isinstance(props, dict):
            return value
        return {
            key: prune_unknown_keys(item, props[key])
            for key, item in value.items()
            if key in props
        }
    if isinstance(value, list):
        node = _branch(schema, "items")
        items = node.get("items") if node else None
        if not isinstance(items, dict):
            return value
        return [prune_unknown_keys(item, items) for item in value]
    return value


def _branch(schema: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    """The schema node (or ``anyOf`` branch) that carries ``key``."""
    if key in schema:
        return schema
    for option in schema.get("anyOf") or ():
        if isinstance(option, dict) and key in option:
            return option
    return None
