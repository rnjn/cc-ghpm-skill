"""Tests for scripts/update_items.py."""

from unittest.mock import patch

import pytest

from scripts.update_items import (
    find_items_by_numbers,
    format_confirmation,
    main,
    parse_args,
    parse_item_numbers,
    validate_field_value,
)


class TestParseArgs:
    """Tests for argument parsing."""

    def test_requires_project(self):
        """Should require --project argument."""
        with pytest.raises(SystemExit):
            parse_args(["--items", "123", "--field", "Priority", "--value", "P1"])

    def test_requires_items(self):
        """Should require --items argument."""
        with pytest.raises(SystemExit):
            parse_args(["--project", "backend", "--field", "Priority", "--value", "P1"])

    def test_requires_field(self):
        """Should require --field argument."""
        with pytest.raises(SystemExit):
            parse_args(["--project", "backend", "--items", "123", "--value", "P1"])

    def test_requires_value(self):
        """Should require --value argument."""
        with pytest.raises(SystemExit):
            parse_args(["--project", "backend", "--items", "123", "--field", "Priority"])

    def test_parses_all_args(self):
        """Should parse all required arguments."""
        args = parse_args(
            [
                "--project",
                "backend",
                "--items",
                "123,456",
                "--field",
                "Priority",
                "--value",
                "P1",
            ]
        )
        assert args.project == "backend"
        assert args.items == "123,456"
        assert args.field == "Priority"
        assert args.value == "P1"

    def test_parses_yes_flag(self):
        """Should parse --yes flag."""
        args = parse_args(
            [
                "--project",
                "backend",
                "--items",
                "123",
                "--field",
                "Priority",
                "--value",
                "P1",
                "--yes",
            ]
        )
        assert args.yes is True


class TestParseItemNumbers:
    """Tests for parse_item_numbers function."""

    def test_parses_single_number(self):
        """Should parse a single number."""
        result = parse_item_numbers("123")
        assert result == [123]

    def test_parses_comma_separated(self):
        """Should parse comma-separated numbers."""
        result = parse_item_numbers("123,456,789")
        assert result == [123, 456, 789]

    def test_handles_spaces(self):
        """Should handle spaces around numbers."""
        result = parse_item_numbers("123, 456, 789")
        assert result == [123, 456, 789]

    def test_handles_hash_prefix(self):
        """Should handle # prefix."""
        result = parse_item_numbers("#123, #456")
        assert result == [123, 456]

    def test_returns_empty_for_invalid(self):
        """Should skip invalid numbers."""
        result = parse_item_numbers("abc, 123, def")
        assert result == [123]


class TestFindItemsByNumbers:
    """Tests for find_items_by_numbers function."""

    @pytest.fixture
    def sample_items(self):
        """Sample project items."""
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
            {
                "id": "ITEM_3",
                "content": {"number": 789, "title": "Update docs", "state": "CLOSED"},
                "fieldValues": {"nodes": []},
            },
        ]

    def test_finds_matching_items(self, sample_items):
        """Should find items by issue number."""
        result = find_items_by_numbers(sample_items, [123, 456])
        assert len(result) == 2
        assert result[0]["content"]["number"] == 123
        assert result[1]["content"]["number"] == 456

    def test_returns_empty_for_not_found(self, sample_items):
        """Should return empty list if no matches."""
        result = find_items_by_numbers(sample_items, [999])
        assert result == []

    def test_preserves_order(self, sample_items):
        """Should preserve order from input numbers."""
        result = find_items_by_numbers(sample_items, [456, 123])
        assert result[0]["content"]["number"] == 456
        assert result[1]["content"]["number"] == 123


class TestValidateFieldValue:
    """Tests for validate_field_value function."""

    @pytest.fixture
    def single_select_field(self):
        """Sample single-select field definition."""
        return {
            "id": "FIELD_1",
            "name": "Priority",
            "options": [
                {"id": "OPT_1", "name": "P0"},
                {"id": "OPT_2", "name": "P1"},
                {"id": "OPT_3", "name": "P2"},
            ],
        }

    def test_validates_valid_option(self, single_select_field):
        """Should return option ID for valid value."""
        result = validate_field_value(single_select_field, "P1")
        assert result == {"singleSelectOptionId": "OPT_2"}

    def test_validates_case_insensitive(self, single_select_field):
        """Should match case-insensitively."""
        result = validate_field_value(single_select_field, "p1")
        assert result == {"singleSelectOptionId": "OPT_2"}

    def test_returns_none_for_invalid(self, single_select_field):
        """Should return None for invalid option."""
        result = validate_field_value(single_select_field, "P9")
        assert result is None

    def test_handles_text_fields(self):
        """Should handle text fields."""
        text_field = {"id": "FIELD_2", "name": "Title", "dataType": "TEXT"}
        result = validate_field_value(text_field, "New title")
        assert result == {"text": "New title"}


class TestFormatConfirmation:
    """Tests for format_confirmation function."""

    @pytest.fixture
    def sample_items(self):
        """Sample items for confirmation."""
        return [
            {
                "id": "ITEM_1",
                "content": {"number": 123, "title": "Fix login bug", "state": "OPEN"},
            },
            {
                "id": "ITEM_2",
                "content": {"number": 456, "title": "Add dark mode", "state": "OPEN"},
            },
        ]

    def test_shows_item_count(self, sample_items, capsys):
        """Should show number of items."""
        format_confirmation(sample_items, "Priority", "P1")
        output = capsys.readouterr().out
        assert "2" in output

    def test_shows_issue_numbers(self, sample_items, capsys):
        """Should show issue numbers."""
        format_confirmation(sample_items, "Priority", "P1")
        output = capsys.readouterr().out
        assert "#123" in output
        assert "#456" in output

    def test_shows_field_and_value(self, sample_items, capsys):
        """Should show field name and value."""
        format_confirmation(sample_items, "Priority", "P1")
        output = capsys.readouterr().out
        assert "Priority" in output
        assert "P1" in output


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
        with patch("scripts.update_items.find_env_file", return_value=mock_config):
            with patch("scripts.update_items.check_gh_auth", return_value=True):
                result = main(
                    [
                        "--project",
                        "nonexistent",
                        "--items",
                        "123",
                        "--field",
                        "Priority",
                        "--value",
                        "P1",
                    ]
                )
        assert result != 0
        output = capsys.readouterr().err
        assert "not found" in output.lower() or "Project" in output
