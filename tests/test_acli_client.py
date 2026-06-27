"""Tests for scripts/acli_client.py."""

from unittest.mock import MagicMock

import pytest

from scripts.acli_client import acli_available, bulk_create
from scripts.common import GHPMError


def test_acli_available_reflects_which(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    assert acli_available() is True
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    assert acli_available() is False


def test_bulk_create_builds_command_with_yes(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(returncode=0)

    rc = bulk_create("out.json", yes=True)

    assert rc == 0
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd == ["acli", "jira", "workitem", "create-bulk", "--from-json", "out.json", "--yes"]


def test_bulk_create_without_yes_omits_flag(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(returncode=2)

    rc = bulk_create("out.json")

    assert rc == 2
    assert "--yes" not in mock_subprocess_run.call_args[0][0]


def test_bulk_create_raises_when_acli_missing(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    with pytest.raises(GHPMError, match="acli"):
        bulk_create("out.json")
