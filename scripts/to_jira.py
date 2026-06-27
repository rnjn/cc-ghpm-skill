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
