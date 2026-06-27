#!/usr/bin/env python3
"""Thin wrapper around the Atlassian `acli` CLI."""

from __future__ import annotations

import shutil
import subprocess

from scripts.common import GHPMError


def acli_available() -> bool:
    """Return True if `acli` is on PATH."""
    return shutil.which("acli") is not None


def bulk_create(json_path: str, yes: bool = False) -> int:
    """Bulk-create Jira work items from a JSON file via acli.

    Returns acli's exit code. Raises GHPMError if acli is not installed.
    """
    if not acli_available():
        raise GHPMError("acli not found on PATH. Install Atlassian CLI and run 'acli jira auth'.")
    cmd = ["acli", "jira", "workitem", "create-bulk", "--from-json", json_path]
    if yes:
        cmd.append("--yes")
    result = subprocess.run(cmd)
    return result.returncode
