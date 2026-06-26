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
