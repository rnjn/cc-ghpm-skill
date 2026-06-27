"""Tests for scripts/acli_client.py."""

from unittest.mock import MagicMock

import pytest

from scripts.acli_client import acli_available, create_issue
from scripts.common import GHPMError


def test_acli_available_reflects_which(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    assert acli_available() is True
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    assert acli_available() is False


def test_create_issue_returns_key_from_json(mock_subprocess_run, monkeypatch):
    import json

    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(
        returncode=0, stdout=json.dumps({"key": "B14-9", "fields": {}}), stderr=""
    )

    rc, key, output = create_issue({"summary": "x", "projectKey": "B14", "type": "Task"})

    assert rc == 0
    assert key == "B14-9"
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd[:5] == ["acli", "jira", "workitem", "create", "--from-json"]
    assert cmd[-1] == "--json"
    assert mock_subprocess_run.call_args.kwargs.get("capture_output") is True


def test_create_issue_failure_returns_none_key_and_output(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="request body invalid"
    )

    rc, key, output = create_issue({"summary": "x"})

    assert rc == 1
    assert key is None
    assert "request body invalid" in output


def test_create_issue_raises_when_acli_missing(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    with pytest.raises(GHPMError, match="acli"):
        create_issue({"summary": "x"})
