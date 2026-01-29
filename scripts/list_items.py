#!/usr/bin/env python3
"""List and filter GitHub Project items."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from rich.console import Console
from rich.table import Table

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
        description="List and filter GitHub Project items",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project short name (from .env)",
    )
    parser.add_argument(
        "--missing-field",
        help="Find items where this field is not set",
    )
    parser.add_argument(
        "--iteration",
        help="Filter by iteration: previous, current, next, or exact name",
    )
    parser.add_argument(
        "--status",
        help="Filter by status value",
    )
    parser.add_argument(
        "--open-only",
        action="store_true",
        help="Only show open issues",
    )
    parser.add_argument(
        "--show-iterations",
        action="store_true",
        help="Show iteration info for the project",
    )
    return parser.parse_args(args)


def filter_items(
    items: list[dict[str, Any]],
    *,
    open_only: bool = False,
    status: str | None = None,
    missing_field: str | None = None,
    iteration_title: str | None = None,
) -> list[dict[str, Any]]:
    """Filter project items based on criteria.

    Args:
        items: List of project items
        open_only: Only include open items
        status: Filter by status value
        missing_field: Filter to items missing this field
        iteration_title: Filter by iteration title

    Returns:
        Filtered list of items
    """
    result = []

    for item in items:
        content = item.get("content")
        if not content:
            continue  # Skip draft items

        # Open only filter
        if open_only and content.get("state") != "OPEN":
            continue

        # Status filter
        if status:
            item_status = get_item_field_value(item, "Status")
            if item_status != status:
                continue

        # Iteration filter
        if iteration_title:
            item_iteration = get_item_field_value(item, "Iteration")
            if item_iteration != iteration_title:
                continue

        # Missing field filter
        if missing_field:
            field_value = get_item_field_value(item, missing_field)
            if field_value is not None:
                continue  # Has the field, skip

        result.append(item)

    return result


def format_output(
    items: list[dict[str, Any]],
    project_name: str,
    *,
    fields_to_show: list[str] | None = None,
    filter_desc: str | None = None,
) -> None:
    """Format and print items as a table.

    Args:
        items: List of items to display
        project_name: Project name for header
        fields_to_show: Fields to include as columns
        filter_desc: Description of filters applied
    """
    if fields_to_show is None:
        fields_to_show = ["Status"]

    # Header
    header_parts = [f"Project: {project_name}"]
    if filter_desc:
        header_parts.append(filter_desc)
    console.print(" | ".join(header_parts))
    console.print()

    # Table
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", style="cyan", no_wrap=True)
    table.add_column("Title", style="white")
    for field in fields_to_show:
        table.add_column(field)

    for item in items:
        content = item.get("content", {})
        number = str(content.get("number", ""))
        title = content.get("title", "")

        # Truncate long titles
        if len(title) > 40:
            title = title[:37] + "..."

        row = [number, title]
        for field in fields_to_show:
            value = get_item_field_value(item, field)
            row.append(value if value else "(empty)")

        table.add_row(*row)

    console.print(table)
    console.print(f"\nFound {len(items)} issue{'s' if len(items) != 1 else ''}")


def show_iterations(
    fields: list[dict[str, Any]],
    project_name: str,
    iteration_field_name: str,
) -> None:
    """Display iteration information for a project.

    Args:
        fields: Project field definitions
        project_name: Project name
        iteration_field_name: Name of iteration field
    """
    iteration_field = get_field_by_name(fields, iteration_field_name)
    if not iteration_field:
        err_console.print(f"[red]Iteration field '{iteration_field_name}' not found[/red]")
        return

    config = iteration_field.get("configuration", {})
    iterations = config.get("iterations", [])
    completed_iterations = config.get("completedIterations", [])

    console.print(f"Project: {project_name} | Iterations")
    console.print()

    # Active iterations
    if iterations:
        console.print("[bold]Active Iterations[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Title")
        table.add_column("Start Date")
        table.add_column("Duration")

        for iteration in iterations:
            table.add_row(
                iteration["title"],
                iteration["startDate"],
                f"{iteration['duration']} days",
            )

        console.print(table)
        console.print()

    # Completed iterations
    if completed_iterations:
        console.print("[bold]Completed Iterations[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Title")
        table.add_column("Start Date")
        table.add_column("Duration")

        for iteration in completed_iterations:
            table.add_row(
                iteration["title"],
                iteration["startDate"],
                f"{iteration['duration']} days",
            )

        console.print(table)


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

        # Find project
        project = config.get_project(parsed.project)
        if not project:
            err_console.print(f"[red]Project '{parsed.project}' not found.[/red]")
            err_console.print("Available projects:")
            for p in config.projects:
                err_console.print(f"  - {p.name}")
            return 1

        # Get project node ID
        project_id = get_project_node_id(project.owner, project.number)

        # Get fields
        fields = get_project_fields(project_id)

        # Show iterations mode
        if parsed.show_iterations:
            show_iterations(fields, project.name, config.iteration_field)
            return 0

        # Resolve iteration keyword if provided
        iteration_title: str | None = None
        if parsed.iteration:
            iteration_field = get_field_by_name(fields, config.iteration_field)
            if iteration_field:
                iterations = iteration_field.get("configuration", {}).get("iterations", [])
                iteration = resolve_iteration_keyword(iterations, parsed.iteration)
                iteration_title = iteration["title"]

        # Validate missing-field if provided
        if parsed.missing_field:
            field = get_field_by_name(fields, parsed.missing_field)
            if not field:
                err_console.print(f"[red]Field '{parsed.missing_field}' not found.[/red]")
                err_console.print("Available fields:")
                for f in fields:
                    if "name" in f:
                        err_console.print(f"  - {f['name']}")
                return 1

        # Fetch items
        items = get_project_items(project_id)

        # Apply filters
        filtered = filter_items(
            items,
            open_only=parsed.open_only,
            status=parsed.status,
            missing_field=parsed.missing_field,
            iteration_title=iteration_title,
        )

        # Build filter description
        filter_parts = []
        if parsed.missing_field:
            filter_parts.append(f'missing "{parsed.missing_field}"')
        if iteration_title:
            filter_parts.append(f'Iteration: {iteration_title}')
        if parsed.status:
            filter_parts.append(f'Status: {parsed.status}')
        if parsed.open_only:
            filter_parts.append("open only")

        filter_desc = " | ".join(filter_parts) if filter_parts else None

        # Determine fields to show
        fields_to_show = ["Status"]
        if parsed.missing_field and parsed.missing_field != "Status":
            fields_to_show.append(parsed.missing_field)

        # Output
        format_output(
            filtered, project.name, fields_to_show=fields_to_show, filter_desc=filter_desc
        )
        return 0

    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
