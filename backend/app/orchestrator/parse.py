"""CLI stream -> AgentResult extraction + validation (B4).

The adapter (B2) yields raw stdout lines. For Claude Code that is
``--output-format stream-json`` (one JSON event per line, the final answer in a
``{"type":"result","result": "..."}`` event); other adapters may emit plain
text with the JSON in a ``` ```json ``` ``` fence. :class:`StreamCollector`
tolerates both: it accumulates assistant text, captures the final ``result``
string, and reports a short human ``detail`` per line so the run loop can drive
the "analyzing" progress. :func:`find_last_json_object` then recovers the last
balanced ``{...}`` that parses.

Trust boundary: this module only *parses* — it never trusts the agent's numbers.
The parsed dict is validated against the ``AgentResult`` schema (narrative +
``video_id`` refs only); the authoritative join happens later in B5.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from contracts.python.models import AgentResult


def _try_json(line: str) -> Optional[Any]:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except Exception:
        return None


def find_last_json_object(text: str) -> Optional[str]:
    """Return the source of the LAST top-level balanced ``{...}`` that parses as
    JSON, ignoring braces inside strings and any surrounding prose / code fences.
    ``None`` if the text contains no parseable object.
    """
    if not text:
        return None
    last: Optional[str] = None
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    candidate = text[start : i + 1]
                    try:
                        json.loads(candidate)
                        last = candidate
                    except Exception:
                        pass
                    start = -1
    return last


def find_json_array(text: str) -> Optional[str]:
    """Return the source of the LAST top-level balanced ``[...]`` that parses as a
    JSON array, ignoring brackets inside strings and any surrounding prose / code
    fences. ``None`` if the text contains no parseable array.

    Used by the direct adapter's keyword-expansion step (the model returns a JSON
    array of search phrases, sometimes wrapped in prose despite instructions).
    """
    if not text:
        return None
    last: Optional[str] = None
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    candidate = text[start : i + 1]
                    try:
                        if isinstance(json.loads(candidate), list):
                            last = candidate
                    except Exception:
                        pass
                    start = -1
    return last


def _assistant_text(obj: Dict[str, Any]) -> str:
    msg = obj.get("message") or {}
    content = msg.get("content")
    parts: List[str] = []
    if isinstance(content, list):
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and isinstance(block.get("text"), str)
            ):
                parts.append(block["text"])
    elif isinstance(content, str):
        parts.append(content)
    return "\n".join(parts)


def _has_tool_use(obj: Dict[str, Any]) -> bool:
    msg = obj.get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") in (
                "tool_use",
                "tool_result",
            ):
                return True
    return False


def _looks_like_agent_result(obj: Dict[str, Any]) -> bool:
    return "top_video_ids" in obj or (
        "schema_version" in obj and "summary" in obj and "topic_title" in obj
    )


class StreamCollector:
    """Accumulates a CLI stream and recovers the final AgentResult dict."""

    def __init__(self) -> None:
        self._text_parts: List[str] = []
        self._result_text: Optional[str] = None
        self._direct_obj: Optional[Dict[str, Any]] = None
        self.tool_events = 0
        self.line_count = 0

    def feed(self, line: str) -> Optional[str]:
        """Consume one raw line; return an optional human ``detail`` string."""
        self.line_count += 1
        obj = _try_json(line)
        if obj is None:
            stripped = line.strip()
            if stripped:
                self._text_parts.append(stripped)
            return None
        if not isinstance(obj, dict):
            return None

        etype = obj.get("type")
        if etype == "assistant":
            text = _assistant_text(obj)
            if text:
                self._text_parts.append(text)
            if _has_tool_use(obj):
                self.tool_events += 1
                return "Running research tools"
            return "Writing analysis" if text else None
        if etype == "result":
            result = obj.get("result")
            if isinstance(result, str):
                self._result_text = result
            elif isinstance(result, dict) and _looks_like_agent_result(result):
                self._direct_obj = result
            return None
        if etype in ("tool_use", "tool_result") or (
            etype == "user" and _has_tool_use(obj)
        ):
            self.tool_events += 1
            return "Running research tools"
        if etype == "system":
            return None
        # A bare object that is itself the AgentResult.
        if _looks_like_agent_result(obj):
            self._direct_obj = obj
        return None

    def text(self) -> str:
        """The model's own answer text, unwrapped from any stream framing.

        The final ``result`` string when the stream had one, else the accumulated
        assistant text. Used by the keyword-expansion step, whose payload is a
        JSON *array* rather than the object :meth:`extract` looks for.
        """
        if self._result_text is not None:
            return self._result_text
        return "\n".join(self._text_parts)

    def extract(self) -> Optional[Dict[str, Any]]:
        """Best-effort final AgentResult-shaped dict, or ``None`` if none found."""
        if self._direct_obj is not None:
            return self._direct_obj
        candidate = self._result_text
        if candidate is None:
            candidate = "\n".join(self._text_parts)
        blob = find_last_json_object(candidate)
        if blob is None:
            return None
        try:
            parsed = json.loads(blob)
        except Exception:
            return None
        return parsed if isinstance(parsed, dict) else None


def validate_agent_result(obj: Dict[str, Any]) -> AgentResult:
    """Validate a parsed dict against the strict ``AgentResult`` schema.

    Raises ``pydantic.ValidationError`` on any contract drift.
    """
    return AgentResult.model_validate(obj)
