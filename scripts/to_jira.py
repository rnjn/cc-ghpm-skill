#!/usr/bin/env python3
"""Transform a GHPM JSON export into acli bulk-create input and import to Jira."""

from __future__ import annotations

from typing import Any


def build_adf_description(body: str, url: str | None = None) -> dict[str, Any]:
    """Build an Atlassian Document Format description from plain text + URL."""
    content: list[dict[str, Any]] = []
    for line in (body or "").splitlines():
        if line.strip():
            content.append(
                {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            )
    if url:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": f"Imported from GitHub: {url}"}],
            }
        )
    if not content:
        content.append({"type": "paragraph", "content": []})
    return {"type": "doc", "version": 1, "content": content}


def issue_to_jira(
    record: dict[str, Any],
    *,
    project_key: str,
    type_field: str,
    default_type: str,
) -> dict[str, Any]:
    """Map one GHPM record to one acli issue object."""
    issue_type = record.get("fields", {}).get(type_field) or default_type
    return {
        "summary": record.get("title") or "",
        "projectKey": project_key,
        "issueType": issue_type,
        "description": build_adf_description(record.get("body") or "", record.get("url")),
    }
