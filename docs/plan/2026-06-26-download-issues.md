# Download Project Items Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `download_issues.py` script that exports all items on a GitHub project board (issues, PRs, draft issues) with their project field values to a JSON or CSV file.

**Architecture:** A fourth script in `scripts/` following the established pattern (parse → load config → fetch → format → write). It reuses `common.py` for config/auth/GraphQL. The shared `get_project_items()` GraphQL query is extended additively (type, assignees, draft issues) so all scripts benefit. Pure serialization helpers (`extract_fields`, `item_to_record`, `export_to_json`, `export_to_csv`) are unit-tested in isolation; `main()` wires them together and writes the file.

**Tech Stack:** Python 3.10+, `uv`, pytest, ruff, `gh` CLI + GraphQL, `rich` (console output), stdlib `csv`/`json`/`datetime`.

## Global Constraints

- Python 3.10+ syntax; `from __future__ import annotations` at top of every module (matches existing scripts).
- All imports of shared logic come from `scripts.common`.
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.
- Run via the Makefile: `make test`, `make lint`, `make format`. All three must pass before reporting success.
- ruff: line length 100, checks E/F/I/W.
- No filtering options in v1; download is unconditional (scope decision from the spec).
- Always write to a file; no stdout for the data. Auto-name `<project>-items-YYYY-MM-DD.<ext>` in the current working directory when `--output-file` is omitted.
- Spec: `docs/spec/2026-06-26-download-issues-design.md`.

---

### Task 1: Extend shared `get_project_items` GraphQL query

The current query in `scripts/common.py` only fetches `number/title/state/url` for Issue and PullRequest. The export needs the item **type**, **assignees**, and **draft issues**. These additions are backward-compatible: other scripts read fields via `content.get(...)` / `get_item_field_value()` and ignore extra data.

**Files:**
- Modify: `scripts/common.py` (the `query` string inside `get_project_items`, lines ~281-328)
- Test: `tests/test_common.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_project_items(project_id, max_items=500)` now returns items whose `content` includes `__typename`, `assignees { nodes { login } }`, and a `DraftIssue` variant (`__typename`, `title`, `assignees`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_common.py` (add `import json` and `from unittest.mock import MagicMock` at the top if not already present):

```python
def test_get_project_items_query_includes_type_assignees_drafts(mock_subprocess_run):
    """The items query must request __typename, assignees, and draft issues."""
    from scripts.common import get_project_items

    resp = MagicMock()
    resp.returncode = 0
    resp.stdout = json.dumps(
        {"data": {"node": {"items": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [],
        }}}}
    )
    resp.stderr = ""
    mock_subprocess_run.return_value = resp

    get_project_items("PVT_test")

    cmd = mock_subprocess_run.call_args[0][0]
    query_arg = next(a for a in cmd if a.startswith("query="))
    assert "__typename" in query_arg
    assert "assignees" in query_arg
    assert "DraftIssue" in query_arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_common.py::test_get_project_items_query_includes_type_assignees_drafts -v`
Expected: FAIL (assert `"__typename" in query_arg` is False — the substring is absent).

- [ ] **Step 3: Modify the query**

In `scripts/common.py`, inside `get_project_items`, replace the `content { ... }` block of the query so it reads:

```graphql
                        content {
                            __typename
                            ... on Issue {
                                number
                                title
                                state
                                url
                                assignees(first: 10) { nodes { login } }
                            }
                            ... on PullRequest {
                                number
                                title
                                state
                                url
                                assignees(first: 10) { nodes { login } }
                            }
                            ... on DraftIssue {
                                title
                                assignees(first: 10) { nodes { login } }
                            }
                        }
```

Leave the rest of the query (`fieldValues`, pagination) unchanged.

- [ ] **Step 4: Run the test to verify it passes, and the full suite**

Run: `uv run pytest tests/test_common.py -v`
Expected: PASS, including the new test and all existing `common` tests (the change is additive, so nothing else should break).

- [ ] **Step 5: Commit**

```bash
git add scripts/common.py tests/test_common.py
git commit -m "feat: fetch item type, assignees, and draft issues in project items query"
```

---

### Task 2: `extract_fields` helper

A pure function that flattens an item's `fieldValues` nodes into a `{field_name: value}` dict, handling text, single-select, and iteration value shapes.

**Files:**
- Create: `scripts/download_issues.py`
- Test: `tests/test_download_issues.py`

**Interfaces:**
- Consumes: a raw project item dict (the shape returned by `get_project_items`).
- Produces: `extract_fields(item: dict) -> dict[str, str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_download_issues.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_download_issues.py -v`
Expected: FAIL with `ImportError`/`ModuleNotFoundError` (no `scripts/download_issues.py` yet).

- [ ] **Step 3: Create the module with the helper**

Create `scripts/download_issues.py`:

```python
#!/usr/bin/env python3
"""Download all GitHub Project items to JSON or CSV."""

from __future__ import annotations

from typing import Any


def extract_fields(item: dict[str, Any]) -> dict[str, str]:
    """Flatten an item's fieldValues into a {field_name: value} dict."""
    result: dict[str, str] = {}
    for fv in item.get("fieldValues", {}).get("nodes", []):
        field = fv.get("field") or {}
        name = field.get("name")
        if not name:
            continue
        if "text" in fv:
            result[name] = fv["text"]
        elif "name" in fv:
            result[name] = fv["name"]
        elif "title" in fv:
            result[name] = fv["title"]
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_download_issues.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/download_issues.py tests/test_download_issues.py
git commit -m "feat: add extract_fields helper for download_issues"
```

---

### Task 3: `item_to_record` normalizer

Normalize a raw project item into a flat record: `number`, `title`, `type`, `state`, `url`, `assignees` (list), and `fields` (from `extract_fields`). Must handle Issue, PullRequest, and DraftIssue (which has no number/state/url).

**Files:**
- Modify: `scripts/download_issues.py`
- Test: `tests/test_download_issues.py`

**Interfaces:**
- Consumes: `extract_fields` (Task 2); a raw project item dict.
- Produces: `item_to_record(item: dict) -> dict` with keys
  `number (int|None), title (str|None), type (str|None), state (str|None), url (str|None), assignees (list[str]), fields (dict[str,str])`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_download_issues.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_download_issues.py::TestItemToRecord -v`
Expected: FAIL with `ImportError: cannot import name 'item_to_record'`.

- [ ] **Step 3: Implement `item_to_record`**

Add to `scripts/download_issues.py` (below `extract_fields`):

```python
def item_to_record(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a raw project item into a flat export record."""
    content = item.get("content") or {}
    assignees = [
        n.get("login")
        for n in content.get("assignees", {}).get("nodes", [])
        if n.get("login")
    ]
    return {
        "number": content.get("number"),
        "title": content.get("title"),
        "type": content.get("__typename"),
        "state": content.get("state"),
        "url": content.get("url"),
        "assignees": assignees,
        "fields": extract_fields(item),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_download_issues.py -v`
Expected: PASS (all tests, including Task 2's).

- [ ] **Step 5: Commit**

```bash
git add scripts/download_issues.py tests/test_download_issues.py
git commit -m "feat: add item_to_record normalizer"
```

---

### Task 4: `export_to_json` serializer

Serialize records into the JSON wrapper (`project`, `exported_at`, `count`, `items`). The timestamp is a parameter so the function is deterministic.

**Files:**
- Modify: `scripts/download_issues.py`
- Test: `tests/test_download_issues.py`

**Interfaces:**
- Consumes: a list of records (Task 3 output).
- Produces: `export_to_json(records: list[dict], project: str, timestamp: str) -> str` (JSON string, 2-space indent).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_download_issues.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_download_issues.py::TestExportToJson -v`
Expected: FAIL with `ImportError: cannot import name 'export_to_json'`.

- [ ] **Step 3: Implement `export_to_json`**

Add `import json` to the top of `scripts/download_issues.py` (with the other imports), then add:

```python
def export_to_json(records: list[dict[str, Any]], project: str, timestamp: str) -> str:
    """Serialize records into the JSON export wrapper."""
    return json.dumps(
        {
            "project": project,
            "exported_at": timestamp,
            "count": len(records),
            "items": records,
        },
        indent=2,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_download_issues.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/download_issues.py tests/test_download_issues.py
git commit -m "feat: add export_to_json serializer"
```

---

### Task 5: `export_to_csv` serializer

Serialize records into CSV: fixed core columns followed by one column per project field name (caller-supplied, stable order). Empty cell when a value is absent; `assignees` joined with `;`; `None` becomes `""`.

**Files:**
- Modify: `scripts/download_issues.py`
- Test: `tests/test_download_issues.py`

**Interfaces:**
- Consumes: a list of records (Task 3); `field_names: list[str]` (column order from project field defs).
- Produces: `export_to_csv(records: list[dict], field_names: list[str]) -> str`. Core column order is fixed: `number, title, type, state, url, assignees`, then `field_names`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_download_issues.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_download_issues.py::TestExportToCsv -v`
Expected: FAIL with `ImportError: cannot import name 'export_to_csv'`.

- [ ] **Step 3: Implement `export_to_csv`**

Add `import csv` and `import io` to the top of `scripts/download_issues.py`, then add:

```python
CORE_COLUMNS = ["number", "title", "type", "state", "url", "assignees"]


def export_to_csv(records: list[dict[str, Any]], field_names: list[str]) -> str:
    """Serialize records into CSV with core columns plus one column per field."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CORE_COLUMNS + field_names)
    for r in records:
        row = [
            "" if r["number"] is None else r["number"],
            r["title"] or "",
            r["type"] or "",
            r["state"] or "",
            r["url"] or "",
            ";".join(r["assignees"]),
        ]
        for name in field_names:
            row.append(r["fields"].get(name, ""))
        writer.writerow(row)
    return output.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_download_issues.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/download_issues.py tests/test_download_issues.py
git commit -m "feat: add export_to_csv serializer"
```

---

### Task 6: `parse_args` + `main` (fetch, serialize, write file)

Wire everything together: parse args, load config, auth, resolve project, fetch fields + items, normalize, serialize per `--format`, and write the file (auto-named in cwd when `--output-file` is omitted). Field column names for CSV come from project field defs, in definition order, excluding `Title`/`Assignees` (already covered by core columns).

**Files:**
- Modify: `scripts/download_issues.py`
- Test: `tests/test_download_issues.py`

**Interfaces:**
- Consumes: `export_to_json`, `export_to_csv`, `item_to_record` (Tasks 3-5); `scripts.common` functions (`find_env_file`, `load_config`, `check_gh_auth`, `get_project_node_id`, `get_project_fields`, `get_project_items`, `get_today`, `GHPMError`).
- Produces: `parse_args(args=None) -> argparse.Namespace` (`.project`, `.format`, `.output_file`); `main(args=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_download_issues.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from scripts.download_issues import main, parse_args


def _gh(data, returncode=0):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = json.dumps(data) if data else ""
    r.stderr = ""
    return r


FIELDS_RESPONSE = {
    "data": {"node": {"fields": {"nodes": [
        {"id": "F0", "name": "Title", "dataType": "TITLE"},
        {"id": "F1", "name": "Status", "options": [{"id": "O1", "name": "Todo"}]},
        {"id": "F2", "name": "Priority", "options": [{"id": "P1", "name": "P1"}]},
    ]}}}
}

ITEMS_RESPONSE = {
    "data": {"node": {"items": {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [
            {
                "id": "IT1",
                "content": {
                    "__typename": "Issue", "number": 123, "title": "Fix bug",
                    "state": "OPEN", "url": "https://x/123",
                    "assignees": {"nodes": [{"login": "alice"}]},
                },
                "fieldValues": {"nodes": [
                    {"field": {"name": "Status"}, "name": "In Progress"},
                    {"field": {"name": "Priority"}, "name": "P1"},
                ]},
            },
            {
                "id": "IT2",
                "content": {"__typename": "DraftIssue", "title": "Idea",
                            "assignees": {"nodes": []}},
                "fieldValues": {"nodes": []},
            },
        ],
    }}}
}

NODE_ID_RESPONSE = {"data": {"user": {"projectV2": {"id": "PVT_x"}}}}


class TestParseArgs:
    def test_requires_project(self):
        with pytest.raises(SystemExit):
            parse_args([])

    def test_defaults_to_json(self):
        args = parse_args(["--project", "backend"])
        assert args.project == "backend"
        assert args.format == "json"
        assert args.output_file is None

    def test_parses_csv_and_output_file(self):
        args = parse_args(["--project", "backend", "--format", "csv", "--output-file", "out.csv"])
        assert args.format == "csv"
        assert args.output_file == "out.csv"


class TestMain:
    @pytest.fixture
    def env_file(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text(
            "PROJECT_1_OWNER=myorg\nPROJECT_1_ID=123\nPROJECT_1_NAME=backend\n"
            "DEFAULT_STATUS_FIELD=Status\nDEFAULT_ITERATION_FIELD=Iteration\nDONE_STATUS=Done\n"
        )
        return f

    def _patches(self, env_file, mock_subprocess_run):
        mock_subprocess_run.side_effect = [
            _gh({}),               # check_gh_auth
            _gh(NODE_ID_RESPONSE), # get_project_node_id (user)
            _gh(FIELDS_RESPONSE),  # get_project_fields
            _gh(ITEMS_RESPONSE),   # get_project_items
        ]

    def test_writes_json_to_given_output_file(self, env_file, tmp_path, mock_subprocess_run):
        self._patches(env_file, mock_subprocess_run)
        out = tmp_path / "dump.json"
        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            rc = main(["--project", "backend", "--output-file", str(out)])
        assert rc == 0
        parsed = json.loads(out.read_text())
        assert parsed["project"] == "backend"
        assert parsed["count"] == 2
        assert parsed["items"][0]["number"] == 123
        assert parsed["items"][0]["assignees"] == ["alice"]
        assert parsed["items"][1]["type"] == "DraftIssue"

    def test_writes_csv_with_dynamic_columns(self, env_file, tmp_path, mock_subprocess_run):
        self._patches(env_file, mock_subprocess_run)
        out = tmp_path / "dump.csv"
        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            rc = main(["--project", "backend", "--format", "csv", "--output-file", str(out)])
        assert rc == 0
        rows = list(csv.reader(io.StringIO(out.read_text())))
        assert rows[0] == [
            "number", "title", "type", "state", "url", "assignees", "Status", "Priority"
        ]
        assert rows[1] == [
            "123", "Fix bug", "Issue", "OPEN", "https://x/123", "alice", "In Progress", "P1"
        ]
        assert rows[2] == ["", "Idea", "DraftIssue", "", "", "", "", ""]

    def test_auto_names_file_in_cwd(self, env_file, tmp_path, monkeypatch, mock_subprocess_run):
        self._patches(env_file, mock_subprocess_run)
        monkeypatch.chdir(tmp_path)
        import datetime as _dt
        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            with patch("scripts.download_issues.get_today", return_value=_dt.date(2026, 6, 26)):
                rc = main(["--project", "backend"])
        assert rc == 0
        assert (tmp_path / "backend-items-2026-06-26.json").exists()

    def test_errors_on_unknown_project(self, env_file, mock_subprocess_run):
        mock_subprocess_run.side_effect = [_gh({})]  # auth only
        with patch("scripts.download_issues.find_env_file", return_value=env_file):
            rc = main(["--project", "nope"])
        assert rc != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_download_issues.py::TestMain -v`
Expected: FAIL with `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Implement `parse_args` and `main`**

Update the imports at the top of `scripts/download_issues.py` to include argparse/sys/rich/common, then add the functions. The top of the file should become:

```python
#!/usr/bin/env python3
"""Download all GitHub Project items to JSON or CSV."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console

from scripts.common import (
    GHPMError,
    check_gh_auth,
    find_env_file,
    get_project_fields,
    get_project_items,
    get_project_node_id,
    get_today,
    load_config,
)

console = Console()
err_console = Console(stderr=True)
```

(Keep the existing `extract_fields`, `item_to_record`, `export_to_json`, `export_to_csv`, and `CORE_COLUMNS` definitions below the imports. Remove the now-duplicate `import json`/`import csv`/`import io` lines that earlier tasks added inside the file — they are consolidated into this import block.)

Then append:

```python
def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Download all GitHub Project items")
    parser.add_argument("--project", required=True, help="Project short name (from .env)")
    parser.add_argument(
        "--format", choices=["json", "csv"], default="json", help="Output format"
    )
    parser.add_argument(
        "--output-file", help="Output path (default: <project>-items-YYYY-MM-DD.<ext> in cwd)"
    )
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    """Main entry point."""
    parsed = parse_args(args)

    try:
        env_file = find_env_file()
        config = load_config(env_file)

        if not check_gh_auth():
            err_console.print(
                "[red]GitHub CLI not authenticated.[/red]\n"
                "Run: gh auth login && gh auth refresh -s project"
            )
            return 1

        project = config.get_project(parsed.project)
        if not project:
            err_console.print(f"[red]Project '{parsed.project}' not found.[/red]")
            err_console.print("Available projects:")
            for p in config.projects:
                err_console.print(f"  - {p.name}")
            return 1

        project_id = get_project_node_id(project.owner, project.number)
        fields = get_project_fields(project_id)
        items = get_project_items(project_id, max_items=10000)
        records = [item_to_record(item) for item in items]

        if parsed.format == "csv":
            field_names = [
                f["name"]
                for f in fields
                if f.get("name") and f["name"].lower() not in ("title", "assignees")
            ]
            content = export_to_csv(records, field_names)
            ext = "csv"
        else:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            content = export_to_json(records, project.name, timestamp)
            ext = "json"

        if parsed.output_file:
            out_path = Path(parsed.output_file)
        else:
            out_path = Path.cwd() / f"{project.name}-items-{get_today().isoformat()}.{ext}"

        out_path.write_text(content)
        console.print(
            f"Exported {len(records)} item{'s' if len(records) != 1 else ''} to {out_path}"
        )
        return 0

    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full test file to verify it passes**

Run: `uv run pytest tests/test_download_issues.py -v`
Expected: PASS (all classes).

- [ ] **Step 5: Lint, format, and run the whole suite**

Run: `make format && make lint && make test`
Expected: ruff reports no errors; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/download_issues.py tests/test_download_issues.py
git commit -m "feat: add download_issues main with JSON/CSV file export"
```

---

### Task 7: Document the command in SKILL.md

Add a "Download Issues" command entry so the skill knows how to invoke the script.

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: the `download_issues.py` CLI from Task 6.
- Produces: documentation only.

- [ ] **Step 1: Add the command section**

In `SKILL.md`, after the "Update Issues" section (before "Show Iterations"), insert:

```markdown
### Download Issues
**Intent**: Export all project items (issues, PRs, drafts) to a file
**Script**: `download_issues.py`
**Example invocations**:
- "ghpm: download backend issues to CSV"
- "ghpm: export frontend project items as json"

**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python scripts/download_issues.py --project <name> [--format json|csv] [--output-file <path>]
```
Writes `<project>-items-YYYY-MM-DD.<ext>` in the current directory when `--output-file` is omitted.
```

- [ ] **Step 2: Verify the suite still passes (docs change, sanity check)**

Run: `make test`
Expected: PASS (unchanged).

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: document download_issues command in SKILL.md"
```

---

## Self-Review

**Spec coverage:**
- All project items incl. issues/PRs/drafts → Task 1 (query) + Task 3 (`item_to_record` handles all three).
- Field values → Task 2 (`extract_fields`), surfaced in JSON (`fields`) and CSV (dynamic columns).
- JSON default + CSV via `--format` → Task 6 (`parse_args`).
- Always write to file; auto-name in cwd → Task 6 (`main`, `test_auto_names_file_in_cwd`).
- CSV: core columns + dynamic field columns, empty cells, assignees `;`-joined → Task 5.
- Deterministic timestamp param → Task 4.
- No filters / no stdout / no markdown → enforced by absence; not implemented (correct per spec).
- SKILL.md update → Task 7.
- `.claude/settings.local.json`: no new permission needed (same `gh`/`uv` invocations) — no task.

**Placeholder scan:** none — every code/test step contains complete content.

**Type consistency:** record keys (`number/title/type/state/url/assignees/fields`) are identical across Tasks 3-6; `export_to_csv(records, field_names)` and `export_to_json(records, project, timestamp)` signatures match their call sites in `main`; `get_today` and `find_env_file` are imported into `scripts.download_issues` so the test patches (`scripts.download_issues.get_today`, `scripts.download_issues.find_env_file`) resolve correctly.

**Note for implementer:** Tasks 2, 4, and 5 each add a stray `import json`/`import csv`/`import io` inside the file as the minimal step; Task 6 Step 3 consolidates all imports into the top block. Confirm no duplicate imports remain (ruff `F811`/`I001` will flag them) after Task 6.
