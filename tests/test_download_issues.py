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
