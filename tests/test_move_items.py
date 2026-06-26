"""Tests for scripts/move_items.py."""

from unittest.mock import patch

import pytest

from scripts.move_items import (
    filter_movable_items,
    format_dry_run_output,
    main,
    parse_args,
)


class TestParseArgs:
    """Tests for argument parsing."""

    def test_requires_from_iteration(self):
        """Should require --from-iteration argument."""
        with pytest.raises(SystemExit):
            parse_args(["--to-iteration", "current"])

    def test_requires_to_iteration(self):
        """Should require --to-iteration argument."""
        with pytest.raises(SystemExit):
            parse_args(["--from-iteration", "previous"])

    def test_parses_both_iterations(self):
        """Should parse both iteration arguments."""
        args = parse_args(["--from-iteration", "previous", "--to-iteration", "current"])
        assert args.from_iteration == "previous"
        assert args.to_iteration == "current"

    def test_parses_project(self):
        """Should parse --project argument."""
        args = parse_args(
            [
                "--from-iteration",
                "previous",
                "--to-iteration",
                "current",
                "--project",
                "backend",
            ]
        )
        assert args.project == "backend"

    def test_parses_dry_run(self):
        """Should parse --dry-run flag."""
        args = parse_args(
            [
                "--from-iteration",
                "previous",
                "--to-iteration",
                "current",
                "--dry-run",
            ]
        )
        assert args.dry_run is True

    def test_dry_run_default_false(self):
        """Should default --dry-run to False."""
        args = parse_args(["--from-iteration", "previous", "--to-iteration", "current"])
        assert args.dry_run is False


class TestFilterMovableItems:
    """Tests for filter_movable_items function."""

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
                        {
                            "field": {"name": "Iteration"},
                            "iterationId": "ITER_2",
                            "title": "Iteration 2",
                        },
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
                        {
                            "field": {"name": "Iteration"},
                            "iterationId": "ITER_2",
                            "title": "Iteration 2",
                        },
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
                        {
                            "field": {"name": "Iteration"},
                            "iterationId": "ITER_2",
                            "title": "Iteration 2",
                        },
                    ]
                },
            },
            {
                "id": "ITEM_4",
                "content": {
                    "number": 101,
                    "title": "Other work",
                    "state": "OPEN",
                },
                "fieldValues": {
                    "nodes": [
                        {"field": {"name": "Status"}, "name": "In Progress"},
                        {
                            "field": {"name": "Iteration"},
                            "iterationId": "ITER_1",
                            "title": "Iteration 1",
                        },
                    ]
                },
            },
        ]

    def test_filters_by_iteration(self, sample_items):
        """Should filter items in the source iteration."""
        result = filter_movable_items(
            sample_items,
            from_iteration_title="Iteration 2",
            done_status="Done",
        )
        # Items 1, 2, 3 are in Iteration 2
        assert len(result) == 2  # But 3 is Done, so only 2

    def test_excludes_closed_issues(self, sample_items):
        """Should exclude closed issues."""
        result = filter_movable_items(
            sample_items,
            from_iteration_title="Iteration 2",
            done_status="Done",
        )
        assert all(item["content"]["state"] == "OPEN" for item in result)

    def test_excludes_done_status(self, sample_items):
        """Should exclude items with Done status."""
        result = filter_movable_items(
            sample_items,
            from_iteration_title="Iteration 2",
            done_status="Done",
        )
        for item in result:
            # Check status field value
            field_values = item.get("fieldValues", {}).get("nodes", [])
            for fv in field_values:
                if fv.get("field", {}).get("name") == "Status":
                    assert fv.get("name") != "Done"

    def test_handles_items_without_iteration(self, sample_items):
        """Should skip items without iteration field."""
        sample_items.append(
            {
                "id": "ITEM_5",
                "content": {"number": 999, "title": "No iteration", "state": "OPEN"},
                "fieldValues": {"nodes": [{"field": {"name": "Status"}, "name": "Todo"}]},
            }
        )
        result = filter_movable_items(
            sample_items,
            from_iteration_title="Iteration 2",
            done_status="Done",
        )
        assert len(result) == 2


class TestFormatDryRunOutput:
    """Tests for format_dry_run_output function."""

    @pytest.fixture
    def sample_items(self):
        """Sample items for formatting."""
        return [
            {
                "id": "ITEM_1",
                "content": {"number": 123, "title": "Fix login bug", "state": "OPEN"},
                "fieldValues": {"nodes": []},
            },
            {
                "id": "ITEM_2",
                "content": {"number": 456, "title": "Add dark mode", "state": "OPEN"},
                "fieldValues": {"nodes": []},
            },
        ]

    def test_shows_dry_run_header(self, sample_items, capsys):
        """Should show DRY RUN header."""
        format_dry_run_output(
            sample_items,
            project_name="backend",
            from_title="Iteration 2",
            to_title="Iteration 3",
        )
        output = capsys.readouterr().out
        assert "[DRY RUN]" in output

    def test_shows_item_count(self, sample_items, capsys):
        """Should show number of items to move."""
        format_dry_run_output(
            sample_items,
            project_name="backend",
            from_title="Iteration 2",
            to_title="Iteration 3",
        )
        output = capsys.readouterr().out
        assert "2" in output

    def test_shows_issue_numbers(self, sample_items, capsys):
        """Should show issue numbers."""
        format_dry_run_output(
            sample_items,
            project_name="backend",
            from_title="Iteration 2",
            to_title="Iteration 3",
        )
        output = capsys.readouterr().out
        assert "#123" in output
        assert "#456" in output


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

    def test_validates_project_when_specified(self, mock_config, capsys):
        """Should error if specified project not found."""
        with patch("scripts.move_items.find_env_file", return_value=mock_config):
            with patch("scripts.move_items.check_gh_auth", return_value=True):
                result = main(
                    [
                        "--from-iteration",
                        "previous",
                        "--to-iteration",
                        "current",
                        "--project",
                        "nonexistent",
                    ]
                )
        assert result != 0
        output = capsys.readouterr().err
        assert "not found" in output.lower() or "Project" in output
