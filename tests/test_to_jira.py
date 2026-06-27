"""Tests for scripts/to_jira.py."""

import datetime
import json
from unittest.mock import patch

import pytest

from scripts.to_jira import (
    build_adf_description,
    issue_to_jira,
    main,
    parse_args,
    transform,
)


def _texts(doc):
    return [c["content"][0]["text"] for c in doc["content"] if c["content"]]


class TestBuildAdfDescription:
    def test_doc_shape(self):
        doc = build_adf_description("Hello", None)
        assert doc["type"] == "doc"
        assert doc["version"] == 1
        assert doc["content"][0]["type"] == "paragraph"

    def test_body_lines_and_url_footer(self):
        doc = build_adf_description("Line one\nLine two", "https://x/1")
        assert _texts(doc) == [
            "Line one",
            "Line two",
            "Imported from GitHub: https://x/1",
        ]

    def test_blank_lines_skipped(self):
        doc = build_adf_description("a\n\n  \nb", None)
        assert _texts(doc) == ["a", "b"]

    def test_empty_body_no_url_has_empty_paragraph(self):
        doc = build_adf_description("", None)
        assert doc["content"] == [{"type": "paragraph", "content": []}]

    def test_empty_body_with_url(self):
        doc = build_adf_description("", "https://x/9")
        assert _texts(doc) == ["Imported from GitHub: https://x/9"]


class TestIssueToJira:
    def _record(self, **over):
        rec = {
            "number": 1,
            "title": "Fix bug",
            "type": "Issue",
            "url": "https://x/1",
            "body": "details",
            "fields": {"Type": "Bug"},
        }
        rec.update(over)
        return rec

    def test_maps_core_fields(self):
        out = issue_to_jira(
            self._record(), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["summary"] == "Fix bug"
        assert out["projectKey"] == "SCOUT"
        assert out["type"] == "Bug"
        assert out["description"]["type"] == "doc"

    def test_issue_type_falls_back_to_default(self):
        out = issue_to_jira(
            self._record(fields={}), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["type"] == "Task"

    def test_missing_title_becomes_empty_string(self):
        out = issue_to_jira(
            self._record(title=None), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["summary"] == ""

    def test_adds_priority_when_mapped(self):
        from scripts.jira_mapping import DEFAULT_PRIORITY_MAP

        out = issue_to_jira(
            self._record(fields={"Priority": "Urgent"}),
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
            priority_field="Priority",
            priority_map=DEFAULT_PRIORITY_MAP,
        )
        assert out["additionalAttributes"] == {"priority": {"name": "Highest"}}

    def test_omits_additional_attributes_when_unmapped(self):
        from scripts.jira_mapping import DEFAULT_PRIORITY_MAP

        out = issue_to_jira(
            self._record(fields={"Priority": "Nope"}),
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
            priority_field="Priority",
            priority_map=DEFAULT_PRIORITY_MAP,
        )
        assert "additionalAttributes" not in out

    def test_omits_additional_attributes_when_no_priority_map(self):
        out = issue_to_jira(
            self._record(),
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
        )
        assert "additionalAttributes" not in out


class TestTransform:
    def test_filters_to_issues_only(self):
        export = {
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "", "fields": {"Type": "Bug"}},
                {"type": "PullRequest", "title": "PR", "url": "u2", "body": "", "fields": {}},
                {"type": "DraftIssue", "title": "D", "url": None, "body": "", "fields": {}},
            ]
        }
        issues = transform(export, project_key="SCOUT", type_field="Type", default_type="Task")
        assert len(issues) == 1
        assert issues[0]["summary"] == "A"
        assert issues[0]["type"] == "Bug"

    def test_handles_missing_items_key(self):
        assert transform({}, project_key="S", type_field="Type", default_type="Task") == []


EXPORT = {
    "project": "workX",
    "count": 2,
    "items": [
        {
            "number": 1,
            "title": "A",
            "type": "Issue",
            "state": "OPEN",
            "url": "https://x/1",
            "body": "hello",
            "assignees": [],
            "fields": {"Type": "Bug"},
        },
        {
            "number": 2,
            "title": "PR",
            "type": "PullRequest",
            "state": "OPEN",
            "url": "https://x/2",
            "body": "",
            "assignees": [],
            "fields": {},
        },
    ],
}


def _write_export(tmp_path):
    p = tmp_path / "export.json"
    p.write_text(json.dumps(EXPORT))
    return p


class TestParseArgs:
    def test_requires_input_and_project(self):
        with pytest.raises(SystemExit):
            parse_args(["--input", "x.json"])  # missing --jira-project

    def test_defaults(self):
        a = parse_args(["--input", "x.json", "--jira-project", "SCOUT"])
        assert a.type_field == "Type"
        assert a.default_type == "Task"
        assert a.dry_run is False
        assert a.yes is False


class TestMain:
    def test_dry_run_writes_file_and_skips_acli(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.create_issue") as ci:
            rc = main(
                [
                    "--input",
                    str(inp),
                    "--jira-project",
                    "SCOUT",
                    "--out",
                    str(out),
                    "--dry-run",
                ]
            )
        assert rc == 0
        ci.assert_not_called()
        payload = json.loads(out.read_text())
        assert len(payload["issues"]) == 1  # PR filtered out
        assert payload["issues"][0]["projectKey"] == "SCOUT"

    def test_creates_each_issue_after_confirmation(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue", return_value=(0, "created")) as ci:
                with patch("builtins.input", return_value="y"):
                    rc = main(["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out)])
        assert rc == 0
        ci.assert_called_once()
        # called with the issue object (not a path)
        assert ci.call_args[0][0]["summary"] == "A"

    def test_partial_failure_returns_nonzero(self, tmp_path):
        # Two Issues; the second create fails.
        export = {
            "project": "workX",
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "x", "fields": {}},
                {"type": "Issue", "title": "B", "url": "u2", "body": "y", "fields": {}},
            ],
        }
        inp = tmp_path / "two.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue", side_effect=[(0, "ok"), (1, "boom")]) as ci:
                rc = main(
                    ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                )
        assert rc != 0
        assert ci.call_count == 2

    def test_abort_when_user_declines(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue") as ci:
                with patch("builtins.input", return_value="n"):
                    rc = main(["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out)])
        assert rc != 0
        ci.assert_not_called()

    def test_yes_skips_prompt(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue", return_value=(0, "created")) as ci:
                with patch("builtins.input", side_effect=AssertionError("should not prompt")):
                    rc = main(
                        [
                            "--input",
                            str(inp),
                            "--jira-project",
                            "SCOUT",
                            "--out",
                            str(out),
                            "--yes",
                        ]
                    )
        assert rc == 0
        ci.assert_called_once()

    def test_errors_on_missing_acli(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=False):
            with patch("scripts.to_jira.create_issue") as ci:
                rc = main(
                    [
                        "--input",
                        str(inp),
                        "--jira-project",
                        "SCOUT",
                        "--out",
                        str(out),
                        "--yes",
                    ]
                )
        assert rc != 0
        ci.assert_not_called()

    def test_bad_input_file_returns_error(self, tmp_path):
        bad = tmp_path / "nope.json"
        rc = main(["--input", str(bad), "--jira-project", "SCOUT", "--dry-run"])
        assert rc != 0

    # Fix 4: auto-named output path
    def test_auto_named_output_path(self, tmp_path, monkeypatch):
        inp = _write_export(tmp_path)
        monkeypatch.chdir(tmp_path)
        with patch("scripts.to_jira.get_today", return_value=datetime.date(2026, 6, 27)):
            rc = main(
                [
                    "--input",
                    str(inp),
                    "--jira-project",
                    "workX",
                    "--dry-run",
                ]
            )
        assert rc == 0
        expected = tmp_path / "workX-jira-2026-06-27.json"
        assert expected.exists()

    # Fix 5: zero-issues short-circuit
    def test_zero_issues_short_circuits(self, tmp_path):
        empty_export = {
            "project": "workX",
            "count": 2,
            "items": [
                {
                    "number": 1,
                    "title": "PR",
                    "type": "PullRequest",
                    "state": "OPEN",
                    "url": "https://x/1",
                    "body": "",
                    "assignees": [],
                    "fields": {},
                },
                {
                    "number": 2,
                    "title": "D",
                    "type": "DraftIssue",
                    "state": "OPEN",
                    "url": None,
                    "body": "",
                    "assignees": [],
                    "fields": {},
                },
            ],
        }
        inp = tmp_path / "empty_export.json"
        inp.write_text(json.dumps(empty_export))
        out = tmp_path / "out.json"
        with patch("scripts.to_jira.create_issue") as ci:
            rc = main(
                [
                    "--input",
                    str(inp),
                    "--jira-project",
                    "SCOUT",
                    "--out",
                    str(out),
                ]
            )
        assert rc == 0
        ci.assert_not_called()
        assert not out.exists()
