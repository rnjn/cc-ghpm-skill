#!/usr/bin/env python3
"""Transform a GHPM JSON export into acli bulk-create input and import to Jira."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from rich.console import Console

from scripts.acli_client import acli_available, create_issue, transition_issues
from scripts.common import GHPMError, get_today
from scripts.jira_mapping import load_priority_map, load_status_map, map_value

console = Console()
err_console = Console(stderr=True)


def build_adf_description(body: str, url: str | None = None) -> dict[str, Any]:
    """Build an Atlassian Document Format description from plain text + URL."""
    content: list[dict[str, Any]] = []
    for line in (body or "").splitlines():
        if line.strip():
            content.append({"type": "paragraph", "content": [{"type": "text", "text": line}]})
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
    priority_field: str = "Priority",
    priority_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Map one GHPM record to one acli issue object."""
    issue_type = record.get("fields", {}).get(type_field) or default_type
    issue: dict[str, Any] = {
        "summary": record.get("title") or "",
        "projectKey": project_key,
        "type": issue_type,
        "description": build_adf_description(record.get("body") or "", record.get("url")),
    }
    if priority_map:
        name = map_value((record.get("fields") or {}).get(priority_field), priority_map)
        if name:
            issue["additionalAttributes"] = {"priority": {"name": name}}
    return issue


def iter_issue_records(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Return export items filtered to GitHub Issues."""
    return [r for r in export.get("items", []) if r.get("type") == "Issue"]


def status_target(
    record: dict[str, Any],
    *,
    status_field: str,
    status_map: dict[str, str],
    initial_status: str,
) -> str | None:
    """Return the Jira status to transition this record to, or None to skip.

    Skips (returns None) when the status is unset, unmapped, or already the
    project's initial status.
    """
    target = map_value((record.get("fields") or {}).get(status_field), status_map)
    if not target or target == initial_status:
        return None
    return target


def transform(
    export: dict[str, Any],
    *,
    project_key: str,
    type_field: str,
    default_type: str,
    priority_field: str = "Priority",
    priority_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Filter export items to Issues and map each to an acli issue object."""
    return [
        issue_to_jira(
            record,
            project_key=project_key,
            type_field=type_field,
            default_type=default_type,
            priority_field=priority_field,
            priority_map=priority_map,
        )
        for record in iter_issue_records(export)
    ]


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Import a GHPM JSON export into Jira via acli")
    parser.add_argument("--input", required=True, help="Path to a GHPM JSON export")
    parser.add_argument("--jira-project", required=True, help="Jira project key")
    parser.add_argument("--type-field", default="Type", help="GHPM field used as Jira issue type")
    parser.add_argument("--default-type", default="Task", help="Jira type when the field is unset")
    parser.add_argument(
        "--priority-field", default="Priority", help="GHPM field used as Jira priority"
    )
    parser.add_argument(
        "--priority-map-file", help="JSON file overriding the GHPM->Jira priority map"
    )
    parser.add_argument("--status-field", default="Status", help="GHPM field used as Jira status")
    parser.add_argument("--status-map-file", help="JSON file overriding the GHPM->Jira status map")
    parser.add_argument(
        "--initial-status",
        default="To Do",
        help="Jira initial status; issues mapping to it are not transitioned",
    )
    parser.add_argument(
        "--out", help="Output path (default: <project>-jira-YYYY-MM-DD.json in cwd)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Write the file; do not call acli")
    parser.add_argument(
        "--yes", action="store_true", help="Skip confirmation and pass --yes to acli"
    )
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    """Main entry point."""
    parsed = parse_args(args)

    try:
        export = json.loads(Path(parsed.input).read_text())
    except (OSError, json.JSONDecodeError) as e:
        err_console.print(f"[red]Could not read export '{parsed.input}': {e}[/red]")
        return 1

    try:
        priority_map = load_priority_map(parsed.priority_map_file)
    except GHPMError as e:
        err_console.print(f"[red]{e}[/red]")
        return 1

    try:
        status_map = load_status_map(parsed.status_map_file)
    except GHPMError as e:
        err_console.print(f"[red]{e}[/red]")
        return 1

    records = iter_issue_records(export)
    unmapped = sorted(
        {
            value
            for r in records
            if (value := (r.get("fields") or {}).get(parsed.priority_field))
            and map_value(value, priority_map) is None
        }
    )
    for value in unmapped:
        err_console.print(f"[yellow]Warning: priority '{value}' not mapped; omitting.[/yellow]")

    unmapped_status = sorted(
        {
            value
            for r in records
            if (value := (r.get("fields") or {}).get(parsed.status_field))
            and map_value(value, status_map) is None
        }
    )
    for value in unmapped_status:
        err_console.print(
            f"[yellow]Warning: status '{value}' not mapped; leaving at initial.[/yellow]"
        )

    issues = transform(
        export,
        project_key=parsed.jira_project,
        type_field=parsed.type_field,
        default_type=parsed.default_type,
        priority_field=parsed.priority_field,
        priority_map=priority_map,
    )

    # Fix 2: short-circuit if no issues to import
    if not issues:
        console.print("No issues to import (export had no Issue-type items).")
        return 0

    project = export.get("project", "export")
    if parsed.out:
        out_path = Path(parsed.out)
    else:
        out_path = Path.cwd() / f"{project}-jira-{get_today().isoformat()}.json"

    # Fix 1: guard the output write
    try:
        out_path.write_text(json.dumps({"issues": issues}, indent=2))
    except OSError as e:
        err_console.print(f"[red]Could not write output file '{out_path}': {e}[/red]")
        return 1
    console.print(f"Wrote {len(issues)} issue{'s' if len(issues) != 1 else ''} to {out_path}")

    if parsed.dry_run:
        plan = Counter(
            t
            for r in records
            if (
                t := status_target(
                    r,
                    status_field=parsed.status_field,
                    status_map=status_map,
                    initial_status=parsed.initial_status,
                )
            )
        )
        if plan:
            console.print("Status transition plan:")
            for status, count in sorted(plan.items()):
                console.print(f"  {count} -> {status}")
        return 0

    if not acli_available():
        err_console.print(
            "[red]acli not found on PATH.[/red] Install Atlassian CLI and run 'acli jira auth'."
        )
        return 1

    if not parsed.yes:
        answer = input(
            f"Create {len(issues)} issue(s) in Jira project {parsed.jira_project}? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            console.print("Aborted.")
            return 1

    # Create issues one at a time (acli create-bulk cannot carry an ADF
    # description; per-issue `create` accepts it). Continue past failures.
    total = len(issues)
    created = 0
    failed = 0
    created_pairs: list[tuple[dict[str, Any], str | None]] = []
    try:
        for idx, (record, issue) in enumerate(zip(records, issues), 1):
            label = issue.get("summary") or f"item {idx}"
            rc, key, output = create_issue(issue)
            if rc == 0:
                created += 1
                created_pairs.append((record, key))
                console.print(f"[{idx}/{total}] created: {label}")
            else:
                failed += 1
                err_console.print(f"[{idx}/{total}] FAILED: {label}: {output.strip()}")
    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1

    console.print(f"Done: {created} created, {failed} failed")

    groups: dict[str, list[str]] = {}
    for record, key in created_pairs:
        if not key:
            continue
        target = status_target(
            record,
            status_field=parsed.status_field,
            status_map=status_map,
            initial_status=parsed.initial_status,
        )
        if target:
            groups.setdefault(target, []).append(key)

    for status, keys in groups.items():
        rc, out = transition_issues(keys, status)
        if rc != 0:
            rc, out = transition_issues(keys, status)  # retry once (indexing lag)
        if rc == 0:
            console.print(f"Transitioned {len(keys)} issue(s) -> {status}")
        else:
            err_console.print(
                f"[red]Failed to transition {len(keys)} issue(s) -> {status}: {out.strip()}[/red]"
            )

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
