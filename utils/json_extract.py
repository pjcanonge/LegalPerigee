"""
Robust JSON extraction from LLM responses that may include
prose preambles, markdown code fences, or trailing commentary.
"""

import json
import re
from typing import Any, Optional


def extract_json(text: str) -> Optional[Any]:
    """
    Extract and parse the first JSON object or array from text.

    Tries in order:
    1. Direct parse (clean response)
    2. Strip ```json ... ``` fences
    3. Find first { ... } or [ ... ] block
    """
    text = text.strip()
    if not text:
        return None

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Strip fences and try the inner content (handles truncated fences too)
    fence_inner = re.search(r"```(?:json)?\s*([\s\S]+?)(?:```|$)", text)
    if fence_inner:
        try:
            return json.loads(fence_inner.group(1).strip())
        except json.JSONDecodeError:
            # Fall through — inner content may still have the { } we need
            text = fence_inner.group(1).strip() or text

    # 3. Find the outermost { } block (greedy — scan for the last matching })
    start = text.find("{")
    if start != -1:
        depth = 0
        last_complete = -1
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    last_complete = i
                    break  # found the outermost closing brace
        if last_complete != -1:
            try:
                return json.loads(text[start : last_complete + 1])
            except json.JSONDecodeError:
                pass

    # 4. Find the outermost [ ] block
    start = text.find("[")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break

    return None
