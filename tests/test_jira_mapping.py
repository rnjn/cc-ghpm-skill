"""Tests for scripts/jira_mapping.py."""

import json

import pytest

from scripts.common import GHPMError
from scripts.jira_mapping import DEFAULT_PRIORITY_MAP, load_priority_map, map_priority


class TestMapPriority:
    def test_identity_values(self):
        assert map_priority("Low", DEFAULT_PRIORITY_MAP) == "Low"
        assert map_priority("Medium", DEFAULT_PRIORITY_MAP) == "Medium"
        assert map_priority("High", DEFAULT_PRIORITY_MAP) == "High"

    def test_remapped_values(self):
        assert map_priority("Urgent", DEFAULT_PRIORITY_MAP) == "Highest"
        assert map_priority("Postponed", DEFAULT_PRIORITY_MAP) == "Lowest"

    def test_case_insensitive(self):
        assert map_priority("uRgEnT", DEFAULT_PRIORITY_MAP) == "Highest"

    def test_none_and_empty(self):
        assert map_priority(None, DEFAULT_PRIORITY_MAP) is None
        assert map_priority("", DEFAULT_PRIORITY_MAP) is None

    def test_unknown_value(self):
        assert map_priority("Blocker", DEFAULT_PRIORITY_MAP) is None

    def test_non_string_value_does_not_raise(self):
        # A non-string truthy value must not raise; just not match.
        assert map_priority(123, DEFAULT_PRIORITY_MAP) is None


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
