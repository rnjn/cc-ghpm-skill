#!/usr/bin/env python3
"""Transform a GHPM JSON export into acli bulk-create input and import to Jira."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from scripts.acli_client import acli_available, create_issue
from scripts.common import GHPMError, get_today

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
) -> dict[str, Any]:
    """Map one GHPM record to one acli issue object."""
    issue_type = record.get("fields", {}).get(type_field) or default_type
    return {
        "summary": record.get("title") or "",
        "projectKey": project_key,
        "type": issue_type,
        "description": build_adf_description(record.get("body") or "", record.get("url")),
    }


def transform(
    export: dict[str, Any],
    *,
    project_key: str,
    type_field: str,
    default_type: str,
) -> list[dict[str, Any]]:
    """Filter export items to Issues and map each to an acli issue object."""
    issues: list[dict[str, Any]] = []
    for record in export.get("items", []):
        if record.get("type") != "Issue":
            continue
        issues.append(
            issue_to_jira(
                record,
                project_key=project_key,
                type_field=type_field,
                default_type=default_type,
            )
        )
    return issues


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Import a GHPM JSON export into Jira via acli")
    parser.add_argument("--input", required=True, help="Path to a GHPM JSON export")
    parser.add_argument("--jira-project", required=True, help="Jira project key")
    parser.add_argument("--type-field", default="Type", help="GHPM field used as Jira issue type")
    parser.add_argument("--default-type", default="Task", help="Jira type when the field is unset")
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

    issues = transform(
        export,
        project_key=parsed.jira_project,
        type_field=parsed.type_field,
        default_type=parsed.default_type,
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
    try:
        for idx, issue in enumerate(issues, 1):
            label = issue.get("summary") or f"item {idx}"
            rc, output = create_issue(issue)
            if rc == 0:
                created += 1
                console.print(f"[{idx}/{total}] created: {label}")
            else:
                failed += 1
                err_console.print(f"[{idx}/{total}] FAILED: {label}: {output.strip()}")
    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1

    console.print(f"Done: {created} created, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
