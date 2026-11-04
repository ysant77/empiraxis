"""Strict JSON for M5 records: no NaN or Infinity tokens, and a record of what was missing.

`dumps` rejects non-finite numbers. `sanitize` turns each one into null and lists its path and
reason, so a consumer such as JSON.parse reads the file and still sees why a value is absent.
"""

from __future__ import annotations

import json
import math
from typing import Any

DEFAULT_REASON = "value undefined in the source record (non-finite number)"


def dumps(obj: Any, **kwargs: Any) -> str:
    """json.dumps that raises ValueError on NaN or Infinity."""
    kwargs.setdefault("default", float)
    return json.dumps(obj, allow_nan=False, **kwargs)


def sanitize(
    obj: Any, reasons: dict[str, str] | None = None, _path: str = ""
) -> tuple[Any, list[dict[str, str]]]:
    """Return a copy with non-finite floats set to None, and a list of {path, reason}.

    `reasons` maps the last path element (for example "error_rate") to its reason.
    """
    reasons = reasons or {}
    if isinstance(obj, float) and not math.isfinite(obj):
        leaf = _path.rsplit("/", 1)[-1]
        return None, [{"path": _path, "reason": reasons.get(leaf, DEFAULT_REASON)}]
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        missing: list[dict[str, str]] = []
        for key, value in obj.items():
            out[key], found = sanitize(value, reasons, f"{_path}/{key}")
            missing += found
        return out, missing
    if isinstance(obj, list | tuple):
        items: list[Any] = []
        missing = []
        for i, value in enumerate(obj):
            item, found = sanitize(value, reasons, f"{_path}/{i}")
            items.append(item)
            missing += found
        return items, missing
    return obj, []


def reject_constant(token: str) -> Any:
    """parse_constant hook for a strict reader: raise on NaN, Infinity, -Infinity."""
    raise ValueError(f"non-standard JSON constant {token}")


def loads_strict(text: str) -> Any:
    return json.loads(text, parse_constant=reject_constant)
