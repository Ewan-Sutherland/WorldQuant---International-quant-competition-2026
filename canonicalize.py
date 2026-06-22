from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def canonicalize_expression(expr: str) -> str:
    """
    Normalize expression formatting so logically identical strings
    with different whitespace hash to the same value.
    """
    expr = expr.strip()

    # Fix Unicode-escaped comparison operators (WQ API returns \u003E for >)
    expr = expr.replace("\\u003E", ">").replace("\\u003e", ">")
    expr = expr.replace("\\u003C", "<").replace("\\u003c", "<")
    expr = expr.replace("\u003E", ">").replace("\u003e", ">")
    expr = expr.replace("\u003C", "<").replace("\u003c", "<")

    # collapse all whitespace
    expr = re.sub(r"\s+", " ", expr)

    # remove awkward spacing around punctuation
    expr = re.sub(r"\(\s+", "(", expr)
    expr = re.sub(r"\s+\)", ")", expr)
    expr = re.sub(r"\s*,\s*", ", ", expr)

    return expr


def canonicalize_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """
    Return a JSON-stable version of settings.
    """
    return json.loads(json.dumps(settings, sort_keys=True))


def hash_candidate(canonical_expression: str, settings: dict[str, Any]) -> str:
    payload = {
        "expression": canonical_expression,
        "settings": canonicalize_settings(settings),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
