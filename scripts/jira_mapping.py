#!/usr/bin/env python3
"""Field/value mapping helpers for the Jira importer."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.common import GHPMError

# Case-insensitive keys (lowercase) → Jira priority name.
DEFAULT_PRIORITY_MAP: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Highest",
    "postponed": "Lowest",
}


def map_value(value: str | None, value_map: dict[str, str]) -> str | None:
    """Return the mapped value for a GHPM value, or None if unset/unmapped."""
    if not value:
        return None
    return value_map.get(str(value).lower())


def load_priority_map(path: str | None) -> dict[str, str]:
    """Return the priority map: defaults, optionally overridden/extended by a JSON file.

    The JSON file must be an object of {GHPMValue: JiraName}. Keys are lowercased
    and merged over the defaults. Raises GHPMError on a missing/invalid file.
    """
    result = dict(DEFAULT_PRIORITY_MAP)
    if path is None:
        return result
    try:
        loaded = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise GHPMError(f"Could not read priority map '{path}': {e}")
    if not isinstance(loaded, dict):
        raise GHPMError(f"Priority map '{path}' must be a JSON object of value->name")
    for key, name in loaded.items():
        result[str(key).lower()] = name
    return result
