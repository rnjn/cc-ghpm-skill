"""Tests for scripts/download_issues.py."""

from scripts.download_issues import extract_fields


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


from scripts.download_issues import item_to_record


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
            "assignees": ["alice"],
            "fields": {"Status": "In Progress"},
        }

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


import json

from scripts.download_issues import export_to_json


class TestExportToJson:
    def test_wraps_records_with_metadata(self):
        records = [
            {"number": 1, "title": "a", "type": "Issue", "state": "OPEN",
             "url": "u", "assignees": ["alice"], "fields": {"Status": "Todo"}},
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


import csv
import io

from scripts.download_issues import export_to_csv


def _rows(csv_text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(csv_text)))


class TestExportToCsv:
    def test_header_is_core_columns_then_field_names(self):
        rows = _rows(export_to_csv([], ["Status", "Priority"]))
        assert rows[0] == [
            "number", "title", "type", "state", "url", "assignees", "Status", "Priority"
        ]

    def test_row_values_and_dynamic_columns(self):
        records = [
            {"number": 123, "title": "Fix bug", "type": "Issue", "state": "OPEN",
             "url": "https://x/123", "assignees": ["alice", "bob"],
             "fields": {"Status": "In Progress", "Priority": "P1"}},
        ]
        rows = _rows(export_to_csv(records, ["Status", "Priority"]))
        assert rows[1] == [
            "123", "Fix bug", "Issue", "OPEN", "https://x/123",
            "alice;bob", "In Progress", "P1",
        ]

    def test_empty_cells_for_draft_and_missing_fields(self):
        records = [
            {"number": None, "title": "Idea", "type": "DraftIssue", "state": None,
             "url": None, "assignees": [], "fields": {}},
        ]
        rows = _rows(export_to_csv(records, ["Status", "Priority"]))
        assert rows[1] == ["", "Idea", "DraftIssue", "", "", "", "", ""]
