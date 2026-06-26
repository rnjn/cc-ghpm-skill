#!/usr/bin/env python3
"""Download all GitHub Project items to JSON or CSV."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from scripts.common import (
    GHPMError,
    check_gh_auth,
    find_env_file,
    get_project_fields,
    get_project_items,
    get_project_node_id,
    get_today,
    load_config,
)

console = Console()
err_console = Console(stderr=True)


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
        n.get("login") for n in content.get("assignees", {}).get("nodes", []) if n.get("login")
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


CORE_COLUMNS = ["number", "title", "type", "state", "url", "assignees"]


def export_to_csv(records: list[dict[str, Any]], field_names: list[str]) -> str:
    """Serialize records into CSV with core columns plus one column per field."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CORE_COLUMNS + field_names)
    for r in records:
        row = [
            "" if r["number"] is None else r["number"],
            r["title"] or "",
            r["type"] or "",
            r["state"] or "",
            r["url"] or "",
            ";".join(r["assignees"]),
        ]
        for name in field_names:
            row.append(r["fields"].get(name, ""))
        writer.writerow(row)
    return output.getvalue()


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Download all GitHub Project items")
    parser.add_argument("--project", required=True, help="Project short name (from .env)")
    parser.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    parser.add_argument(
        "--output-file", help="Output path (default: <project>-items-YYYY-MM-DD.<ext> in cwd)"
    )
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    """Main entry point."""
    parsed = parse_args(args)

    try:
        env_file = find_env_file()
        config = load_config(env_file)

        if not check_gh_auth():
            err_console.print(
                "[red]GitHub CLI not authenticated.[/red]\n"
                "Run: gh auth login && gh auth refresh -s project"
            )
            return 1

        project = config.get_project(parsed.project)
        if not project:
            err_console.print(f"[red]Project '{parsed.project}' not found.[/red]")
            err_console.print("Available projects:")
            for p in config.projects:
                err_console.print(f"  - {p.name}")
            return 1

        project_id = get_project_node_id(project.owner, project.number)
        fields = get_project_fields(project_id)
        items = get_project_items(project_id, max_items=10000)
        records = [item_to_record(item) for item in items]

        if parsed.format == "csv":
            field_names = [
                f["name"]
                for f in fields
                if f.get("name") and f["name"].lower() not in ("title", "assignees")
            ]
            content = export_to_csv(records, field_names)
            ext = "csv"
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            content = export_to_json(records, project.name, timestamp)
            ext = "json"

        if parsed.output_file:
            out_path = Path(parsed.output_file)
        else:
            out_path = Path.cwd() / f"{project.name}-items-{get_today().isoformat()}.{ext}"

        out_path.write_text(content)
        console.print(
            f"Exported {len(records)} item{'s' if len(records) != 1 else ''} to {out_path}"
        )
        return 0

    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
