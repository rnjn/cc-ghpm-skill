#!/usr/bin/env python3
"""Download all GitHub Project items to JSON or CSV."""

from __future__ import annotations

from typing import Any


def extract_fields(item: dict[str, Any]) -> dict[str, str]:
    """Flatten an item's fieldValues into a {field_name: value} dict."""
    result: dict[str, str] = {}
    for fv in item.get("fieldValues", {}).get("nodes", []):
        field = fv.get("field") or {}
        name = field.get("name")
        if not name:
            continue
        if "text" in fv:
            result[name] = fv["text"]
        elif "name" in fv:
            result[name] = fv["name"]
        elif "title" in fv:
            result[name] = fv["title"]
    return result
