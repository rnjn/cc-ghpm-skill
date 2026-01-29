#!/usr/bin/env python3
"""Update field values on GitHub Project items."""

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
    get_project_fields,
    get_project_items,
    get_project_node_id,
    load_config,
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
        description="Update field values on GitHub Project items",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project short name (from .env)",
    )
    parser.add_argument(
        "--items",
        required=True,
        help="Comma-separated issue numbers (e.g., 123,456,789)",
    )
    parser.add_argument(
        "--field",
        required=True,
        help="Field name to update",
    )
    parser.add_argument(
        "--value",
        required=True,
        help="Value to set",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    return parser.parse_args(args)


def parse_item_numbers(items_str: str) -> list[int]:
    """Parse comma-separated issue numbers.

    Args:
        items_str: Comma-separated issue numbers (e.g., "123, 456, #789")

    Returns:
        List of issue numbers
    """
    numbers = []
    for part in items_str.split(","):
        part = part.strip().lstrip("#")
        try:
            numbers.append(int(part))
        except ValueError:
            continue
    return numbers


def find_items_by_numbers(
    items: list[dict[str, Any]],
    numbers: list[int],
) -> list[dict[str, Any]]:
    """Find project items by issue number.

    Args:
        items: List of project items
        numbers: Issue numbers to find

    Returns:
        List of matching items in the order of input numbers
    """
    # Build lookup map
    by_number: dict[int, dict[str, Any]] = {}
    for item in items:
        content = item.get("content")
        if content and "number" in content:
            by_number[content["number"]] = item

    # Return in order
    result = []
    for num in numbers:
        if num in by_number:
            result.append(by_number[num])
    return result


def validate_field_value(
    field: dict[str, Any],
    value: str,
) -> dict[str, Any] | None:
    """Validate and format field value for GraphQL mutation.

    Args:
        field: Field definition
        value: Value to set

    Returns:
        Formatted value dict for GraphQL, or None if invalid
    """
    # Single select fields (Status, Priority, etc.)
    if "options" in field:
        for option in field["options"]:
            if option["name"].lower() == value.lower():
                return {"singleSelectOptionId": option["id"]}
        return None

    # Iteration fields
    if "configuration" in field and "iterations" in field.get("configuration", {}):
        for iteration in field["configuration"]["iterations"]:
            if iteration["title"].lower() == value.lower():
                return {"iterationId": iteration["id"]}
        return None

    # Text fields
    if field.get("dataType") == "TEXT":
        return {"text": value}

    # Number fields
    if field.get("dataType") == "NUMBER":
        try:
            return {"number": float(value)}
        except ValueError:
            return None

    # Default to text for unknown types
    return {"text": value}


def format_confirmation(
    items: list[dict[str, Any]],
    field_name: str,
    value: str,
) -> None:
    """Format and print confirmation prompt.

    Args:
        items: Items to be updated
        field_name: Field being updated
        value: New value
    """
    console.print(f"About to update {len(items)} issue{'s' if len(items) != 1 else ''}:")
    for item in items:
        content = item.get("content", {})
        number = content.get("number", "")
        title = content.get("title", "")
        if len(title) > 50:
            title = title[:47] + "..."
        console.print(f"  #{number}  {title}")

    console.print()
    console.print(f'Set "{field_name}" = "{value}"')
    console.print()


def format_update_result(
    item: dict[str, Any],
    field_name: str,
    value: str,
    success: bool,
) -> None:
    """Format and print single update result.

    Args:
        item: Updated item
        field_name: Field that was updated
        value: New value
        success: Whether update succeeded
    """
    content = item.get("content", {})
    number = content.get("number", "")
    title = content.get("title", "")
    if len(title) > 40:
        title = title[:37] + "..."

    if success:
        console.print(f"  #{number}  {title}  {field_name}: {value} [green]\u2713[/green]")
    else:
        console.print(f"  #{number}  {title}  {field_name}: {value} [red]\u2717[/red]")


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

        # Validate field exists
        field = get_field_by_name(fields, parsed.field)
        if not field:
            err_console.print(f"[red]Field '{parsed.field}' not found.[/red]")
            err_console.print("Available fields:")
            for f in fields:
                if "name" in f:
                    err_console.print(f"  - {f['name']}")
            return 1

        # Validate value
        field_value = validate_field_value(field, parsed.value)
        if field_value is None:
            err_console.print(
                f"[red]Invalid value '{parsed.value}' for field '{parsed.field}'.[/red]"
            )
            if "options" in field:
                err_console.print("Valid options:")
                for opt in field["options"]:
                    err_console.print(f"  - {opt['name']}")
            return 1

        # Parse issue numbers
        numbers = parse_item_numbers(parsed.items)
        if not numbers:
            err_console.print("[red]No valid issue numbers provided.[/red]")
            return 1

        # Fetch items and find matching
        all_items = get_project_items(project_id)
        items = find_items_by_numbers(all_items, numbers)

        if not items:
            err_console.print(
                f"[red]No items found for numbers: {', '.join(str(n) for n in numbers)}[/red]"
            )
            return 1

        # Report any not found
        found_numbers = {item["content"]["number"] for item in items}
        not_found = [n for n in numbers if n not in found_numbers]
        if not_found:
            err_console.print(
                f"[yellow]Warning: Issues not found in project: "
                f"{', '.join(str(n) for n in not_found)}[/yellow]"
            )

        # Confirmation
        format_confirmation(items, parsed.field, parsed.value)

        if not parsed.yes:
            response = input("Proceed? [y/N] ")
            if response.lower() not in ("y", "yes"):
                console.print("Cancelled.")
                return 0

        # Update items
        console.print(f"Updated {len(items)} issue{'s' if len(items) != 1 else ''}:")
        success_count = 0

        for item in items:
            try:
                update_item_field(project_id, item["id"], field["id"], field_value)
                format_update_result(item, parsed.field, parsed.value, success=True)
                success_count += 1
            except GHPMError as e:
                format_update_result(item, parsed.field, parsed.value, success=False)
                err_console.print(f"    Error: {e}")

        if success_count < len(items):
            err_console.print(
                f"\n[yellow]Warning: {len(items) - success_count} update(s) failed[/yellow]"
            )
            return 1

        return 0

    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
