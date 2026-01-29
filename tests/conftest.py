"""Shared pytest fixtures for GHPM tests."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_env_file(tmp_path: Path) -> Path:
    """Create a temporary .env file for testing."""
    env_content = """
PROJECT_1_OWNER=myorg
PROJECT_1_ID=123
PROJECT_1_NAME=backend

PROJECT_2_OWNER=myorg
PROJECT_2_ID=456
PROJECT_2_NAME=frontend

DEFAULT_STATUS_FIELD=Status
DEFAULT_ITERATION_FIELD=Iteration
DONE_STATUS=Done
"""
    env_file = tmp_path / ".env"
    env_file.write_text(env_content)
    return env_file


@pytest.fixture
def sample_fields_response() -> dict:
    """Sample GraphQL response for project fields."""
    return {
        "data": {
            "node": {
                "fields": {
                    "nodes": [
                        {"id": "FIELD_1", "name": "Title", "dataType": "TEXT"},
                        {
                            "id": "FIELD_2",
                            "name": "Status",
                            "options": [
                                {"id": "OPT_1", "name": "Todo"},
                                {"id": "OPT_2", "name": "In Progress"},
                                {"id": "OPT_3", "name": "Done"},
                            ],
                        },
                        {
                            "id": "FIELD_3",
                            "name": "Iteration",
                            "configuration": {
                                "iterations": [
                                    {
                                        "id": "ITER_1",
                                        "title": "Iteration 1",
                                        "startDate": "2025-01-06",
                                        "duration": 7,
                                    },
                                    {
                                        "id": "ITER_2",
                                        "title": "Iteration 2",
                                        "startDate": "2025-01-13",
                                        "duration": 7,
                                    },
                                    {
                                        "id": "ITER_3",
                                        "title": "Iteration 3",
                                        "startDate": "2025-01-20",
                                        "duration": 7,
                                    },
                                    {
                                        "id": "ITER_4",
                                        "title": "Iteration 4",
                                        "startDate": "2025-01-27",
                                        "duration": 7,
                                    },
                                ]
                            },
                        },
                        {
                            "id": "FIELD_4",
                            "name": "Priority",
                            "options": [
                                {"id": "PRI_1", "name": "P0"},
                                {"id": "PRI_2", "name": "P1"},
                                {"id": "PRI_3", "name": "P2"},
                            ],
                        },
                    ]
                }
            }
        }
    }


@pytest.fixture
def sample_items_response() -> dict:
    """Sample GraphQL response for project items."""
    return {
        "data": {
            "node": {
                "items": {
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                    "nodes": [
                        {
                            "id": "ITEM_1",
                            "content": {
                                "number": 123,
                                "title": "Fix login bug",
                                "state": "OPEN",
                                "url": "https://github.com/myorg/repo/issues/123",
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
                                "url": "https://github.com/myorg/repo/issues/456",
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
                                "title": "Update API docs",
                                "state": "CLOSED",
                                "url": "https://github.com/myorg/repo/issues/789",
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
                    ],
                }
            }
        }
    }


@pytest.fixture
def mock_subprocess_run(monkeypatch):
    """Mock subprocess.run for gh CLI calls."""
    mock = MagicMock()
    monkeypatch.setattr("subprocess.run", mock)
    return mock


def make_gh_response(data: dict, returncode: int = 0) -> MagicMock:
    """Helper to create mock subprocess.CompletedProcess."""
    result = MagicMock()
    result.returncode = returncode
    result.stdout = json.dumps(data) if data else ""
    result.stderr = ""
    return result
