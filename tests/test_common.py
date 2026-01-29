"""Tests for scripts/common.py."""

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.common import (
    GHPMError,
    check_gh_auth,
    get_project_fields,
    get_project_node_id,
    load_config,
    resolve_iteration_keyword,
    run_graphql,
)
from tests.conftest import make_gh_response


class TestLoadConfig:
    """Tests for load_config function."""

    def test_loads_single_project(self, tmp_path: Path):
        """Should parse a single project from .env."""
        env_content = """
PROJECT_1_OWNER=myorg
PROJECT_1_ID=123
PROJECT_1_NAME=backend
"""
        env_file = tmp_path / ".env"
        env_file.write_text(env_content)

        config = load_config(env_file)

        assert len(config.projects) == 1
        assert config.projects[0].owner == "myorg"
        assert config.projects[0].number == 123
        assert config.projects[0].name == "backend"

    def test_loads_multiple_projects(self, mock_env_file: Path):
        """Should parse multiple projects from .env."""
        config = load_config(mock_env_file)

        assert len(config.projects) == 2
        assert config.projects[0].name == "backend"
        assert config.projects[1].name == "frontend"

    def test_loads_defaults(self, mock_env_file: Path):
        """Should parse default field settings."""
        config = load_config(mock_env_file)

        assert config.status_field == "Status"
        assert config.iteration_field == "Iteration"
        assert config.done_status == "Done"

    def test_get_project_by_name(self, mock_env_file: Path):
        """Should find project by name."""
        config = load_config(mock_env_file)

        project = config.get_project("backend")
        assert project is not None
        assert project.number == 123

    def test_get_project_not_found(self, mock_env_file: Path):
        """Should return None for unknown project."""
        config = load_config(mock_env_file)

        project = config.get_project("nonexistent")
        assert project is None

    def test_raises_on_missing_env(self, tmp_path: Path):
        """Should raise error if .env file not found."""
        with pytest.raises(GHPMError, match="not found"):
            load_config(tmp_path / ".env")


class TestCheckGhAuth:
    """Tests for check_gh_auth function."""

    def test_returns_true_when_authenticated(self, mock_subprocess_run):
        """Should return True when gh auth status succeeds."""
        mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        result = check_gh_auth()

        assert result is True

    def test_returns_false_when_not_authenticated(self, mock_subprocess_run):
        """Should return False when gh auth status fails."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="not logged in"
        )

        result = check_gh_auth()

        assert result is False


class TestRunGraphQL:
    """Tests for run_graphql function."""

    def test_executes_query(self, mock_subprocess_run):
        """Should execute GraphQL query via gh CLI."""
        expected_data = {"data": {"viewer": {"login": "testuser"}}}
        mock_subprocess_run.return_value = make_gh_response(expected_data)

        result = run_graphql("query { viewer { login } }")

        assert result == expected_data
        mock_subprocess_run.assert_called_once()
        call_args = mock_subprocess_run.call_args
        assert "gh" in call_args[0][0]
        assert "api" in call_args[0][0]
        assert "graphql" in call_args[0][0]

    def test_passes_variables(self, mock_subprocess_run):
        """Should pass variables to GraphQL query."""
        mock_subprocess_run.return_value = make_gh_response({"data": {}})

        run_graphql("query($id: ID!) { node(id: $id) { id } }", {"id": "123"})

        call_args = mock_subprocess_run.call_args
        # Variables should be passed via -f flags
        args = call_args[0][0]
        assert "-f" in args

    def test_raises_on_graphql_error(self, mock_subprocess_run):
        """Should raise GHPMError on GraphQL errors."""
        error_response = {"errors": [{"message": "Something went wrong"}]}
        mock_subprocess_run.return_value = make_gh_response(error_response)

        with pytest.raises(GHPMError, match="GraphQL error"):
            run_graphql("query { invalid }")

    def test_raises_on_command_failure(self, mock_subprocess_run):
        """Should raise GHPMError when gh command fails."""
        mock_subprocess_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="command failed"
        )

        with pytest.raises(GHPMError):
            run_graphql("query { viewer { login } }")


class TestGetProjectNodeId:
    """Tests for get_project_node_id function."""

    def test_fetches_node_id(self, mock_subprocess_run):
        """Should fetch project node ID from owner and number."""
        response = {"data": {"user": {"projectV2": {"id": "PVT_123"}}}}
        mock_subprocess_run.return_value = make_gh_response(response)

        result = get_project_node_id("testuser", 1)

        assert result == "PVT_123"

    def test_fetches_org_project(self, mock_subprocess_run):
        """Should fetch organization project node ID."""
        # First call returns None for user, second succeeds for org
        user_response = {"data": {"user": None}}
        org_response = {"data": {"organization": {"projectV2": {"id": "PVT_456"}}}}

        mock_subprocess_run.side_effect = [
            make_gh_response(user_response),
            make_gh_response(org_response),
        ]

        result = get_project_node_id("myorg", 1)

        assert result == "PVT_456"

    def test_raises_when_not_found(self, mock_subprocess_run):
        """Should raise GHPMError when project not found."""
        mock_subprocess_run.return_value = make_gh_response(
            {"data": {"user": None, "organization": None}}
        )

        with pytest.raises(GHPMError, match="not found"):
            get_project_node_id("unknown", 999)


class TestGetProjectFields:
    """Tests for get_project_fields function."""

    def test_fetches_fields(self, mock_subprocess_run, sample_fields_response):
        """Should fetch and parse project fields."""
        mock_subprocess_run.return_value = make_gh_response(sample_fields_response)

        fields = get_project_fields("PVT_123")

        assert len(fields) == 4
        assert any(f["name"] == "Status" for f in fields)
        assert any(f["name"] == "Iteration" for f in fields)

    def test_returns_iterations(self, mock_subprocess_run, sample_fields_response):
        """Should include iteration configuration."""
        mock_subprocess_run.return_value = make_gh_response(sample_fields_response)

        fields = get_project_fields("PVT_123")

        iteration_field = next(f for f in fields if f["name"] == "Iteration")
        assert "configuration" in iteration_field
        assert len(iteration_field["configuration"]["iterations"]) == 4


class TestResolveIterationKeyword:
    """Tests for resolve_iteration_keyword function."""

    @pytest.fixture
    def iterations(self):
        """Sample iterations list."""
        return [
            {"id": "ITER_1", "title": "Iteration 1", "startDate": "2025-01-06", "duration": 7},
            {"id": "ITER_2", "title": "Iteration 2", "startDate": "2025-01-13", "duration": 7},
            {"id": "ITER_3", "title": "Iteration 3", "startDate": "2025-01-20", "duration": 7},
            {"id": "ITER_4", "title": "Iteration 4", "startDate": "2025-01-27", "duration": 7},
        ]

    def test_resolves_current(self, iterations, monkeypatch):
        """Should resolve 'current' to iteration containing today."""
        # Mock today to be 2025-01-21 (within Iteration 3)
        monkeypatch.setattr("scripts.common.get_today", lambda: date(2025, 1, 21))

        result = resolve_iteration_keyword(iterations, "current")

        assert result["id"] == "ITER_3"
        assert result["title"] == "Iteration 3"

    def test_resolves_previous(self, iterations, monkeypatch):
        """Should resolve 'previous' to iteration before current."""
        monkeypatch.setattr("scripts.common.get_today", lambda: date(2025, 1, 21))

        result = resolve_iteration_keyword(iterations, "previous")

        assert result["id"] == "ITER_2"
        assert result["title"] == "Iteration 2"

    def test_resolves_next(self, iterations, monkeypatch):
        """Should resolve 'next' to iteration after current."""
        monkeypatch.setattr("scripts.common.get_today", lambda: date(2025, 1, 21))

        result = resolve_iteration_keyword(iterations, "next")

        assert result["id"] == "ITER_4"
        assert result["title"] == "Iteration 4"

    def test_resolves_by_title(self, iterations):
        """Should resolve iteration by exact title match."""
        result = resolve_iteration_keyword(iterations, "Iteration 2")

        assert result["id"] == "ITER_2"

    def test_raises_when_not_found(self, iterations, monkeypatch):
        """Should raise GHPMError when iteration not found."""
        monkeypatch.setattr("scripts.common.get_today", lambda: date(2025, 1, 21))

        with pytest.raises(GHPMError, match="not found"):
            resolve_iteration_keyword(iterations, "nonexistent")

    def test_raises_when_no_previous(self, iterations, monkeypatch):
        """Should raise GHPMError when no previous iteration."""
        # Set date to first iteration
        monkeypatch.setattr("scripts.common.get_today", lambda: date(2025, 1, 7))

        with pytest.raises(GHPMError, match="No previous"):
            resolve_iteration_keyword(iterations, "previous")

    def test_raises_when_no_next(self, iterations, monkeypatch):
        """Should raise GHPMError when no next iteration."""
        # Set date to last iteration
        monkeypatch.setattr("scripts.common.get_today", lambda: date(2025, 1, 28))

        with pytest.raises(GHPMError, match="No next"):
            resolve_iteration_keyword(iterations, "next")
