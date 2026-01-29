#!/usr/bin/env python3
"""Move GitHub Project items between iterations."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from rich.console import Console

from scripts.common import (
    GHPMError,
    check_gh_auth,
    find_env_file,
    get_field_by_name,
    get_item_field_value,
    get_project_fields,
    get_project_items,
    get_project_node_id,
    load_config,
    resolve_iteration_keyword,
    update_item_field,
)

console = Console()
err_console = Console(stderr=True)


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        args: Arguments to parse (defaults to sys.argv[1:])

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Move open issues between iterations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--from-iteration",
        required=True,
        help="Source iteration: previous, current, next, or exact name",
    )
    parser.add_argument(
        "--to-iteration",
        required=True,
        help="Target iteration: previous, current, next, or exact name",
    )
    parser.add_argument(
        "--project",
        help="Project short name (from .env). If omitted, runs on all projects",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    return parser.parse_args(args)


def get_item_iteration_id(item: dict[str, Any]) -> str | None:
    """Get the iteration ID from an item.

    Args:
        item: Project item

    Returns:
        Iteration ID or None if not set
    """
    field_values = item.get("fieldValues", {}).get("nodes", [])
    for fv in field_values:
        field = fv.get("field", {})
        if field.get("name", "").lower() == "iteration":
            return fv.get("iterationId")
    return None


def filter_movable_items(
    items: list[dict[str, Any]],
    from_iteration_title: str,
    done_status: str,
) -> list[dict[str, Any]]:
    """Filter items that should be moved.

    Includes items that:
    - Are in the source iteration
    - Are OPEN (not closed)
    - Do not have Done status

    Args:
        items: List of project items
        from_iteration_title: Source iteration title
        done_status: Status value that indicates done

    Returns:
        Filtered list of movable items
    """
    result = []

    for item in items:
        content = item.get("content")
        if not content:
            continue  # Skip draft items

        # Check if issue is open
        if content.get("state") != "OPEN":
            continue

        # Check status is not Done
        status = get_item_field_value(item, "Status")
        if status and status.lower() == done_status.lower():
            continue

        # Check iteration matches
        iteration_title = get_item_field_value(item, "Iteration")
        if iteration_title != from_iteration_title:
            continue

        result.append(item)

    return result


def format_dry_run_output(
    items: list[dict[str, Any]],
    project_name: str,
    from_title: str,
    to_title: str,
) -> None:
    """Format and print dry-run output.

    Args:
        items: Items that would be moved
        project_name: Project name
        from_title: Source iteration title
        to_title: Target iteration title
    """
    console.print(f"[yellow][DRY RUN][/yellow] Project: {project_name}")
    console.print(f'  Would move {len(items)} items from "{from_title}" -> "{to_title}":')

    for item in items:
        content = item.get("content", {})
        number = content.get("number", "")
        title = content.get("title", "")
        if len(title) > 50:
            title = title[:47] + "..."
        console.print(f"    #{number}  {title}")

    console.print()


def format_move_result(
    project_name: str,
    moved_count: int,
    from_title: str,
    to_title: str,
) -> None:
    """Format and print move result.

    Args:
        project_name: Project name
        moved_count: Number of items moved
        from_title: Source iteration title
        to_title: Target iteration title
    """
    console.print(f"Project: {project_name}")
    console.print(f'  Moved {moved_count} items from "{from_title}" -> "{to_title}"')
    console.print()


def move_items_for_project(
    project_id: str,
    project_name: str,
    fields: list[dict[str, Any]],
    iteration_field_name: str,
    from_keyword: str,
    to_keyword: str,
    done_status: str,
    dry_run: bool,
) -> tuple[int, int]:
    """Move items for a single project.

    Args:
        project_id: Project node ID
        project_name: Project name for display
        fields: Project field definitions
        iteration_field_name: Name of iteration field
        from_keyword: Source iteration keyword or title
        to_keyword: Target iteration keyword or title
        done_status: Done status value
        dry_run: Whether to just preview

    Returns:
        Tuple of (items found, items moved)
    """
    # Get iteration field
    iteration_field = get_field_by_name(fields, iteration_field_name)
    if not iteration_field:
        err_console.print(f"[red]Iteration field '{iteration_field_name}' not found[/red]")
        return 0, 0

    config = iteration_field.get("configuration", {})
    iterations = config.get("iterations", [])
    completed_iterations = config.get("completedIterations", [])

    # Resolve iteration keywords
    from_iteration = resolve_iteration_keyword(iterations, from_keyword, completed_iterations)
    to_iteration = resolve_iteration_keyword(iterations, to_keyword, completed_iterations)

    # Fetch items
    items = get_project_items(project_id)

    # Filter movable items
    movable = filter_movable_items(items, from_iteration["title"], done_status)

    if not movable:
        console.print(f"Project: {project_name}")
        console.print(f'  No items to move from "{from_iteration["title"]}"')
        console.print()
        return 0, 0

    if dry_run:
        format_dry_run_output(
            movable,
            project_name,
            from_iteration["title"],
            to_iteration["title"],
        )
        return len(movable), 0

    # Move items
    moved = 0
    for item in movable:
        try:
            update_item_field(
                project_id,
                item["id"],
                iteration_field["id"],
                {"iterationId": to_iteration["id"]},
            )
            moved += 1
        except GHPMError as e:
            content = item.get("content", {})
            err_console.print(f"[red]Failed to move #{content.get('number')}: {e}[/red]")

    format_move_result(
        project_name,
        moved,
        from_iteration["title"],
        to_iteration["title"],
    )
    return len(movable), moved


def main(args: list[str] | None = None) -> int:
    """Main entry point.

    Args:
        args: Command line arguments

    Returns:
        Exit code (0 for success)
    """
    parsed = parse_args(args)

    try:
        # Load config
        env_file = find_env_file()
        config = load_config(env_file)

        # Check auth
        if not check_gh_auth():
            err_console.print(
                "[red]GitHub CLI not authenticated.[/red]\n"
                "Run: gh auth login && gh auth refresh -s project"
            )
            return 1

        # Determine which projects to process
        if parsed.project:
            project = config.get_project(parsed.project)
            if not project:
                err_console.print(f"[red]Project '{parsed.project}' not found.[/red]")
                err_console.print("Available projects:")
                for p in config.projects:
                    err_console.print(f"  - {p.name}")
                return 1
            projects = [project]
        else:
            projects = config.projects

        # Process each project
        total_found = 0
        total_moved = 0

        for project in projects:
            try:
                project_id = get_project_node_id(project.owner, project.number)
                fields = get_project_fields(project_id)

                found, moved = move_items_for_project(
                    project_id,
                    project.name,
                    fields,
                    config.iteration_field,
                    parsed.from_iteration,
                    parsed.to_iteration,
                    config.done_status,
                    parsed.dry_run,
                )
                total_found += found
                total_moved += moved
            except GHPMError as e:
                err_console.print(f"[red]Error processing {project.name}: {e}[/red]")
                continue

        # Summary
        if parsed.dry_run:
            console.print("[yellow][DRY RUN][/yellow] No changes made.")
            console.print(f"Would move {total_found} items across {len(projects)} project(s)")
        else:
            console.print(f"Total: {total_moved} items moved across {len(projects)} project(s)")

        return 0

    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
