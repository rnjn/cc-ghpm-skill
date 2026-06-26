"""Common utilities for GHPM scripts."""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


class GHPMError(Exception):
    """Base exception for GHPM errors."""

    pass


@dataclass
class ProjectConfig:
    """Configuration for a single GitHub project."""

    owner: str
    number: int
    name: str
    node_id: str | None = None


@dataclass
class Config:
    """Full GHPM configuration."""

    projects: list[ProjectConfig]
    status_field: str = "Status"
    iteration_field: str = "Iteration"
    done_status: str = "Done"

    def get_project(self, name: str) -> ProjectConfig | None:
        """Find project by name (case-insensitive)."""
        name_lower = name.lower()
        for project in self.projects:
            if project.name.lower() == name_lower:
                return project
        return None


def load_config(env_path: Path) -> Config:
    """Load configuration from .env file.

    Args:
        env_path: Path to .env file

    Returns:
        Config object with parsed settings

    Raises:
        GHPMError: If file not found or invalid format
    """
    if not env_path.exists():
        raise GHPMError(f"Configuration file not found: {env_path}")

    # Read and parse .env file
    env_vars: dict[str, str] = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                env_vars[key.strip()] = value.strip()

    # Parse projects
    projects: list[ProjectConfig] = []
    project_nums = set()
    for key in env_vars:
        match = re.match(r"PROJECT_(\d+)_OWNER", key)
        if match:
            project_nums.add(int(match.group(1)))

    for num in sorted(project_nums):
        owner = env_vars.get(f"PROJECT_{num}_OWNER")
        project_id = env_vars.get(f"PROJECT_{num}_ID")
        name = env_vars.get(f"PROJECT_{num}_NAME")

        if owner and project_id and name:
            projects.append(
                ProjectConfig(
                    owner=owner,
                    number=int(project_id),
                    name=name,
                )
            )

    return Config(
        projects=projects,
        status_field=env_vars.get("DEFAULT_STATUS_FIELD", "Status"),
        iteration_field=env_vars.get("DEFAULT_ITERATION_FIELD", "Iteration"),
        done_status=env_vars.get("DONE_STATUS", "Done"),
    )


def check_gh_auth() -> bool:
    """Check if GitHub CLI is authenticated.

    Returns:
        True if authenticated, False otherwise
    """
    try:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def run_graphql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Execute a GraphQL query via gh CLI.

    Args:
        query: GraphQL query string
        variables: Optional variables dict

    Returns:
        Parsed JSON response

    Raises:
        GHPMError: On query failure or GraphQL errors
    """
    cmd = ["gh", "api", "graphql", "-f", f"query={query}"]

    if variables:
        for key, value in variables.items():
            if isinstance(value, bool):
                cmd.extend(["-F", f"{key}={str(value).lower()}"])
            elif isinstance(value, int):
                cmd.extend(["-F", f"{key}={value}"])
            else:
                cmd.extend(["-f", f"{key}={value}"])

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise GHPMError(f"gh CLI error: {result.stderr}")

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise GHPMError(f"Invalid JSON response: {e}")

    if "errors" in data:
        error_msg = "; ".join(e.get("message", str(e)) for e in data["errors"])
        raise GHPMError(f"GraphQL error: {error_msg}")

    return data


def get_project_node_id(owner: str, number: int) -> str:
    """Fetch the node ID for a project.

    Args:
        owner: User or organization login
        number: Project number

    Returns:
        Project node ID (e.g., "PVT_...")

    Raises:
        GHPMError: If project not found
    """
    # Try user first
    query = """
    query($owner: String!, $number: Int!) {
        user(login: $owner) {
            projectV2(number: $number) {
                id
            }
        }
    }
    """
    try:
        result = run_graphql(query, {"owner": owner, "number": number})
        user_data = result.get("data", {}).get("user")
        if user_data and user_data.get("projectV2"):
            return user_data["projectV2"]["id"]
    except GHPMError:
        pass  # Fall through to organization query

    # Try organization
    query = """
    query($owner: String!, $number: Int!) {
        organization(login: $owner) {
            projectV2(number: $number) {
                id
            }
        }
    }
    """
    result = run_graphql(query, {"owner": owner, "number": number})

    org_data = result.get("data", {}).get("organization")
    if org_data and org_data.get("projectV2"):
        return org_data["projectV2"]["id"]

    raise GHPMError(f"Project not found: {owner}/project/{number}")


def get_project_fields(project_id: str) -> list[dict[str, Any]]:
    """Fetch field definitions for a project.

    Args:
        project_id: Project node ID

    Returns:
        List of field definitions
    """
    query = """
    query($projectId: ID!) {
        node(id: $projectId) {
            ... on ProjectV2 {
                fields(first: 50) {
                    nodes {
                        ... on ProjectV2Field {
                            id
                            name
                            dataType
                        }
                        ... on ProjectV2IterationField {
                            id
                            name
                            configuration {
                                iterations {
                                    id
                                    title
                                    startDate
                                    duration
                                }
                                completedIterations {
                                    id
                                    title
                                    startDate
                                    duration
                                }
                            }
                        }
                        ... on ProjectV2SingleSelectField {
                            id
                            name
                            options {
                                id
                                name
                            }
                        }
                    }
                }
            }
        }
    }
    """
    result = run_graphql(query, {"projectId": project_id})
    return result["data"]["node"]["fields"]["nodes"]


def get_project_items(
    project_id: str,
    max_items: int = 500,
) -> list[dict[str, Any]]:
    """Fetch all items from a project with pagination.

    Args:
        project_id: Project node ID
        max_items: Maximum items to fetch

    Returns:
        List of project items
    """
    query = """
    query($projectId: ID!, $cursor: String) {
        node(id: $projectId) {
            ... on ProjectV2 {
                items(first: 100, after: $cursor) {
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                    nodes {
                        id
                        content {
                            __typename
                            ... on Issue {
                                number
                                title
                                state
                                url
                                assignees(first: 10) { nodes { login } }
                            }
                            ... on PullRequest {
                                number
                                title
                                state
                                url
                                assignees(first: 10) { nodes { login } }
                            }
                            ... on DraftIssue {
                                title
                                assignees(first: 10) { nodes { login } }
                            }
                        }
                        fieldValues(first: 20) {
                            nodes {
                                ... on ProjectV2ItemFieldTextValue {
                                    field { ... on ProjectV2Field { name } }
                                    text
                                }
                                ... on ProjectV2ItemFieldSingleSelectValue {
                                    field { ... on ProjectV2SingleSelectField { name } }
                                    name
                                }
                                ... on ProjectV2ItemFieldIterationValue {
                                    field { ... on ProjectV2IterationField { name } }
                                    iterationId
                                    title
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """
    items: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(items) < max_items:
        variables: dict[str, Any] = {"projectId": project_id}
        if cursor:
            variables["cursor"] = cursor

        result = run_graphql(query, variables)
        page = result["data"]["node"]["items"]
        items.extend(page["nodes"])

        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    return items


def get_today() -> date:
    """Get today's date. Separate function for testing."""
    return date.today()


def resolve_iteration_keyword(
    iterations: list[dict[str, Any]],
    keyword: str,
    completed_iterations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve iteration keyword (previous/current/next) or title to iteration.

    Args:
        iterations: List of active iteration objects with startDate and duration
        keyword: "previous", "current", "next", or iteration title
        completed_iterations: Optional list of completed iterations (for "previous")

    Returns:
        Matching iteration object

    Raises:
        GHPMError: If iteration not found
    """
    # Check for exact title match first (in both active and completed)
    for iteration in iterations:
        if iteration["title"].lower() == keyword.lower():
            return iteration
    if completed_iterations:
        for iteration in completed_iterations:
            if iteration["title"].lower() == keyword.lower():
                return iteration

    # Handle keywords
    if keyword.lower() not in ("previous", "current", "next"):
        raise GHPMError(f"Iteration not found: {keyword}")

    today = get_today()

    # Find current iteration (the one containing today)
    current_idx = None
    for i, iteration in enumerate(iterations):
        start = date.fromisoformat(iteration["startDate"])
        end = start + timedelta(days=iteration["duration"])
        if start <= today < end:
            current_idx = i
            break

    # If no current found, find the most recent past or next future
    if current_idx is None:
        # Find closest iteration
        for i, iteration in enumerate(iterations):
            start = date.fromisoformat(iteration["startDate"])
            if start <= today:
                current_idx = i
            else:
                # We've passed today, use previous as current
                if current_idx is None:
                    current_idx = i
                break

    if current_idx is None:
        raise GHPMError("Could not determine current iteration")

    if keyword.lower() == "current":
        return iterations[current_idx]
    elif keyword.lower() == "previous":
        if current_idx == 0:
            # Check completed iterations for the most recent one
            if completed_iterations and len(completed_iterations) > 0:
                return completed_iterations[0]  # Most recent completed
            raise GHPMError("No previous iteration available")
        return iterations[current_idx - 1]
    else:  # next
        if current_idx >= len(iterations) - 1:
            raise GHPMError("No next iteration available")
        return iterations[current_idx + 1]


def update_item_field(
    project_id: str,
    item_id: str,
    field_id: str,
    value: dict[str, Any],
) -> bool:
    """Update a field value on a project item.

    Args:
        project_id: Project node ID
        item_id: Item node ID
        field_id: Field node ID
        value: Field value (format depends on field type)

    Returns:
        True if successful
    """
    mutation = (
        "mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, "
        "$value: ProjectV2FieldValue!) { "
        "updateProjectV2ItemFieldValue(input: { "
        "projectId: $projectId, itemId: $itemId, fieldId: $fieldId, value: $value "
        "}) { projectV2Item { id } } }"
    )

    # Use stdin to pass complex JSON variables properly
    request_body = json.dumps(
        {
            "query": mutation,
            "variables": {
                "projectId": project_id,
                "itemId": item_id,
                "fieldId": field_id,
                "value": value,
            },
        }
    )

    result = subprocess.run(
        ["gh", "api", "graphql", "--input", "-"],
        input=request_body,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise GHPMError(f"Failed to update item: {result.stderr}")

    # Check for GraphQL errors in response
    try:
        response = json.loads(result.stdout)
        if "errors" in response:
            error_msg = response["errors"][0].get("message", "Unknown error")
            raise GHPMError(f"Failed to update item: {error_msg}")
    except json.JSONDecodeError:
        pass

    return True


def get_field_by_name(
    fields: list[dict[str, Any]],
    name: str,
) -> dict[str, Any] | None:
    """Find a field by name (case-insensitive).

    Args:
        fields: List of field definitions
        name: Field name to find

    Returns:
        Field definition or None
    """
    name_lower = name.lower()
    for field in fields:
        if field.get("name", "").lower() == name_lower:
            return field
    return None


def get_item_field_value(
    item: dict[str, Any],
    field_name: str,
) -> str | None:
    """Extract field value from an item.

    Args:
        item: Project item
        field_name: Name of field to get

    Returns:
        Field value as string, or None if not set
    """
    field_values = item.get("fieldValues", {}).get("nodes", [])
    for fv in field_values:
        field = fv.get("field", {})
        if field.get("name", "").lower() == field_name.lower():
            # Different value types
            if "text" in fv:
                return fv["text"]
            if "name" in fv and "field" in fv:
                return fv["name"]
            if "title" in fv:
                return fv["title"]
    return None


def find_env_file() -> Path:
    """Find .env file, checking script directory first.

    Returns:
        Path to .env file

    Raises:
        GHPMError: If .env file not found
    """
    # Check script directory
    script_dir = Path(__file__).parent.parent
    env_path = script_dir / ".env"
    if env_path.exists():
        return env_path

    # Check current directory
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env

    raise GHPMError("No .env file found. Create one based on .env.example")
