from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?|```", re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([\]}])")


def parse_json_response(raw: str) -> Any:
    """Parse LLM JSON output, tolerating fences, prose, trailing commas, and truncation."""
    cleaned = _sanitize(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    balanced = _extract_balanced(cleaned)
    if balanced is not None:
        try:
            return json.loads(balanced)
        except json.JSONDecodeError:
            pass
    # Last resort: try to repair truncated JSON by closing open braces/brackets
    repaired = _repair_truncated(cleaned)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Unparseable JSON from LLM: {raw[:200]!r}")


def _sanitize(raw: str) -> str:
    text = _FENCE_RE.sub("", raw).strip()
    text = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _extract_balanced(text: str) -> str | None:
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escaped = False
        for i in range(start, len(text)):
            char = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
            elif char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    return None


def _repair_truncated(text: str) -> str | None:
    """Attempt to repair truncated JSON by closing open strings, braces, and brackets.

    LLMs sometimes hit max_tokens mid-response, leaving incomplete JSON like:
    {"response_text": "Got it, I'll create that
    This function closes the open string and any open structures so json.loads succeeds.
    """
    # Find the first opening brace
    start = text.find("{")
    if start < 0:
        return None
    fragment = text[start:]

    # Track depth and string state
    depth = 0
    in_string = False
    escaped = False
    stack: list[str] = []

    for char in fragment:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
            stack.append("}")
        elif char == "[":
            depth += 1
            stack.append("]")
        elif char == "}" or char == "]":
            depth -= 1
            if stack:
                stack.pop()

    # If we're still inside a string, close it
    suffix = ""
    if in_string:
        suffix += '"'

    # Handle truncation at awkward points:
    # - After a colon with no value: '{"reasoning":' → add null
    # - After a comma: '{"a": "ok",' → strip the trailing comma before closing
    stripped = (fragment + suffix).rstrip()
    if not in_string and stripped.endswith(":"):
        suffix += " null"
    elif not in_string and stripped.endswith(","):
        fragment = stripped[:-1]  # remove the trailing comma

    # Close any open structures (innermost first)
    while stack:
        suffix += stack.pop()

    if not suffix:
        return None  # nothing to repair

    return fragment + suffix
