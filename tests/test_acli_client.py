"""Tests for scripts/acli_client.py."""

import json
from unittest.mock import MagicMock

import pytest

from scripts.acli_client import acli_available, create_issue, transition_issues
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


def test_transition_issues_builds_batched_command(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    stdout = json.dumps(
        {
            "results": [
                {"status": "SUCCESS", "id": "B14-1"},
                {"status": "SUCCESS", "id": "B14-2"},
            ],
            "totalCount": 2,
            "successCount": 2,
        }
    )
    mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")

    success, fail_count, output = transition_issues(["B14-1", "B14-2"], "Done")

    assert success == 2
    assert fail_count == 0
    assert output == stdout
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd == [
        "acli",
        "jira",
        "workitem",
        "transition",
        "--key",
        "B14-1,B14-2",
        "--status",
        "Done",
        "--yes",
        "--ignore-errors",
        "--json",
    ]


def test_transition_issues_counts_failures(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    stdout = json.dumps(
        {
            "results": [
                {"status": "SUCCESS", "id": "B14-1"},
                {"status": "FAILURE", "id": "B14-2", "message": "not found"},
            ],
            "totalCount": 2,
            "successCount": 1,
        }
    )
    mock_subprocess_run.return_value = MagicMock(returncode=0, stdout=stdout, stderr="")

    success, fail_count, output = transition_issues(["B14-1", "B14-2"], "Done")

    assert success == 1
    assert fail_count == 1
    assert output == stdout


def test_transition_issues_raises_when_acli_missing(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    with pytest.raises(GHPMError, match="acli"):
        transition_issues(["B14-1"], "Done")
