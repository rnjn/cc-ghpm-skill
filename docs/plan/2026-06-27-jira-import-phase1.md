# Jira Import — Phase 1 (Core Import) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform a GHPM JSON export into Atlassian `acli` bulk-create JSON and (after a confirm gate) import GitHub Issues into Jira.

**Architecture:** Extend the exporter to carry each issue's `body`. Add a thin `acli_client.py` wrapper around the `acli` subprocess (the single place mocked in tests), and a `to_jira.py` importer with pure, unit-tested transform functions (`build_adf_description`, `issue_to_jira`, `transform`) plus a `main` that writes the acli file and conditionally invokes acli.

**Tech Stack:** Python 3.10+, `uv`, pytest, ruff, `gh` CLI + GraphQL (export), Atlassian `acli` (import), `rich` console, stdlib `json`/`subprocess`/`shutil`/`argparse`.

## Global Constraints

- Python 3.10+; `from __future__ import annotations` at the top of every module.
- Import shared logic from `scripts.common`; all `acli` calls go through `scripts.acli_client`.
- TDD: failing test first → watch it fail → minimal implementation → watch it pass → commit.
- Run via Makefile: `make format && make lint && make test` must all pass before reporting success.
- ruff: line length 100; imports consolidated at the top of each file (no E402).
- Phase 1 scope only: JSON export input only; import **Issues** only (skip PRs/drafts); assignee omitted; description is ADF built from `body` + a GitHub URL footer.
- acli authentication is assumed (`acli jira auth`); the tool does not authenticate.
- Spec: `docs/spec/2026-06-26-jira-import-design.md`.

---

### Task 1: Add `body` to the Issue fragment in the items query

**Files:**
- Modify: `scripts/common.py` (Issue fragment inside `get_project_items`, ~lines 294-300)
- Test: `tests/test_common.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `get_project_items` now requests `body` on Issue content; raw items may include `content.body`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_common.py`:

```python
def test_get_project_items_query_includes_body(mock_subprocess_run):
    """The items query must request the issue body."""
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
    assert "body" in query_arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_common.py::test_get_project_items_query_includes_body -v`
Expected: FAIL (`assert "body" in query_arg` is False).

- [ ] **Step 3: Add `body` to the Issue fragment**

In `scripts/common.py`, inside `get_project_items`, update only the Issue fragment:

```graphql
                            ... on Issue {
                                number
                                title
                                state
                                url
                                body
                                assignees(first: 10) { nodes { login } }
                            }
```

(Leave the PullRequest and DraftIssue fragments unchanged.)

- [ ] **Step 4: Run the test and the full common suite**

Run: `uv run pytest tests/test_common.py -v`
Expected: PASS (new test plus all existing common tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/common.py tests/test_common.py
git commit -m "feat: fetch issue body in project items query"
```

---

### Task 2: Include `body` in `item_to_record`

**Files:**
- Modify: `scripts/download_issues.py` (`item_to_record`)
- Test: `tests/test_download_issues.py` (`TestItemToRecord`)

**Interfaces:**
- Consumes: raw item dict (now possibly with `content.body`).
- Produces: `item_to_record` returns a record that additionally contains `body: str | None`.

- [ ] **Step 1: Update the existing equality test and add a body test**

In `tests/test_download_issues.py`, the test `test_normalizes_issue_with_assignees_and_fields` asserts full dict equality, so it must learn about `body`. Replace that test body with this version (adds `body` to both input and expected):

```python
    def test_normalizes_issue_with_assignees_and_fields(self):
        item = {
            "id": "I1",
            "content": {
                "__typename": "Issue",
                "number": 123,
                "title": "Fix login bug",
                "state": "OPEN",
                "url": "https://github.com/o/r/issues/123",
                "body": "Steps to reproduce",
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
            "body": "Steps to reproduce",
            "assignees": ["alice"],
            "fields": {"Status": "In Progress"},
        }
```

Then add a test for the missing-body case:

```python
    def test_body_is_none_when_absent(self):
        item = {"content": {"__typename": "Issue", "title": "x"}, "fieldValues": {"nodes": []}}
        assert item_to_record(item)["body"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_download_issues.py::TestItemToRecord -v`
Expected: FAIL (`test_normalizes_issue_with_assignees_and_fields` mismatch — record has no `body`; `test_body_is_none_when_absent` KeyError).

- [ ] **Step 3: Add `body` to `item_to_record`**

In `scripts/download_issues.py`, in `item_to_record`, add the `body` key to the returned dict (place it after `url`):

```python
        "url": content.get("url"),
        "body": content.get("body"),
        "assignees": assignees,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_download_issues.py -v`
Expected: PASS (all download_issues tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/download_issues.py tests/test_download_issues.py
git commit -m "feat: include issue body in export record"
```

---

### Task 3: `acli_client.py` wrapper

**Files:**
- Create: `scripts/acli_client.py`
- Test: `tests/test_acli_client.py`

**Interfaces:**
- Consumes: `GHPMError` from `scripts.common`.
- Produces:
  - `acli_available() -> bool`
  - `bulk_create(json_path: str, yes: bool = False) -> int` — runs
    `acli jira workitem create-bulk --from-json <json_path> [--yes]`, returns acli's
    exit code; raises `GHPMError` if acli is not on PATH.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_acli_client.py`:

```python
"""Tests for scripts/acli_client.py."""

from unittest.mock import MagicMock

import pytest

from scripts.acli_client import acli_available, bulk_create
from scripts.common import GHPMError


def test_acli_available_reflects_which(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    assert acli_available() is True
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    assert acli_available() is False


def test_bulk_create_builds_command_with_yes(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(returncode=0)

    rc = bulk_create("out.json", yes=True)

    assert rc == 0
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd == [
        "acli", "jira", "workitem", "create-bulk", "--from-json", "out.json", "--yes"
    ]


def test_bulk_create_without_yes_omits_flag(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(returncode=2)

    rc = bulk_create("out.json")

    assert rc == 2
    assert "--yes" not in mock_subprocess_run.call_args[0][0]


def test_bulk_create_raises_when_acli_missing(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    with pytest.raises(GHPMError, match="acli"):
        bulk_create("out.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_acli_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.acli_client'`.

- [ ] **Step 3: Create the wrapper**

Create `scripts/acli_client.py`:

```python
#!/usr/bin/env python3
"""Thin wrapper around the Atlassian `acli` CLI."""

from __future__ import annotations

import shutil
import subprocess

from scripts.common import GHPMError


def acli_available() -> bool:
    """Return True if `acli` is on PATH."""
    return shutil.which("acli") is not None


def bulk_create(json_path: str, yes: bool = False) -> int:
    """Bulk-create Jira work items from a JSON file via acli.

    Returns acli's exit code. Raises GHPMError if acli is not installed.
    """
    if not acli_available():
        raise GHPMError(
            "acli not found on PATH. Install Atlassian CLI and run 'acli jira auth'."
        )
    cmd = ["acli", "jira", "workitem", "create-bulk", "--from-json", json_path]
    if yes:
        cmd.append("--yes")
    result = subprocess.run(cmd)
    return result.returncode
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_acli_client.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/acli_client.py tests/test_acli_client.py
git commit -m "feat: add acli_client wrapper with bulk_create"
```

---

### Task 4: `build_adf_description`

**Files:**
- Create: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py`

**Interfaces:**
- Produces: `build_adf_description(body: str, url: str | None = None) -> dict` — returns an
  ADF `doc`: one `paragraph` per non-blank line of `body`, plus a trailing
  `Imported from GitHub: <url>` paragraph when `url` is given; a single empty
  paragraph if there is no content.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_to_jira.py`:

```python
"""Tests for scripts/to_jira.py."""

from scripts.to_jira import build_adf_description


def _texts(doc):
    return [
        c["content"][0]["text"]
        for c in doc["content"]
        if c["content"]
    ]


class TestBuildAdfDescription:
    def test_doc_shape(self):
        doc = build_adf_description("Hello", None)
        assert doc["type"] == "doc"
        assert doc["version"] == 1
        assert doc["content"][0]["type"] == "paragraph"

    def test_body_lines_and_url_footer(self):
        doc = build_adf_description("Line one\nLine two", "https://x/1")
        assert _texts(doc) == [
            "Line one",
            "Line two",
            "Imported from GitHub: https://x/1",
        ]

    def test_blank_lines_skipped(self):
        doc = build_adf_description("a\n\n  \nb", None)
        assert _texts(doc) == ["a", "b"]

    def test_empty_body_no_url_has_empty_paragraph(self):
        doc = build_adf_description("", None)
        assert doc["content"] == [{"type": "paragraph", "content": []}]

    def test_empty_body_with_url(self):
        doc = build_adf_description("", "https://x/9")
        assert _texts(doc) == ["Imported from GitHub: https://x/9"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.to_jira'`.

- [ ] **Step 3: Create the module with the function**

Create `scripts/to_jira.py`:

```python
#!/usr/bin/env python3
"""Transform a GHPM JSON export into acli bulk-create input and import to Jira."""

from __future__ import annotations

from typing import Any


def build_adf_description(body: str, url: str | None = None) -> dict[str, Any]:
    """Build an Atlassian Document Format description from plain text + URL."""
    content: list[dict[str, Any]] = []
    for line in (body or "").splitlines():
        if line.strip():
            content.append(
                {"type": "paragraph", "content": [{"type": "text", "text": line}]}
            )
    if url:
        content.append(
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": f"Imported from GitHub: {url}"}],
            }
        )
    if not content:
        content.append({"type": "paragraph", "content": []})
    return {"type": "doc", "version": 1, "content": content}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: add ADF description builder for Jira import"
```

---

### Task 5: `issue_to_jira`

**Files:**
- Modify: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py`

**Interfaces:**
- Consumes: `build_adf_description` (Task 4); a GHPM record dict.
- Produces: `issue_to_jira(record, *, project_key, type_field, default_type) -> dict` with keys
  `summary, projectKey, issueType, description`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_to_jira.py`:

```python
from scripts.to_jira import issue_to_jira


class TestIssueToJira:
    def _record(self, **over):
        rec = {
            "number": 1,
            "title": "Fix bug",
            "type": "Issue",
            "url": "https://x/1",
            "body": "details",
            "fields": {"Type": "Bug"},
        }
        rec.update(over)
        return rec

    def test_maps_core_fields(self):
        out = issue_to_jira(
            self._record(), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["summary"] == "Fix bug"
        assert out["projectKey"] == "SCOUT"
        assert out["issueType"] == "Bug"
        assert out["description"]["type"] == "doc"

    def test_issue_type_falls_back_to_default(self):
        out = issue_to_jira(
            self._record(fields={}), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["issueType"] == "Task"

    def test_missing_title_becomes_empty_string(self):
        out = issue_to_jira(
            self._record(title=None), project_key="SCOUT", type_field="Type", default_type="Task"
        )
        assert out["summary"] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_to_jira.py::TestIssueToJira -v`
Expected: FAIL with `ImportError: cannot import name 'issue_to_jira'`.

- [ ] **Step 3: Implement `issue_to_jira`**

Append to `scripts/to_jira.py` (below `build_adf_description`):

```python
def issue_to_jira(
    record: dict[str, Any],
    *,
    project_key: str,
    type_field: str,
    default_type: str,
) -> dict[str, Any]:
    """Map one GHPM record to one acli issue object."""
    issue_type = record.get("fields", {}).get(type_field) or default_type
    return {
        "summary": record.get("title") or "",
        "projectKey": project_key,
        "issueType": issue_type,
        "description": build_adf_description(record.get("body") or "", record.get("url")),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: map GHPM record to acli issue object"
```

---

### Task 6: `transform`

**Files:**
- Modify: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py`

**Interfaces:**
- Consumes: `issue_to_jira` (Task 5); a parsed GHPM export dict.
- Produces: `transform(export, *, project_key, type_field, default_type) -> list[dict]` — filters
  `export["items"]` to `type == "Issue"` and maps each.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_to_jira.py`:

```python
from scripts.to_jira import transform


class TestTransform:
    def test_filters_to_issues_only(self):
        export = {
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "", "fields": {"Type": "Bug"}},
                {"type": "PullRequest", "title": "PR", "url": "u2", "body": "", "fields": {}},
                {"type": "DraftIssue", "title": "D", "url": None, "body": "", "fields": {}},
            ]
        }
        issues = transform(export, project_key="SCOUT", type_field="Type", default_type="Task")
        assert len(issues) == 1
        assert issues[0]["summary"] == "A"
        assert issues[0]["issueType"] == "Bug"

    def test_handles_missing_items_key(self):
        assert transform({}, project_key="S", type_field="Type", default_type="Task") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_to_jira.py::TestTransform -v`
Expected: FAIL with `ImportError: cannot import name 'transform'`.

- [ ] **Step 3: Implement `transform`**

Append to `scripts/to_jira.py`:

```python
def transform(
    export: dict[str, Any],
    *,
    project_key: str,
    type_field: str,
    default_type: str,
) -> list[dict[str, Any]]:
    """Filter export items to Issues and map each to an acli issue object."""
    issues: list[dict[str, Any]] = []
    for record in export.get("items", []):
        if record.get("type") != "Issue":
            continue
        issues.append(
            issue_to_jira(
                record,
                project_key=project_key,
                type_field=type_field,
                default_type=default_type,
            )
        )
    return issues
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: transform GHPM export to acli issues (issues only)"
```

---

### Task 7: `parse_args` + `main` (write file, gate, invoke acli)

**Files:**
- Modify: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py`

**Interfaces:**
- Consumes: `transform` (Task 6); `acli_client.acli_available`, `acli_client.bulk_create` (Task 3);
  `scripts.common.get_today`.
- Produces: `parse_args(args=None) -> argparse.Namespace` (`.input`, `.jira_project`, `.type_field`,
  `.default_type`, `.out`, `.dry_run`, `.yes`); `main(args=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_to_jira.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from scripts.to_jira import main, parse_args

EXPORT = {
    "project": "workX",
    "count": 2,
    "items": [
        {"number": 1, "title": "A", "type": "Issue", "state": "OPEN",
         "url": "https://x/1", "body": "hello", "assignees": [], "fields": {"Type": "Bug"}},
        {"number": 2, "title": "PR", "type": "PullRequest", "state": "OPEN",
         "url": "https://x/2", "body": "", "assignees": [], "fields": {}},
    ],
}


def _write_export(tmp_path):
    p = tmp_path / "export.json"
    p.write_text(json.dumps(EXPORT))
    return p


class TestParseArgs:
    def test_requires_input_and_project(self):
        with pytest.raises(SystemExit):
            parse_args(["--input", "x.json"])  # missing --jira-project

    def test_defaults(self):
        a = parse_args(["--input", "x.json", "--jira-project", "SCOUT"])
        assert a.type_field == "Type"
        assert a.default_type == "Task"
        assert a.dry_run is False
        assert a.yes is False


class TestMain:
    def test_dry_run_writes_file_and_skips_acli(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.bulk_create") as bc:
            rc = main([
                "--input", str(inp), "--jira-project", "SCOUT",
                "--out", str(out), "--dry-run",
            ])
        assert rc == 0
        bc.assert_not_called()
        payload = json.loads(out.read_text())
        assert len(payload["issues"]) == 1  # PR filtered out
        assert payload["issues"][0]["projectKey"] == "SCOUT"

    def test_invokes_acli_after_confirmation(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.bulk_create", return_value=0) as bc:
                with patch("builtins.input", return_value="y"):
                    rc = main([
                        "--input", str(inp), "--jira-project", "SCOUT", "--out", str(out),
                    ])
        assert rc == 0
        bc.assert_called_once_with(str(out), yes=True)

    def test_abort_when_user_declines(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.bulk_create") as bc:
                with patch("builtins.input", return_value="n"):
                    rc = main([
                        "--input", str(inp), "--jira-project", "SCOUT", "--out", str(out),
                    ])
        assert rc != 0
        bc.assert_not_called()

    def test_yes_skips_prompt(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.bulk_create", return_value=0) as bc:
                with patch("builtins.input", side_effect=AssertionError("should not prompt")):
                    rc = main([
                        "--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes",
                    ])
        assert rc == 0
        bc.assert_called_once_with(str(out), yes=True)

    def test_errors_on_missing_acli(self, tmp_path):
        inp = _write_export(tmp_path)
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=False):
            with patch("scripts.to_jira.bulk_create") as bc:
                rc = main([
                    "--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes",
                ])
        assert rc != 0
        bc.assert_not_called()

    def test_bad_input_file_returns_error(self, tmp_path):
        bad = tmp_path / "nope.json"
        rc = main(["--input", str(bad), "--jira-project", "SCOUT", "--dry-run"])
        assert rc != 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_to_jira.py::TestMain -v`
Expected: FAIL with `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Implement `parse_args` and `main`**

Update the top of `scripts/to_jira.py` to consolidate imports and wire dependencies. Replace the existing header (`from __future__ ...` through `from typing import Any`) with:

```python
#!/usr/bin/env python3
"""Transform a GHPM JSON export into acli bulk-create input and import to Jira."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from scripts.acli_client import acli_available, bulk_create
from scripts.common import get_today

console = Console()
err_console = Console(stderr=True)
```

Then append at the end of `scripts/to_jira.py`:

```python
def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Import a GHPM JSON export into Jira via acli"
    )
    parser.add_argument("--input", required=True, help="Path to a GHPM JSON export")
    parser.add_argument("--jira-project", required=True, help="Jira project key")
    parser.add_argument("--type-field", default="Type", help="GHPM field used as Jira issue type")
    parser.add_argument("--default-type", default="Task", help="Jira type when the field is unset")
    parser.add_argument(
        "--out", help="Output path (default: <project>-jira-YYYY-MM-DD.json in cwd)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Write the file; do not call acli")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation and pass --yes to acli")
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    """Main entry point."""
    parsed = parse_args(args)

    try:
        export = json.loads(Path(parsed.input).read_text())
    except (OSError, json.JSONDecodeError) as e:
        err_console.print(f"[red]Could not read export '{parsed.input}': {e}[/red]")
        return 1

    issues = transform(
        export,
        project_key=parsed.jira_project,
        type_field=parsed.type_field,
        default_type=parsed.default_type,
    )

    project = export.get("project", "export")
    if parsed.out:
        out_path = Path(parsed.out)
    else:
        out_path = Path.cwd() / f"{project}-jira-{get_today().isoformat()}.json"

    out_path.write_text(json.dumps({"issues": issues}, indent=2))
    console.print(
        f"Wrote {len(issues)} issue{'s' if len(issues) != 1 else ''} to {out_path}"
    )

    if parsed.dry_run:
        return 0

    if not acli_available():
        err_console.print(
            "[red]acli not found on PATH.[/red] Install Atlassian CLI and run 'acli jira auth'."
        )
        return 1

    if not parsed.yes:
        answer = input(
            f"Create {len(issues)} issue(s) in Jira project {parsed.jira_project}? [y/N] "
        )
        if answer.strip().lower() not in ("y", "yes"):
            console.print("Aborted.")
            return 1

    return bulk_create(str(out_path), yes=True)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full test file to verify it passes**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS (all classes).

- [ ] **Step 5: Format, lint, and run the whole suite**

Run: `make format && make lint && make test`
Expected: ruff clean; all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: add to_jira main with file write and acli confirm-gate"
```

---

### Task 8: Document the command in SKILL.md

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: the `to_jira.py` CLI from Task 7. Documentation only.

- [ ] **Step 1: Add the command section**

In `SKILL.md`, after the "Download Issues" section (before "Show Iterations"), insert:

```markdown
### Import to Jira
**Intent**: Import GitHub Issues from a GHPM JSON export into Jira via acli
**Script**: `to_jira.py`
**Example invocations**:
- "ghpm: import the workX export into Jira project SCOUT"

**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python -m scripts.to_jira --input <ghpm-export.json> --jira-project <KEY> [--type-field Type] [--default-type Task] [--out <file>] [--dry-run] [--yes]
```
Writes `<project>-jira-YYYY-MM-DD.json` in the current directory when `--out` is omitted. Requires `acli` installed and `acli jira auth` completed. Imports Issues only (PRs/drafts skipped).
```

- [ ] **Step 2: Verify the suite still passes**

Run: `make test`
Expected: PASS (unchanged).

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: document to_jira import command in SKILL.md"
```

---

## Self-Review

**Spec coverage (Phase 1 only):**
- Exporter gains `body` (Issue fragment) → Tasks 1-2.
- `acli_client.py` wrapper, mocked in tests → Task 3.
- ADF description from body + URL footer → Task 4.
- `summary`/`projectKey`/`issueType` (field with default fallback) mapping → Task 5.
- Filter to Issues only → Task 6.
- CLI flags, auto-named output file, dry-run, confirm-gate, acli invocation, acli-missing handling → Task 7.
- `body` JSON-only / CSV unchanged → satisfied: `item_to_record` adds `body` (in the record/JSON), and `export_to_csv` writes only `CORE_COLUMNS + field_names`, so no `body` column appears (no change needed).
- assignee omitted; JSON input only; auth assumed → reflected (not implemented), correct per Phase 1 scope.
- SKILL.md documentation → Task 8.
- Phase 1 manual real-Jira verification (ADF acceptance on one issue) → noted in spec; performed at the post-implementation checkpoint, not a code task.

**Placeholder scan:** none — every code/test step contains complete content.

**Type consistency:** record key `body` added in Task 2 is read by `issue_to_jira`/`build_adf_description` in Tasks 4-5; acli issue object keys (`summary/projectKey/issueType/description`) are stable across Tasks 5-7; `bulk_create(json_path, yes)` signature in Task 3 matches the `bulk_create(str(out_path), yes=True)` call in Task 7; `acli_available`/`bulk_create` are imported into `scripts.to_jira` so the test patches (`scripts.to_jira.acli_available`, `scripts.to_jira.bulk_create`) resolve. `get_today` is imported into `scripts.to_jira` for auto-naming.
