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

    def test_iter_issue_records_filters_issues(self):
        from scripts.to_jira import iter_issue_records

        export = {
            "items": [
                {"type": "Issue", "title": "A"},
                {"type": "PullRequest", "title": "PR"},
                {"type": "DraftIssue", "title": "D"},
            ]
        }
        recs = iter_issue_records(export)
        assert [r["title"] for r in recs] == ["A"]

    def test_transform_forwards_priority_map(self):
        from scripts.jira_mapping import DEFAULT_PRIORITY_MAP

        export = {
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u",
                    "body": "",
                    "fields": {"Priority": "High"},
                },
            ]
        }
        issues = transform(
            export,
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
            priority_field="Priority",
            priority_map=DEFAULT_PRIORITY_MAP,
        )
        assert issues[0]["additionalAttributes"] == {"priority": {"name": "High"}}


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

    def test_priority_defaults(self):
        a = parse_args(["--input", "x.json", "--jira-project", "SCOUT"])
        assert a.priority_field == "Priority"
        assert a.priority_map_file is None

    def test_status_defaults(self):
        a = parse_args(["--input", "x.json", "--jira-project", "SCOUT"])
        assert a.status_field == "Status"
        assert a.status_map_file is None
        assert a.initial_status == "To Do"


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
            with patch("scripts.to_jira.create_issue", return_value=(0, "B14-1", "created")) as ci:
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
            with patch(
                "scripts.to_jira.create_issue", side_effect=[(0, "B14-1", "ok"), (1, None, "boom")]
            ) as ci:
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
            with patch("scripts.to_jira.create_issue", return_value=(0, "B14-1", "created")) as ci:
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

    def test_priority_in_written_file(self, tmp_path):
        export = {
            "project": "workX",
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u1",
                    "body": "x",
                    "fields": {"Priority": "Urgent"},
                },
            ],
        }
        inp = tmp_path / "p.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        rc = main(["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--dry-run"])
        assert rc == 0
        payload = json.loads(out.read_text())
        assert payload["issues"][0]["additionalAttributes"] == {"priority": {"name": "Highest"}}

    def test_warns_once_per_distinct_unmapped_priority(self, tmp_path, capsys):
        export = {
            "project": "workX",
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u1",
                    "body": "",
                    "fields": {"Priority": "Blocker"},
                },
                {
                    "type": "Issue",
                    "title": "B",
                    "url": "u2",
                    "body": "",
                    "fields": {"Priority": "Blocker"},
                },
                {
                    "type": "Issue",
                    "title": "C",
                    "url": "u3",
                    "body": "",
                    "fields": {"Priority": "Wishlist"},
                },
            ],
        }
        inp = tmp_path / "p.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        rc = main(["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--dry-run"])
        assert rc == 0
        err = capsys.readouterr().err
        assert err.count("Blocker") == 1  # warned once despite two issues
        assert "Wishlist" in err

    def test_no_warning_for_mapped_or_unset_priority(self, tmp_path, capsys):
        export = {
            "project": "workX",
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u1",
                    "body": "",
                    "fields": {"Priority": "High"},
                },
                {"type": "Issue", "title": "B", "url": "u2", "body": "", "fields": {}},
            ],
        }
        inp = tmp_path / "p.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        rc = main(["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--dry-run"])
        assert rc == 0
        err = capsys.readouterr().err
        assert "not mapped" not in err
        assert "Warning" not in err

    def _status_export(self):
        return {
            "project": "workX",
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u1",
                    "body": "",
                    "fields": {"Status": "In Progress"},
                },
                {
                    "type": "Issue",
                    "title": "B",
                    "url": "u2",
                    "body": "",
                    "fields": {"Status": "In Progress"},
                },
                {
                    "type": "Issue",
                    "title": "C",
                    "url": "u3",
                    "body": "",
                    "fields": {"Status": "Done"},
                },
                {
                    "type": "Issue",
                    "title": "D",
                    "url": "u4",
                    "body": "",
                    "fields": {"Status": "Todo"},
                },
            ],
        }

    def test_transitions_grouped_by_status_skipping_initial(self, tmp_path):
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(self._status_export()))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch(
                "scripts.to_jira.create_issue",
                side_effect=[(0, "K1", "ok"), (0, "K2", "ok"), (0, "K3", "ok"), (0, "K4", "ok")],
            ):
                with patch("scripts.to_jira.transition_issues", return_value=(0, 0, "")) as tr:
                    rc = main(
                        ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                    )
        assert rc == 0
        # Grouped: In Progress -> [K1, K2], Done -> [K3]; Todo (==initial) skipped.
        calls = {c.args[1]: c.args[0] for c in tr.call_args_list}
        assert calls["In Progress"] == ["K1", "K2"]
        assert calls["Done"] == ["K3"]
        assert "To Do" not in calls

    def test_unmapped_status_warns_once_and_skips(self, tmp_path, capsys):
        export = {
            "project": "workX",
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u1",
                    "body": "",
                    "fields": {"Status": "Weird"},
                },
                {
                    "type": "Issue",
                    "title": "B",
                    "url": "u2",
                    "body": "",
                    "fields": {"Status": "Weird"},
                },
            ],
        }
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch(
                "scripts.to_jira.create_issue", side_effect=[(0, "K1", "ok"), (0, "K2", "ok")]
            ):
                with patch("scripts.to_jira.transition_issues") as tr:
                    rc = main(
                        ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                    )
        assert rc == 0
        tr.assert_not_called()
        assert capsys.readouterr().err.count("Weird") == 1

    def test_failed_transition_group_retried_once(self, tmp_path):
        export = {
            "project": "workX",
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u1",
                    "body": "",
                    "fields": {"Status": "Done"},
                },
            ],
        }
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue", side_effect=[(0, "K1", "ok")]):
                with patch(
                    "scripts.to_jira.transition_issues",
                    side_effect=[(0, 1, "lag"), (1, 0, "")],
                ) as tr:
                    rc = main(
                        ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                    )
        assert rc == 0
        assert tr.call_count == 2  # first failed, retried once

    def test_created_without_key_warns_and_skips_transition(self, tmp_path, capsys):
        export = {
            "project": "workX",
            "items": [
                {
                    "type": "Issue",
                    "title": "A",
                    "url": "u1",
                    "body": "",
                    "fields": {"Status": "Done"},
                },
            ],
        }
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        from unittest.mock import MagicMock

        tr = MagicMock()
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue", side_effect=[(0, None, "ok")]):
                with patch("scripts.to_jira.transition_issues", tr):
                    rc = main(
                        ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                    )
        assert rc == 0
        tr.assert_not_called()
        assert "could not capture its key" in capsys.readouterr().err

    def test_dry_run_prints_status_plan_and_calls_nothing(self, tmp_path, capsys):
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(self._status_export()))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.create_issue") as ci:
            with patch("scripts.to_jira.transition_issues") as tr:
                rc = main(
                    ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--dry-run"]
                )
        assert rc == 0
        ci.assert_not_called()
        tr.assert_not_called()
        outerr = capsys.readouterr().out
        assert "In Progress" in outerr and "Done" in outerr
