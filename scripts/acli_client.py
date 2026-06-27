#!/usr/bin/env python3
"""Thin wrapper around the Atlassian `acli` CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any

from scripts.common import GHPMError


def acli_available() -> bool:
    """Return True if `acli` is on PATH."""
    return shutil.which("acli") is not None


def create_issue(issue: dict[str, Any]) -> tuple[int, str | None, str]:
    """Create a single Jira work item from an issue dict via acli.

    Writes the issue to a temp JSON file and runs
    `acli jira workitem create --from-json <file> --json`. Returns
    (exit_code, key_or_None, combined_output). Raises GHPMError if acli is missing.
    """
    if not acli_available():
        raise GHPMError("acli not found on PATH. Install Atlassian CLI and run 'acli jira auth'.")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(issue, f)
        path = f.name
    try:
        result = subprocess.run(
            ["acli", "jira", "workitem", "create", "--from-json", path, "--json"],
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(path)

    key: str | None = None
    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            key = data.get("key")
    except (json.JSONDecodeError, TypeError):
        pass
    return result.returncode, key, (result.stdout or "") + (result.stderr or "")


def transition_issues(keys: list[str], status: str) -> tuple[int, int, str]:
    """Transition the given issue keys to a target status via acli (batched).

    Returns (success_count, fail_count, combined_output). Parses --json output
    from acli to determine real success/failure regardless of exit code.
    Raises GHPMError if acli is missing.
    """
    if not acli_available():
        raise GHPMError("acli not found on PATH. Install Atlassian CLI and run 'acli jira auth'.")
    result = subprocess.run(
        [
            "acli",
            "jira",
            "workitem",
            "transition",
            "--key",
            ",".join(keys),
            "--status",
            status,
            "--yes",
            "--ignore-errors",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    try:
        data = json.loads(result.stdout)
        success_count = data.get("successCount", 0)
        fail_count = sum(1 for r in data.get("results", []) if r.get("status") != "SUCCESS")
    except (json.JSONDecodeError, TypeError):
        success_count = 0
        fail_count = len(keys)
    return success_count, fail_count, combined
