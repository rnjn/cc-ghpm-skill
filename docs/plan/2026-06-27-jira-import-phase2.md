# Jira Import — Phase 2 (Priority Mapping) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry the GHPM `Priority` field into Jira's standard `priority` field during import, with a configurable value map.

**Architecture:** A new `scripts/jira_mapping.py` holds the default priority map, an override-file loader, and a `map_priority` lookup. `scripts/to_jira.py`'s `issue_to_jira` gains optional priority params and emits `additionalAttributes.priority.name` when a value maps; `transform` forwards them; `main` adds two flags, loads the map, and warns once per distinct unmapped value. All acli interaction is unchanged (per-issue `create`, mocked via `scripts.acli_client`).

**Tech Stack:** Python 3.10+, `uv`, pytest, ruff via Makefile, Atlassian `acli`, `rich`, stdlib `json`/`argparse`.

## Global Constraints

- Python 3.10+; `from __future__ import annotations` at top of every module.
- Shared logic imported from `scripts.common` / `scripts.jira_mapping`; acli only via `scripts.acli_client`.
- Priority is set on the acli issue object as `additionalAttributes: {"priority": {"name": "<JiraName>"}}` (top-level `priority` is rejected by acli).
- Default priority map (case-insensitive keys → Jira name): `Low→Low, Medium→Medium, High→High, Urgent→Highest, Postponed→Lowest`.
- Unset/`None` priority → omit `additionalAttributes`, no warning. A non-empty value not in the map → omit, and warn **once per distinct value**. Never fail an issue over priority.
- New flags: `--priority-field` (default `Priority`), `--priority-map-file` (optional JSON `{"GHPMValue":"JiraName"}`, merged over defaults).
- TDD: failing test first. ruff line length ≤100, imports consolidated (no E402). `make format && make lint && make test` clean before reporting success.
- Spec: `docs/spec/2026-06-27-jira-import-phase2-priority-design.md`.

---

### Task 1: `jira_mapping.py` — default map, loader, lookup

**Files:**
- Create: `scripts/jira_mapping.py`
- Test: `tests/test_jira_mapping.py`

**Interfaces:**
- Consumes: `GHPMError` from `scripts.common`.
- Produces:
  - `DEFAULT_PRIORITY_MAP: dict[str, str]` (lowercase keys).
  - `map_priority(value: str | None, value_map: dict[str, str]) -> str | None`.
  - `load_priority_map(path: str | None) -> dict[str, str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jira_mapping.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_jira_mapping.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.jira_mapping'`.

- [ ] **Step 3: Create the module**

Create `scripts/jira_mapping.py`:

```python
#!/usr/bin/env python3
"""Field/value mapping helpers for the Jira importer."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.common import GHPMError

# Case-insensitive keys (lowercase) → Jira priority name.
DEFAULT_PRIORITY_MAP: dict[str, str] = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
    "urgent": "Highest",
    "postponed": "Lowest",
}


def map_priority(value: str | None, value_map: dict[str, str]) -> str | None:
    """Return the Jira priority name for a GHPM value, or None if unset/unmapped."""
    if not value:
        return None
    return value_map.get(value.lower())


def load_priority_map(path: str | None) -> dict[str, str]:
    """Return the priority map: defaults, optionally overridden/extended by a JSON file.

    The JSON file must be an object of {GHPMValue: JiraName}. Keys are lowercased
    and merged over the defaults. Raises GHPMError on a missing/invalid file.
    """
    result = dict(DEFAULT_PRIORITY_MAP)
    if path is None:
        return result
    try:
        loaded = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise GHPMError(f"Could not read priority map '{path}': {e}")
    if not isinstance(loaded, dict):
        raise GHPMError(f"Priority map '{path}' must be a JSON object of value->name")
    for key, name in loaded.items():
        result[str(key).lower()] = name
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_jira_mapping.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/jira_mapping.py tests/test_jira_mapping.py
git commit -m "feat: add jira_mapping with default priority map and loader"
```

---

### Task 2: `issue_to_jira` emits priority

**Files:**
- Modify: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py` (`TestIssueToJira`)

**Interfaces:**
- Consumes: `map_priority` (Task 1).
- Produces: `issue_to_jira(record, *, project_key, type_field, default_type, priority_field="Priority", priority_map=None) -> dict`. When `priority_map` is provided and the record's priority maps to a name, the result includes `additionalAttributes: {"priority": {"name": <name>}}`; otherwise no `additionalAttributes` key.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_to_jira.py` inside `class TestIssueToJira` (after `test_missing_title_becomes_empty_string`):

```python
    def test_adds_priority_when_mapped(self):
        from scripts.jira_mapping import DEFAULT_PRIORITY_MAP

        out = issue_to_jira(
            self._record(fields={"Priority": "Urgent"}),
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
            priority_field="Priority",
            priority_map=DEFAULT_PRIORITY_MAP,
        )
        assert out["additionalAttributes"] == {"priority": {"name": "Highest"}}

    def test_omits_additional_attributes_when_unmapped(self):
        from scripts.jira_mapping import DEFAULT_PRIORITY_MAP

        out = issue_to_jira(
            self._record(fields={"Priority": "Nope"}),
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
            priority_field="Priority",
            priority_map=DEFAULT_PRIORITY_MAP,
        )
        assert "additionalAttributes" not in out

    def test_omits_additional_attributes_when_no_priority_map(self):
        out = issue_to_jira(
            self._record(),
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
        )
        assert "additionalAttributes" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_to_jira.py::TestIssueToJira -v`
Expected: FAIL — `issue_to_jira` does not accept `priority_field`/`priority_map` (TypeError) and does not add `additionalAttributes`.

- [ ] **Step 3: Update `issue_to_jira`**

In `scripts/to_jira.py`, add the import (in the existing local-imports block):

```python
from scripts.jira_mapping import load_priority_map, map_priority
```

Then replace `issue_to_jira` with:

```python
def issue_to_jira(
    record: dict[str, Any],
    *,
    project_key: str,
    type_field: str,
    default_type: str,
    priority_field: str = "Priority",
    priority_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Map one GHPM record to one acli issue object."""
    issue_type = record.get("fields", {}).get(type_field) or default_type
    issue: dict[str, Any] = {
        "summary": record.get("title") or "",
        "projectKey": project_key,
        "type": issue_type,
        "description": build_adf_description(record.get("body") or "", record.get("url")),
    }
    if priority_map:
        name = map_priority((record.get("fields") or {}).get(priority_field), priority_map)
        if name:
            issue["additionalAttributes"] = {"priority": {"name": name}}
    return issue
```

(`load_priority_map` is imported now though first used in Task 4; ruff will not flag it as unused once Task 4 lands. If you implement strictly task-by-task and ruff flags F401 here, import only `map_priority` in this task and add `load_priority_map` in Task 4.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS (new priority tests plus all existing to_jira tests, which pass no `priority_map` and so see no `additionalAttributes`).

- [ ] **Step 5: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: issue_to_jira emits Jira priority via additionalAttributes"
```

---

### Task 3: `iter_issue_records` + `transform` forwards priority

**Files:**
- Modify: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py` (`TestTransform`)

**Interfaces:**
- Consumes: `issue_to_jira` (Task 2).
- Produces:
  - `iter_issue_records(export: dict) -> list[dict]` — the export's items filtered to `type == "Issue"`.
  - `transform(export, *, project_key, type_field, default_type, priority_field="Priority", priority_map=None) -> list[dict]` — maps each issue record, forwarding the priority params.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_to_jira.py` inside `class TestTransform`:

```python
    def test_iter_issue_records_filters_issues(self):
        from scripts.to_jira import iter_issue_records

        export = {
            "items": [
                {"type": "Issue", "title": "A"},
                {"type": "PullRequest", "title": "PR"},
                {"type": "DraftIssue", "title": "D"},
            ]
        }
        recs = iter_issue_records(export)
        assert [r["title"] for r in recs] == ["A"]

    def test_transform_forwards_priority_map(self):
        from scripts.jira_mapping import DEFAULT_PRIORITY_MAP

        export = {
            "items": [
                {"type": "Issue", "title": "A", "url": "u", "body": "",
                 "fields": {"Priority": "High"}},
            ]
        }
        issues = transform(
            export,
            project_key="SCOUT",
            type_field="Type",
            default_type="Task",
            priority_field="Priority",
            priority_map=DEFAULT_PRIORITY_MAP,
        )
        assert issues[0]["additionalAttributes"] == {"priority": {"name": "High"}}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_to_jira.py::TestTransform -v`
Expected: FAIL — `iter_issue_records` does not exist (ImportError) and `transform` does not accept `priority_map` (TypeError).

- [ ] **Step 3: Add `iter_issue_records` and update `transform`**

In `scripts/to_jira.py`, replace `transform` with these two functions:

```python
def iter_issue_records(export: dict[str, Any]) -> list[dict[str, Any]]:
    """Return export items filtered to GitHub Issues."""
    return [r for r in export.get("items", []) if r.get("type") == "Issue"]


def transform(
    export: dict[str, Any],
    *,
    project_key: str,
    type_field: str,
    default_type: str,
    priority_field: str = "Priority",
    priority_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Filter export items to Issues and map each to an acli issue object."""
    return [
        issue_to_jira(
            record,
            project_key=project_key,
            type_field=type_field,
            default_type=default_type,
            priority_field=priority_field,
            priority_map=priority_map,
        )
        for record in iter_issue_records(export)
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS (existing transform tests still pass — they pass no `priority_map`).

- [ ] **Step 5: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: add iter_issue_records and forward priority through transform"
```

---

### Task 4: `main` wiring — flags, map load, unmapped warnings

**Files:**
- Modify: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py` (`TestParseArgs`, `TestMain`)

**Interfaces:**
- Consumes: `load_priority_map`, `map_priority` (Task 1); `iter_issue_records`, `transform` (Tasks 2-3).
- Produces: `parse_args` gains `--priority-field` (default `Priority`) and `--priority-map-file` (default None); `main` loads the map, warns once per distinct unmapped non-empty priority value, and passes the map to `transform`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_to_jira.py`:

In `class TestParseArgs`:

```python
    def test_priority_defaults(self):
        a = parse_args(["--input", "x.json", "--jira-project", "SCOUT"])
        assert a.priority_field == "Priority"
        assert a.priority_map_file is None
```

In `class TestMain`:

```python
    def test_priority_in_written_file(self, tmp_path):
        export = {
            "project": "workX",
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "x",
                 "fields": {"Priority": "Urgent"}},
            ],
        }
        inp = tmp_path / "p.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        rc = main(
            ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--dry-run"]
        )
        assert rc == 0
        payload = json.loads(out.read_text())
        assert payload["issues"][0]["additionalAttributes"] == {"priority": {"name": "Highest"}}

    def test_warns_once_per_distinct_unmapped_priority(self, tmp_path, capsys):
        export = {
            "project": "workX",
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "",
                 "fields": {"Priority": "Blocker"}},
                {"type": "Issue", "title": "B", "url": "u2", "body": "",
                 "fields": {"Priority": "Blocker"}},
                {"type": "Issue", "title": "C", "url": "u3", "body": "",
                 "fields": {"Priority": "Wishlist"}},
            ],
        }
        inp = tmp_path / "p.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        rc = main(
            ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--dry-run"]
        )
        assert rc == 0
        err = capsys.readouterr().err
        assert err.count("Blocker") == 1  # warned once despite two issues
        assert "Wishlist" in err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_to_jira.py::TestParseArgs::test_priority_defaults tests/test_to_jira.py::TestMain::test_priority_in_written_file tests/test_to_jira.py::TestMain::test_warns_once_per_distinct_unmapped_priority -v`
Expected: FAIL — `parse_args` has no `priority_field`/`priority_map_file`; `main` does not add priority or warn.

- [ ] **Step 3: Add flags and wire `main`**

In `scripts/to_jira.py`, ensure the import line reads (add `load_priority_map` if you deferred it in Task 2):

```python
from scripts.jira_mapping import load_priority_map, map_priority
```

In `parse_args`, add after the `--default-type` argument:

```python
    parser.add_argument(
        "--priority-field", default="Priority", help="GHPM field used as Jira priority"
    )
    parser.add_argument(
        "--priority-map-file", help="JSON file overriding the GHPM->Jira priority map"
    )
```

In `main`, replace the `transform(...)` call block (currently lines ~106-111) with:

```python
    try:
        priority_map = load_priority_map(parsed.priority_map_file)
    except GHPMError as e:
        err_console.print(f"[red]{e}[/red]")
        return 1

    records = iter_issue_records(export)
    unmapped = sorted(
        {
            value
            for r in records
            if (value := (r.get("fields") or {}).get(parsed.priority_field))
            and map_priority(value, priority_map) is None
        }
    )
    for value in unmapped:
        err_console.print(f"[yellow]Warning: priority '{value}' not mapped; omitting.[/yellow]")

    issues = transform(
        export,
        project_key=parsed.jira_project,
        type_field=parsed.type_field,
        default_type=parsed.default_type,
        priority_field=parsed.priority_field,
        priority_map=priority_map,
    )
```

(Leave the rest of `main` — the no-issues short-circuit, file write, dry-run, confirm-gate, per-issue create loop — unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS (all classes).

- [ ] **Step 5: Format, lint, full suite**

Run: `make format && make lint && make test`
Expected: ruff clean (no E402/F401/F811); all tests pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: wire priority mapping into to_jira main with unmapped warnings"
```

---

### Task 5: Document the new flags in SKILL.md

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: the Phase 2 CLI from Task 4. Documentation only.

- [ ] **Step 1: Update the Import to Jira command**

In `SKILL.md`, update the "Import to Jira" execution block to include the new flags and a note. Replace the existing execution code block under "### Import to Jira" with:

```markdown
**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python -m scripts.to_jira --input <ghpm-export.json> --jira-project <KEY> [--type-field Type] [--default-type Task] [--priority-field Priority] [--priority-map-file <map.json>] [--out <file>] [--dry-run] [--yes]
```
Writes `<project>-jira-YYYY-MM-DD.json` in the current directory when `--out` is omitted. Requires `acli` installed and `acli jira auth` completed. Imports Issues only (PRs/drafts skipped). Maps the GHPM Priority field to Jira priority (default: Low/Medium/High pass through, Urgent→Highest, Postponed→Lowest); override with `--priority-map-file`. Unmapped priority values are omitted with a warning.
```

- [ ] **Step 2: Verify the suite still passes**

Run: `make test`
Expected: PASS (unchanged).

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: document priority mapping flags for to_jira"
```

---

## Self-Review

**Spec coverage:**
- `additionalAttributes.priority.name` mechanism → Tasks 2-3 (verified-fact constraint honored).
- Default priority map (Low/Medium/High identity, Urgent→Highest, Postponed→Lowest) → Task 1 `DEFAULT_PRIORITY_MAP`.
- `--priority-field`, `--priority-map-file` (merge over defaults) → Task 1 `load_priority_map` + Task 4 flags.
- Unset → omit silently; unmapped non-empty → omit + warn once per distinct value → Task 2 (omit) + Task 4 (warn loop over `unmapped` set).
- `jira_mapping.py` module split → Task 1.
- Never fail an issue over priority → guaranteed: unmapped values never reach the payload.
- SKILL.md docs → Task 5.
- Live verification (workX High/Urgent/unset against B14) → manual checkpoint, noted in spec; not a code task.

**Placeholder scan:** none — all steps contain complete code/tests.

**Type consistency:** `map_priority(value, value_map) -> str | None` and `load_priority_map(path) -> dict[str,str]` (Task 1) are used with matching signatures in Tasks 2 and 4; `issue_to_jira`'s new keyword-only params `priority_field` / `priority_map` (Task 2) match `transform`'s forwarding (Task 3) and `main`'s call (Task 4); `iter_issue_records(export) -> list[dict]` (Task 3) is reused by `main` for the warning set (Task 4). The argparse dest for `--priority-map-file` is `priority_map_file` (used in Task 4) and `--priority-field` is `priority_field`.

**Note for implementer:** Tasks 2-4 touch the same import line in `scripts/to_jira.py`. If implementing strictly task-by-task and ruff flags `load_priority_map` as unused after Task 2, import only `map_priority` in Task 2 and add `load_priority_map` in Task 4 (called out inline in Task 2 Step 3). After Task 4, the import block must list both, with no unused names.
