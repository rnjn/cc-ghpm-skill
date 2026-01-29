"""Tests for scripts/list_items.py."""

from unittest.mock import patch

import pytest

from scripts.list_items import (
    filter_items,
    format_output,
    main,
    parse_args,
)


class TestParseArgs:
    """Tests for argument parsing."""

    def test_requires_project(self):
        """Should require --project argument."""
        with pytest.raises(SystemExit):
            parse_args([])

    def test_parses_project(self):
        """Should parse --project argument."""
        args = parse_args(["--project", "backend"])
        assert args.project == "backend"

    def test_parses_missing_field(self):
        """Should parse --missing-field argument."""
        args = parse_args(["--project", "backend", "--missing-field", "Priority"])
        assert args.missing_field == "Priority"

    def test_parses_iteration(self):
        """Should parse --iteration argument."""
        args = parse_args(["--project", "backend", "--iteration", "current"])
        assert args.iteration == "current"

    def test_parses_status(self):
        """Should parse --status argument."""
        args = parse_args(["--project", "backend", "--status", "In Progress"])
        assert args.status == "In Progress"

    def test_parses_open_only(self):
        """Should parse --open-only flag."""
        args = parse_args(["--project", "backend", "--open-only"])
        assert args.open_only is True

    def test_parses_show_iterations(self):
        """Should parse --show-iterations flag."""
        args = parse_args(["--project", "backend", "--show-iterations"])
        assert args.show_iterations is True


class TestFilterItems:
    """Tests for filter_items function."""

    @pytest.fixture
    def sample_items(self):
        """Sample project items for filtering."""
        return [
            {
                "id": "ITEM_1",
                "content": {
                    "number": 123,
                    "title": "Fix login bug",
                    "state": "OPEN",
                },
                "fieldValues": {
                    "nodes": [
                        {"field": {"name": "Status"}, "name": "In Progress"},
                        {"field": {"name": "Iteration"}, "title": "Iteration 2"},
                        {"field": {"name": "Priority"}, "name": "P1"},
                    ]
                },
            },
            {
                "id": "ITEM_2",
                "content": {
                    "number": 456,
                    "title": "Add dark mode",
                    "state": "OPEN",
                },
                "fieldValues": {
                    "nodes": [
                        {"field": {"name": "Status"}, "name": "Todo"},
                        {"field": {"name": "Iteration"}, "title": "Iteration 2"},
                        # No Priority field
                    ]
                },
            },
            {
                "id": "ITEM_3",
                "content": {
                    "number": 789,
                    "title": "Update docs",
                    "state": "CLOSED",
                },
                "fieldValues": {
                    "nodes": [
                        {"field": {"name": "Status"}, "name": "Done"},
                        {"field": {"name": "Iteration"}, "title": "Iteration 1"},
                        {"field": {"name": "Priority"}, "name": "P2"},
                    ]
                },
            },
        ]

    def test_filters_open_only(self, sample_items):
        """Should filter to only open items."""
        result = filter_items(sample_items, open_only=True)
        assert len(result) == 2
        assert all(item["content"]["state"] == "OPEN" for item in result)

    def test_filters_by_status(self, sample_items):
        """Should filter by status value."""
        result = filter_items(sample_items, status="In Progress")
        assert len(result) == 1
        assert result[0]["content"]["number"] == 123

    def test_filters_missing_field(self, sample_items):
        """Should filter to items missing a field."""
        result = filter_items(sample_items, missing_field="Priority")
        assert len(result) == 1
        assert result[0]["content"]["number"] == 456

    def test_filters_by_iteration(self, sample_items):
        """Should filter by iteration title."""
        result = filter_items(sample_items, iteration_title="Iteration 2")
        assert len(result) == 2

    def test_combines_filters(self, sample_items):
        """Should combine multiple filters."""
        result = filter_items(
            sample_items,
            open_only=True,
            iteration_title="Iteration 2",
        )
        assert len(result) == 2

    def test_handles_items_without_content(self, sample_items):
        """Should skip items without content (draft items)."""
        sample_items.append({"id": "ITEM_4", "content": None, "fieldValues": {"nodes": []}})
        result = filter_items(sample_items, open_only=True)
        # Should not crash, just skip the item
        assert len(result) == 2


class TestFormatOutput:
    """Tests for format_output function."""

    @pytest.fixture
    def sample_items(self):
        """Sample items for formatting."""
        return [
            {
                "id": "ITEM_1",
                "content": {
                    "number": 123,
                    "title": "Fix login bug",
                    "state": "OPEN",
                },
                "fieldValues": {
                    "nodes": [
                        {"field": {"name": "Status"}, "name": "In Progress"},
                        {"field": {"name": "Priority"}, "name": "P1"},
                    ]
                },
            },
        ]

    def test_includes_issue_number(self, sample_items, capsys):
        """Should include issue numbers in output."""
        format_output(sample_items, "backend", fields_to_show=["Status", "Priority"])
        output = capsys.readouterr().out
        assert "123" in output

    def test_includes_title(self, sample_items, capsys):
        """Should include issue title in output."""
        format_output(sample_items, "backend", fields_to_show=["Status"])
        output = capsys.readouterr().out
        assert "Fix login bug" in output

    def test_shows_field_values(self, sample_items, capsys):
        """Should show specified field values."""
        format_output(sample_items, "backend", fields_to_show=["Status", "Priority"])
        output = capsys.readouterr().out
        assert "In Progress" in output
        assert "P1" in output

    def test_shows_empty_for_missing_fields(self, sample_items, capsys):
        """Should show empty marker for missing fields."""
        format_output(sample_items, "backend", fields_to_show=["Status", "Product"])
        output = capsys.readouterr().out
        assert "(empty)" in output

    def test_shows_count(self, sample_items, capsys):
        """Should show item count."""
        format_output(sample_items, "backend", fields_to_show=["Status"])
        output = capsys.readouterr().out
        assert "1" in output  # Found 1 issue


class TestMain:
    """Tests for main function integration."""

    @pytest.fixture
    def mock_config(self, tmp_path):
        """Create mock config for testing."""
        env_content = """
PROJECT_1_OWNER=myorg
PROJECT_1_ID=123
PROJECT_1_NAME=backend
DEFAULT_STATUS_FIELD=Status
DEFAULT_ITERATION_FIELD=Iteration
DONE_STATUS=Done
"""
        env_file = tmp_path / ".env"
        env_file.write_text(env_content)
        return env_file

    def test_validates_project_exists(self, mock_config, capsys):
        """Should error if project not found."""
        with patch("scripts.list_items.find_env_file", return_value=mock_config):
            with patch("scripts.list_items.check_gh_auth", return_value=True):
                result = main(["--project", "nonexistent"])
        assert result != 0
        output = capsys.readouterr().err
        assert "not found" in output.lower() or "Project" in output
