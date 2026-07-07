from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?|```", re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([\]}])")


def parse_json_response(raw: str) -> Any:
    """Parse LLM JSON output, tolerating fences, prose, and trailing commas."""
    cleaned = _sanitize(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        balanced = _extract_balanced(cleaned)
        if balanced is not None:
            try:
                return json.loads(balanced)
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
