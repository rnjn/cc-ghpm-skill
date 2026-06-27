"""Tests for scripts/download_issues.py."""

import csv
import io
import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.download_issues import (
    export_to_csv,
    export_to_json,
    extract_fields,
    item_to_record,
    main,
    parse_args,
)


class TestExtractFields:
    def test_extracts_single_select_and_iteration_and_text(self):
        item = {
            "fieldValues": {
                "nodes": [
                    {"field": {"name": "Status"}, "name": "In Progress"},
                    {"field": {"name": "Iteration"}, "iterationId": "I2", "title": "Iteration 2"},
                    {"field": {"name": "Notes"}, "text": "hello"},
                ]
            }
        }
        assert extract_fields(item) == {
            "Status": "In Progress",
            "Iteration": "Iteration 2",
            "Notes": "hello",
        }

    def test_skips_nodes_without_a_named_field(self):
        item = {"fieldValues": {"nodes": [{}, {"field": {}, "name": "x"}]}}
        assert extract_fields(item) == {}

    def test_handles_missing_field_values(self):
        assert extract_fields({}) == {}


class TestItemToRecord:
    def test_normalizes_issue_with_assignees_and_fields(self):
        item = {
            "id": "I1",
            "content": {
                "__typename": "Issue",
                "number": 123,
                "title": "Fix login bug",
                "state": "OPEN",
                "url": "https://github.com/o/r/issues/123",
                "body": "Steps to reproduce",
                "assignees": {"nodes": [{"login": "alice"}]},
            },
            "fieldValues": {"nodes": [{"field": {"name": "Status"}, "name": "In Progress"}]},
        }
        assert item_to_record(item) == {
            "number": 123,
            "title": "Fix login bug",
            "type": "Issue",
            "state": "OPEN",
            "url": "https://github.com/o/r/issues/123",
            "body": "Steps to reproduce",
            "assignees": ["alice"],
            "fields": {"Status": "In Progress"},
        }

    def test_body_is_none_when_absent(self):
        item = {"content": {"__typename": "Issue", "title": "x"}, "fieldValues": {"nodes": []}}
        assert item_to_record(item)["body"] is None

    def test_normalizes_pull_request(self):
        item = {
            "content": {
                "__typename": "PullRequest",
                "number": 9,
                "title": "Add CI",
                "state": "OPEN",
                "url": "https://github.com/o/r/pull/9",
                "assignees": {"nodes": [{"login": "bob"}]},
            },
            "fieldValues": {"nodes": []},
        }
        record = item_to_record(item)
        assert record["type"] == "PullRequest"
        assert record["number"] == 9
        assert record["assignees"] == ["bob"]

    def test_normalizes_draft_issue_with_no_number(self):
        item = {
            "content": {"__typename": "DraftIssue", "title": "Idea", "assignees": {"nodes": []}},
            "fieldValues": {"nodes": []},
        }
        record = item_to_record(item)
        assert record["type"] == "DraftIssue"
        assert record["number"] is None
        assert record["state"] is None
        assert record["url"] is None
        assert record["assignees"] == []
        assert record["title"] == "Idea"

    def test_handles_null_content(self):
        record = item_to_record({"content": None, "fieldValues": {"nodes": []}})
        assert record["type"] is None
        assert record["number"] is None
        assert record["assignees"] == []


class TestExportToJson:
    def test_wraps_records_with_metadata(self):
        records = [
            {
                "number": 1,
                "title": "a",
                "type": "Issue",
                "state": "OPEN",
                "url": "u",
                "assignees": ["alice"],
                "fields": {"Status": "Todo"},
            },
        ]
        out = export_to_json(records, "backend", "2026-06-26T14:32:00Z")
        parsed = json.loads(out)
        assert parsed["project"] == "backend"
        assert parsed["exported_at"] == "2026-06-26T14:32:00Z"
        assert parsed["count"] == 1
        assert parsed["items"] == records

    def test_empty_records(self):
        parsed = json.loads(export_to_json([], "backend", "2026-06-26T00:00:00Z"))
        assert parsed["count"] == 0
        assert parsed["items"] == []


def _rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


class TestExportToCsv:
    def test_header_is_core_columns_then_field_names(self):
        rows = _rows(export_to_csv([], ["Status", "Priority"]))
        assert rows[0] == [
            "number",
            "title",
            "type",
            "state",
            "url",
            "assignees",
            "Status",
            "Priority",
        ]

    def test_row_values_and_dynamic_columns(self):
        records = [
            {
                "number": 123,
                "title": "Fix bug",
                "type": "Issue",
                "state": "OPEN",
                "url": "https://x/123",
                "assignees": ["alice", "bob"],
                "fields": {"Status": "In Progress", "Priority": "P1"},
            },
        ]
        rows = _rows(export_to_csv(records, ["Status", "Priority"]))
        assert rows[1] == [
            "123",
            "Fix bug",
            "Issue",
            "OPEN",
            "https://x/123",
            "alice;bob",
            "In Progress",
            "P1",
        ]

    def test_empty_cells_for_draft_and_missing_fields(self):
        records = [
            {
                "number": None,
                "title": "Idea",
                "type": "DraftIssue",
                "state": None,
                "url": None,
                "assignees": [],
                "fields": {},
            },
        ]
        rows = _rows(export_to_csv(records, ["Status", "Priority"]))
        assert rows[1] == ["", "Idea", "DraftIssue", "", "", "", "", ""]


def _gh(data, returncode=0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = json.dumps(data) if data else ""
    r.stderr = ""
    return r


FIELDS_RESPONSE = {
    "data": {
        "node": {
            "fields": {
                "nodes": [
                    {"id": "F0", "name": "Title", "dataType": "TITLE"},
                    {"id": "F1", "name": "Status", "options": [{"id": "O1", "name": "Todo"}]},
                    {"id": "F2", "name": "Priority", "options": [{"id": "P1", "name": "P1"}]},
                ]
            }
        }
    }
}

ITEMS_RESPONSE = {
    "data": {
        "node": {
            "items": {
                "pageInfo": {"hasNextPage": False, "endCursor": None},
                "nodes": [
                    {
                        "id": "IT1",
                        "content": {
                            "__typename": "Issue",
                            "number": 123,
                            "title": "Fix bug",
                            "state": "OPEN",
                            "url": "https://x/123",
                            "assignees": {"nodes": [{"login": "alice"}]},
                        },
                        "fieldValues": {
                            "nodes": [
                                {"field": {"name": "Status"}, "name": "In Progress"},
                                {"field": {"name": "Priority"}, "name": "P1"},
                            ]
                        },
                    },
                    {
                        "id": "IT2",
                        "content": {
                            "__typename": "DraftIssue",
                            "title": "Idea",
                            "assignees": {"nodes": []},
                        },
                        "fieldValues": {"nodes": []},
                    },
                ],
            }
        }
    }
}

NODE_ID_RESPONSE = {"data": {"user": {"projectV2": {"id": "PVT_x"}}}}


class TestParseArgs:
    def test_requires_project(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_defaults_to_json(self):
        args = parse_args(["--project", "backend"])
        assert args.project == "backend"
        assert args.format == "json"
        assert args.output_file is None

    def test_parses_csv_and_output_file(self):
        args = parse_args(["--project", "backend", "--format", "csv", "--output-file", "out.csv"])
        assert args.format == "csv"
        assert args.output_file == "out.csv"


class TestMain:
    @pytest.fixture
    def env_file(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text(
            "PROJECT_1_OWNER=myorg\nPROJECT_1_ID=123\nPROJECT_1_NAME=backend\n"
            "DEFAULT_STATUS_FIELD=Status\nDEFAULT_ITERATION_FIELD=Iteration\nDONE_STATUS=Done\n"
        )
        return f

    def _patches(self, env_file, mock_subprocess_run):
        mock_subprocess_run.side_effect = [
            _gh({}),  # check_gh_auth
            _gh(NODE_ID_RESPONSE),  # get_project_node_id (user)
            _gh(FIELDS_RESPONSE),  # get_project_fields
            _gh(ITEMS_RESPONSE),  # get_project_items
        ]

    def test_writes_json_to_given_output_file(self, env_file, tmp_path, mock_subprocess_run):
        self._patches(env_file, mock_subprocess_run)
        out = tmp_path / "dump.json"
        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            rc = main(["--project", "backend", "--output-file", str(out)])
        assert rc == 0
        parsed = json.loads(out.read_text())
        assert parsed["project"] == "backend"
        assert parsed["count"] == 2
        assert parsed["items"][0]["number"] == 123
        assert parsed["items"][0]["assignees"] == ["alice"]
        assert parsed["items"][1]["type"] == "DraftIssue"

    def test_writes_csv_with_dynamic_columns(self, env_file, tmp_path, mock_subprocess_run):
        self._patches(env_file, mock_subprocess_run)
        out = tmp_path / "dump.csv"
        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            rc = main(["--project", "backend", "--format", "csv", "--output-file", str(out)])
        assert rc == 0
        rows = list(csv.reader(io.StringIO(out.read_text())))
        assert rows[0] == [
            "number",
            "title",
            "type",
            "state",
            "url",
            "assignees",
            "Status",
            "Priority",
        ]
        assert rows[1] == [
            "123",
            "Fix bug",
            "Issue",
            "OPEN",
            "https://x/123",
            "alice",
            "In Progress",
            "P1",
        ]
        assert rows[2] == ["", "Idea", "DraftIssue", "", "", "", "", ""]

    def test_auto_names_file_in_cwd(self, env_file, tmp_path, monkeypatch, mock_subprocess_run):
        self._patches(env_file, mock_subprocess_run)
        monkeypatch.chdir(tmp_path)
        import datetime as _dt

        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            with patch("scripts.download_issues.get_today", return_value=_dt.date(2026, 6, 26)):
                rc = main(["--project", "backend"])
        assert rc == 0
        assert (tmp_path / "backend-items-2026-06-26.json").exists()

    def test_errors_on_unknown_project(self, env_file, mock_subprocess_run):
        mock_subprocess_run.side_effect = [_gh({})]  # auth only
        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            rc = main(["--project", "nope"])
        assert rc != 0
