"""Round floating-point values in JSON-compatible trees for readable output.

Fingerprint payloads skip rounding (see ``ArtifactModel.to_json_dict``) so hashes stay
bit-stable. For all other artifacts, rounding keeps derived scores and costs accurate
enough for aggregation while avoiding long binary-float tails like ``7.380000000000002``.
"""

from __future__ import annotations

import math
from typing import Any

# Six dimensions plus common aliases
_DIMENSION_KEYS = frozenset(
    {
        "task",
        "process",
        "autonomy",
        "closeness",
        "efficiency",
        "spark",
    }
)


def _decimal_places_for_key(key: str | None) -> int:
    """Pick decimal places from JSON key name (best-effort)."""
    if key is None:
        return 6
    lower = key.lower()
    if "latency" in lower or "duration" in lower or lower.endswith("_seconds"):
        return 4
    if "cost" in lower or lower.endswith("_usd") or lower == "usd":
        return 6
    if "score" in lower or lower in _DIMENSION_KEYS:
        return 5
    if lower in ("temperature", "top_p"):
        return 4
    return 6


def _round_float(value: float, key: str | None) -> float:
    if math.isnan(value) or math.isinf(value):
        return value
    places = _decimal_places_for_key(key)
    rounded = round(value, places)
    if rounded == 0.0 and value != 0.0:
        return math.copysign(0.0, value)
    return rounded


def round_floats_for_json(obj: Any, key: str | None = None) -> Any:
    """Recursively round floats in dicts/lists; preserve structure and non-float types."""
    if isinstance(obj, float):
        return _round_float(obj, key)
    if isinstance(obj, dict):
        return {k: round_floats_for_json(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [round_floats_for_json(item, None) for item in obj]
    if isinstance(obj, tuple):
        return tuple(round_floats_for_json(item, None) for item in obj)
    return obj
