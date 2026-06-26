#!/usr/bin/env python3
"""Download all GitHub Project items to JSON or CSV."""

from __future__ import annotations

import json
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


def item_to_record(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw project item into a flat export record."""
    content = item.get("content") or {}
    assignees = [
        n.get("login")
        for n in content.get("assignees", {}).get("nodes", [])
        if n.get("login")
    ]
    return {
        "number": content.get("number"),
        "title": content.get("title"),
        "type": content.get("__typename"),
        "state": content.get("state"),
        "url": content.get("url"),
        "assignees": assignees,
        "fields": extract_fields(item),
    }


def export_to_json(records: list[dict[str, Any]], project: str, timestamp: str) -> str:
    """Serialize records into the JSON export wrapper."""
    return json.dumps(
        {
            "project": project,
            "exported_at": timestamp,
            "count": len(records),
            "items": records,
        },
        indent=2,
    )
