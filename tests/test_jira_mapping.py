"""Tests for scripts/jira_mapping.py."""

import json

import pytest

from scripts.common import GHPMError
from scripts.jira_mapping import (
    DEFAULT_PRIORITY_MAP,
    DEFAULT_STATUS_MAP,
    load_priority_map,
    load_status_map,
    map_value,
)


class TestMapValue:
    def test_identity_values(self):
        assert map_value("Low", DEFAULT_PRIORITY_MAP) == "Low"
        assert map_value("Medium", DEFAULT_PRIORITY_MAP) == "Medium"
        assert map_value("High", DEFAULT_PRIORITY_MAP) == "High"

    def test_remapped_values(self):
        assert map_value("Urgent", DEFAULT_PRIORITY_MAP) == "Highest"
        assert map_value("Postponed", DEFAULT_PRIORITY_MAP) == "Lowest"

    def test_case_insensitive(self):
        assert map_value("uRgEnT", DEFAULT_PRIORITY_MAP) == "Highest"

    def test_none_and_empty(self):
        assert map_value(None, DEFAULT_PRIORITY_MAP) is None
        assert map_value("", DEFAULT_PRIORITY_MAP) is None

    def test_unknown_value(self):
        assert map_value("Blocker", DEFAULT_PRIORITY_MAP) is None

    def test_non_string_value_does_not_raise(self):
        # A non-string truthy value must not raise; just not match.
        assert map_value(123, DEFAULT_PRIORITY_MAP) is None


class TestLoadPriorityMap:
    def test_none_returns_defaults_copy(self):
        m = load_priority_map(None)
        assert m == DEFAULT_PRIORITY_MAP
        m["low"] = "CHANGED"
        assert DEFAULT_PRIORITY_MAP["low"] == "Low"  # returned a copy, defaults intact

    def test_override_merges_over_defaults(self, tmp_path):
        f = tmp_path / "map.json"
        f.write_text(json.dumps({"Postponed": "Low", "Blocker": "Highest"}))
        m = load_priority_map(str(f))
        assert m["postponed"] == "Low"  # overridden
        assert m["blocker"] == "Highest"  # added
        assert m["urgent"] == "Highest"  # default still present

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(GHPMError):
            load_priority_map(str(tmp_path / "nope.json"))

    def test_invalid_json_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json")
        with pytest.raises(GHPMError):
            load_priority_map(str(f))

    def test_non_object_raises(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text("[1, 2, 3]")
        with pytest.raises(GHPMError):
            load_priority_map(str(f))


class TestStatusMap:
    def test_default_status_map(self):
        assert DEFAULT_STATUS_MAP == {
            "todo": "To Do",
            "in progress": "In Progress",
            "in review": "In Review",
            "blocked": "Blocked",
            "done": "Done",
        }

    def test_map_value_with_status_map(self):
        assert map_value("Todo", DEFAULT_STATUS_MAP) == "To Do"
        assert map_value("in review", DEFAULT_STATUS_MAP) == "In Review"
        assert map_value("Nope", DEFAULT_STATUS_MAP) is None

    def test_load_status_map_none_returns_defaults_copy(self):
        m = load_status_map(None)
        assert m == DEFAULT_STATUS_MAP
        m["todo"] = "CHANGED"
        assert DEFAULT_STATUS_MAP["todo"] == "To Do"

    def test_load_status_map_override(self, tmp_path):
        f = tmp_path / "s.json"
        f.write_text(json.dumps({"Blocked": "On Hold", "Backlog": "To Do"}))
        m = load_status_map(str(f))
        assert m["blocked"] == "On Hold"
        assert m["backlog"] == "To Do"
        assert m["done"] == "Done"

    def test_load_status_map_invalid_raises(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("[1,2]")
        with pytest.raises(Exception):
            load_status_map(str(f))
