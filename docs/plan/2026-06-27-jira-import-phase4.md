# Jira Import — Phase 4 (Status Transition) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After creating issues, move each to the Jira status matching its GHPM `Status`, via a batched post-create transition pass.

**Architecture:** Generalize the mapping lookup (`map_priority`→`map_value`) and add a status map + loader in `jira_mapping.py`. `acli_client.create_issue` returns the created key (via `--json`), and a new `transition_issues` batches `acli jira workitem transition`. `to_jira.main` gains a second pass: group created keys by mapped status (skipping the initial status / unset / unmapped), transition each group once with a single retry, and a `--dry-run` status plan.

**Tech Stack:** Python 3.10+, `uv`, pytest, ruff via Makefile, Atlassian `acli`, `rich`, stdlib `json`/`argparse`/`collections`.

## Global Constraints

- Python 3.10+; `from __future__ import annotations` at top of every module.
- Shared logic from `scripts.common` / `scripts.jira_mapping`; acli only via `scripts.acli_client`.
- Status is set by **transition after create**, never in the acli create payload.
- Default status map (case-insensitive keys → Jira name): `Todo→To Do, In Progress→In Progress, In Review→In Review, Blocked→Blocked, Done→Done`.
- Skip transition when the mapped target equals `--initial-status` (default `To Do`), is unset, or is unmapped. Warn **once per distinct** unmapped non-empty status value. Transition failures are reported, not fatal.
- A status group whose transition returns non-zero is retried **exactly once** (indexing-lag insurance; transitions are idempotent).
- `create_issue(issue) -> (returncode, key_or_None, combined_output)` using `acli ... create --from-json <file> --json`.
- `transition_issues(keys, status) -> (returncode, combined_output)` using `acli jira workitem transition --key "<comma-joined>" --status "<status>" --yes --ignore-errors`.
- New flags: `--status-field` (default `Status`), `--status-map-file`, `--initial-status` (default `To Do`).
- TDD: failing test first. ruff line ≤100, imports consolidated (no E402/F401/F811). `make format && make lint && make test` clean before reporting success.
- Spec: `docs/spec/2026-06-27-jira-import-phase4-status-design.md`.

---

### Task 1: Rename `map_priority` → `map_value` (generic lookup)

**Files:**
- Modify: `scripts/jira_mapping.py`, `scripts/to_jira.py`
- Test: `tests/test_jira_mapping.py`

**Interfaces:**
- Produces: `map_value(value: str | None, value_map: dict[str, str]) -> str | None` (the former `map_priority`, behavior unchanged).
- `map_priority` no longer exists.

- [ ] **Step 1: Update the tests to use `map_value`**

In `tests/test_jira_mapping.py`:
- Change the import line `from scripts.jira_mapping import DEFAULT_PRIORITY_MAP, load_priority_map, map_priority` to:

```python
from scripts.jira_mapping import DEFAULT_PRIORITY_MAP, load_priority_map, map_value
```

- Rename the class `class TestMapPriority:` to `class TestMapValue:`.
- Replace every `map_priority(` with `map_value(` within that class (all its assertions).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_jira_mapping.py -v`
Expected: FAIL with `ImportError: cannot import name 'map_value'`.

- [ ] **Step 3: Rename the function and update call sites**

In `scripts/jira_mapping.py`, rename `map_priority` to `map_value` (keep the body):

```python
def map_value(value: str | None, value_map: dict[str, str]) -> str | None:
    """Return the mapped value for a GHPM value, or None if unset/unmapped."""
    if not value:
        return None
    return value_map.get(str(value).lower())
```

In `scripts/to_jira.py`:
- Change the import `from scripts.jira_mapping import load_priority_map, map_priority` to:

```python
from scripts.jira_mapping import load_priority_map, map_value
```

- In `issue_to_jira`, change `map_priority(` to `map_value(`.
- In `main`, change `map_priority(value, priority_map)` to `map_value(value, priority_map)`.

- [ ] **Step 4: Run the full suite to verify it passes**

Run: `uv run pytest -q`
Expected: PASS (rename is behavior-preserving; `map_value` is now used in both `jira_mapping` tests and `to_jira`).

- [ ] **Step 5: Commit**

```bash
git add scripts/jira_mapping.py scripts/to_jira.py tests/test_jira_mapping.py
git commit -m "refactor: generalize map_priority to map_value"
```

---

### Task 2: Status map + shared loader

**Files:**
- Modify: `scripts/jira_mapping.py`
- Test: `tests/test_jira_mapping.py`

**Interfaces:**
- Consumes: `GHPMError`, `DEFAULT_PRIORITY_MAP`.
- Produces:
  - `DEFAULT_STATUS_MAP: dict[str, str]` (lowercase keys).
  - `load_value_map(path: str | None, defaults: dict[str, str], label: str) -> dict[str, str]` — generic loader.
  - `load_status_map(path: str | None) -> dict[str, str]`.
  - `load_priority_map(path: str | None) -> dict[str, str]` now delegates to `load_value_map`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_mapping.py`:

```python
from scripts.jira_mapping import DEFAULT_STATUS_MAP, load_status_map


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
        import json

        f = tmp_path / "s.json"
        f.write_text(json.dumps({"Blocked": "On Hold", "Backlog": "To Do"}))
        m = load_status_map(str(f))
        assert m["blocked"] == "On Hold"
        assert m["backlog"] == "To Do"
        assert m["done"] == "Done"

    def test_load_status_map_invalid_raises(self, tmp_path):
        import pytest

        f = tmp_path / "bad.json"
        f.write_text("[1,2]")
        with pytest.raises(Exception):
            load_status_map(str(f))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_jira_mapping.py::TestStatusMap -v`
Expected: FAIL with `ImportError: cannot import name 'DEFAULT_STATUS_MAP'`.

- [ ] **Step 3: Add the status map and refactor the loader**

In `scripts/jira_mapping.py`, add `DEFAULT_STATUS_MAP` after `DEFAULT_PRIORITY_MAP`:

```python
DEFAULT_STATUS_MAP: dict[str, str] = {
    "todo": "To Do",
    "in progress": "In Progress",
    "in review": "In Review",
    "blocked": "Blocked",
    "done": "Done",
}
```

Replace the existing `load_priority_map` with a generic loader plus two thin wrappers:

```python
def load_value_map(path: str | None, defaults: dict[str, str], label: str) -> dict[str, str]:
    """Return `defaults`, optionally overridden/extended by a JSON object file.

    The file must be an object of {GHPMValue: JiraName}; keys are lowercased and
    merged over the defaults. Raises GHPMError on a missing/invalid file.
    """
    result = dict(defaults)
    if path is None:
        return result
    try:
        loaded = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise GHPMError(f"Could not read {label} map '{path}': {e}")
    if not isinstance(loaded, dict):
        raise GHPMError(f"{label} map '{path}' must be a JSON object of value->name")
    for key, name in loaded.items():
        result[str(key).lower()] = name
    return result


def load_priority_map(path: str | None) -> dict[str, str]:
    """Return the priority map: defaults, optionally overridden by a JSON file."""
    return load_value_map(path, DEFAULT_PRIORITY_MAP, "priority")


def load_status_map(path: str | None) -> dict[str, str]:
    """Return the status map: defaults, optionally overridden by a JSON file."""
    return load_value_map(path, DEFAULT_STATUS_MAP, "status")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_jira_mapping.py -v`
Expected: PASS — new status tests plus the existing priority-loader tests (their error assertions don't match on message text, so the refactor is safe).

- [ ] **Step 5: Commit**

```bash
git add scripts/jira_mapping.py tests/test_jira_mapping.py
git commit -m "feat: add DEFAULT_STATUS_MAP and shared load_value_map"
```

---

### Task 3: `create_issue` returns the created key

**Files:**
- Modify: `scripts/acli_client.py`, `scripts/to_jira.py`
- Test: `tests/test_acli_client.py`, `tests/test_to_jira.py`

**Interfaces:**
- Produces: `create_issue(issue: dict) -> tuple[int, str | None, str]` — `(returncode, key_or_None, combined_output)`. Command now includes `--json`; `key` is parsed from stdout JSON's top-level `key`.

- [ ] **Step 1: Update the acli_client tests**

Replace the two `create_issue` tests in `tests/test_acli_client.py` with:

```python
def test_create_issue_returns_key_from_json(mock_subprocess_run, monkeypatch):
    import json

    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(
        returncode=0, stdout=json.dumps({"key": "B14-9", "fields": {}}), stderr=""
    )

    rc, key, output = create_issue({"summary": "x", "projectKey": "B14", "type": "Task"})

    assert rc == 0
    assert key == "B14-9"
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd[:5] == ["acli", "jira", "workitem", "create", "--from-json"]
    assert cmd[-1] == "--json"
    assert mock_subprocess_run.call_args.kwargs.get("capture_output") is True


def test_create_issue_failure_returns_none_key_and_output(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="request body invalid"
    )

    rc, key, output = create_issue({"summary": "x"})

    assert rc == 1
    assert key is None
    assert "request body invalid" in output
```

(Leave `test_acli_available_reflects_which` and `test_create_issue_raises_when_acli_missing` as they are.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_acli_client.py -v`
Expected: FAIL — `create_issue` returns a 2-tuple (unpack into 3 vars raises ValueError) and the command lacks `--json`.

- [ ] **Step 3: Update `create_issue`**

In `scripts/acli_client.py`, replace `create_issue` with:

```python
def create_issue(issue: dict[str, Any]) -> tuple[int, str | None, str]:
    """Create a single Jira work item from an issue dict via acli.

    Writes the issue to a temp JSON file and runs
    `acli jira workitem create --from-json <file> --json`. Returns
    (exit_code, key_or_None, combined_output). Raises GHPMError if acli is missing.
    """
    if not acli_available():
        raise GHPMError("acli not found on PATH. Install Atlassian CLI and run 'acli jira auth'.")

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(issue, f)
        path = f.name
    try:
        result = subprocess.run(
            ["acli", "jira", "workitem", "create", "--from-json", path, "--json"],
            capture_output=True,
            text=True,
        )
    finally:
        os.unlink(path)

    key: str | None = None
    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            key = data.get("key")
    except (json.JSONDecodeError, TypeError):
        pass
    return result.returncode, key, (result.stdout or "") + (result.stderr or "")
```

- [ ] **Step 4: Update the `main` create loop to the 3-tuple**

In `scripts/to_jira.py`, in the create loop, change the unpack so it ignores the key for now (Task 5 will use it):

Change:

```python
            rc, output = create_issue(issue)
```

to:

```python
            rc, _, output = create_issue(issue)
```

- [ ] **Step 5: Update `to_jira` main tests that mock `create_issue`**

In `tests/test_to_jira.py`, update every mocked `create_issue` return to the 3-tuple form:
- In `test_creates_each_issue_after_confirmation`: `return_value=(0, "created")` → `return_value=(0, "B14-1", "created")`.
- In `test_partial_failure_returns_nonzero`: `side_effect=[(0, "ok"), (1, "boom")]` → `side_effect=[(0, "B14-1", "ok"), (1, None, "boom")]`.
- In `test_yes_skips_prompt`: `return_value=(0, "created")` → `return_value=(0, "B14-1", "created")`.

(The tests that patch `create_issue` but assert it is *not* called — dry-run, abort, missing-acli, zero-issues — need no return value change.)

- [ ] **Step 6: Run the full suite**

Run: `make format && make lint && make test`
Expected: PASS; ruff clean.

- [ ] **Step 7: Commit**

```bash
git add scripts/acli_client.py scripts/to_jira.py tests/test_acli_client.py tests/test_to_jira.py
git commit -m "feat: create_issue returns created key via --json"
```

---

### Task 4: `transition_issues` wrapper

**Files:**
- Modify: `scripts/acli_client.py`
- Test: `tests/test_acli_client.py`

**Interfaces:**
- Produces: `transition_issues(keys: list[str], status: str) -> tuple[int, str]` — runs
  `acli jira workitem transition --key "<comma-joined>" --status "<status>" --yes --ignore-errors`;
  returns `(returncode, combined_output)`; raises `GHPMError` if acli is missing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_acli_client.py`:

```python
def test_transition_issues_builds_batched_command(mock_subprocess_run, monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: "/usr/bin/acli")
    mock_subprocess_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")

    rc, output = transition_issues(["B14-1", "B14-2"], "Done")

    assert rc == 0
    assert output == "ok"
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd == [
        "acli", "jira", "workitem", "transition",
        "--key", "B14-1,B14-2", "--status", "Done", "--yes", "--ignore-errors",
    ]


def test_transition_issues_raises_when_acli_missing(monkeypatch):
    monkeypatch.setattr("scripts.acli_client.shutil.which", lambda name: None)
    with pytest.raises(GHPMError, match="acli"):
        transition_issues(["B14-1"], "Done")
```

Update the import at the top of `tests/test_acli_client.py`:

```python
from scripts.acli_client import acli_available, create_issue, transition_issues
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_acli_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'transition_issues'`.

- [ ] **Step 3: Implement `transition_issues`**

Append to `scripts/acli_client.py`:

```python
def transition_issues(keys: list[str], status: str) -> tuple[int, str]:
    """Transition the given issue keys to a target status via acli (batched).

    Returns (exit_code, combined_output). Raises GHPMError if acli is missing.
    """
    if not acli_available():
        raise GHPMError("acli not found on PATH. Install Atlassian CLI and run 'acli jira auth'.")
    result = subprocess.run(
        [
            "acli", "jira", "workitem", "transition",
            "--key", ",".join(keys), "--status", status, "--yes", "--ignore-errors",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_acli_client.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/acli_client.py tests/test_acli_client.py
git commit -m "feat: add transition_issues batched acli wrapper"
```

---

### Task 5: `main` — status flags, transition pass, dry-run plan

**Files:**
- Modify: `scripts/to_jira.py`
- Test: `tests/test_to_jira.py`

**Interfaces:**
- Consumes: `load_status_map`, `map_value` (Tasks 1-2); `create_issue` (3-tuple, Task 3); `transition_issues` (Task 4); `iter_issue_records`, `transform`.
- Produces: `parse_args` gains `--status-field` (default `Status`), `--status-map-file`, `--initial-status` (default `To Do`); a module-level helper `status_target(record, *, status_field, status_map, initial_status) -> str | None`; `main` performs the transition pass.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_to_jira.py`:

In `class TestParseArgs`:

```python
    def test_status_defaults(self):
        a = parse_args(["--input", "x.json", "--jira-project", "SCOUT"])
        assert a.status_field == "Status"
        assert a.status_map_file is None
        assert a.initial_status == "To Do"
```

In `class TestMain` (the export below mixes statuses; helper `_write` writes it):

```python
    def _status_export(self):
        return {
            "project": "workX",
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "",
                 "fields": {"Status": "In Progress"}},
                {"type": "Issue", "title": "B", "url": "u2", "body": "",
                 "fields": {"Status": "In Progress"}},
                {"type": "Issue", "title": "C", "url": "u3", "body": "",
                 "fields": {"Status": "Done"}},
                {"type": "Issue", "title": "D", "url": "u4", "body": "",
                 "fields": {"Status": "Todo"}},
            ],
        }

    def test_transitions_grouped_by_status_skipping_initial(self, tmp_path):
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(self._status_export()))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch(
                "scripts.to_jira.create_issue",
                side_effect=[(0, "K1", "ok"), (0, "K2", "ok"), (0, "K3", "ok"), (0, "K4", "ok")],
            ):
                with patch("scripts.to_jira.transition_issues", return_value=(0, "")) as tr:
                    rc = main(
                        ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                    )
        assert rc == 0
        # Grouped: In Progress -> [K1, K2], Done -> [K3]; Todo (==initial) skipped.
        calls = {c.args[1]: c.args[0] for c in tr.call_args_list}
        assert calls["In Progress"] == ["K1", "K2"]
        assert calls["Done"] == ["K3"]
        assert "To Do" not in calls

    def test_unmapped_status_warns_once_and_skips(self, tmp_path, capsys):
        export = {
            "project": "workX",
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "",
                 "fields": {"Status": "Weird"}},
                {"type": "Issue", "title": "B", "url": "u2", "body": "",
                 "fields": {"Status": "Weird"}},
            ],
        }
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue", side_effect=[(0, "K1", "ok"), (0, "K2", "ok")]):
                with patch("scripts.to_jira.transition_issues") as tr:
                    rc = main(
                        ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                    )
        assert rc == 0
        tr.assert_not_called()
        assert capsys.readouterr().err.count("Weird") == 1

    def test_failed_transition_group_retried_once(self, tmp_path):
        export = {
            "project": "workX",
            "items": [
                {"type": "Issue", "title": "A", "url": "u1", "body": "",
                 "fields": {"Status": "Done"}},
            ],
        }
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(export))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.acli_available", return_value=True):
            with patch("scripts.to_jira.create_issue", side_effect=[(0, "K1", "ok")]):
                with patch(
                    "scripts.to_jira.transition_issues", side_effect=[(1, "lag"), (0, "")]
                ) as tr:
                    rc = main(
                        ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--yes"]
                    )
        assert rc == 0
        assert tr.call_count == 2  # first failed, retried once

    def test_dry_run_prints_status_plan_and_calls_nothing(self, tmp_path, capsys):
        inp = tmp_path / "s.json"
        inp.write_text(json.dumps(self._status_export()))
        out = tmp_path / "acli.json"
        with patch("scripts.to_jira.create_issue") as ci:
            with patch("scripts.to_jira.transition_issues") as tr:
                rc = main(
                    ["--input", str(inp), "--jira-project", "SCOUT", "--out", str(out), "--dry-run"]
                )
        assert rc == 0
        ci.assert_not_called()
        tr.assert_not_called()
        outerr = capsys.readouterr().out
        assert "In Progress" in outerr and "Done" in outerr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_to_jira.py::TestParseArgs::test_status_defaults tests/test_to_jira.py::TestMain -v`
Expected: FAIL — `parse_args` lacks the status flags; `main` does no transition / plan; `transition_issues` not imported into `scripts.to_jira` (patch target missing).

- [ ] **Step 3: Add imports, flags, and the `status_target` helper**

In `scripts/to_jira.py`, update the imports:

```python
from collections import Counter

from scripts.acli_client import acli_available, create_issue, transition_issues
from scripts.jira_mapping import load_priority_map, load_status_map, map_value
```

(`from collections import Counter` goes in the stdlib import group; keep imports sorted.)

Add the helper (module level, near `iter_issue_records`):

```python
def status_target(
    record: dict[str, Any],
    *,
    status_field: str,
    status_map: dict[str, str],
    initial_status: str,
) -> str | None:
    """Return the Jira status to transition this record to, or None to skip.

    Skips (returns None) when the status is unset, unmapped, or already the
    project's initial status.
    """
    target = map_value((record.get("fields") or {}).get(status_field), status_map)
    if not target or target == initial_status:
        return None
    return target
```

In `parse_args`, add after the `--priority-map-file` argument:

```python
    parser.add_argument("--status-field", default="Status", help="GHPM field used as Jira status")
    parser.add_argument(
        "--status-map-file", help="JSON file overriding the GHPM->Jira status map"
    )
    parser.add_argument(
        "--initial-status",
        default="To Do",
        help="Jira initial status; issues mapping to it are not transitioned",
    )
```

- [ ] **Step 4: Wire the status map load + warnings + dry-run plan into `main`**

In `scripts/to_jira.py` `main`, immediately after the existing priority-map load/warn block (right before `issues = transform(...)`), add the status map load and unmapped-status warnings:

```python
    try:
        status_map = load_status_map(parsed.status_map_file)
    except GHPMError as e:
        err_console.print(f"[red]{e}[/red]")
        return 1

    unmapped_status = sorted(
        {
            value
            for r in records
            if (value := (r.get("fields") or {}).get(parsed.status_field))
            and map_value(value, status_map) is None
        }
    )
    for value in unmapped_status:
        err_console.print(
            f"[yellow]Warning: status '{value}' not mapped; leaving at initial.[/yellow]"
        )
```

Then, in the `if parsed.dry_run:` block (currently `return 0`), print the plan before returning:

```python
    if parsed.dry_run:
        plan = Counter(
            t
            for r in records
            if (
                t := status_target(
                    r,
                    status_field=parsed.status_field,
                    status_map=status_map,
                    initial_status=parsed.initial_status,
                )
            )
        )
        if plan:
            console.print("Status transition plan:")
            for status, count in sorted(plan.items()):
                console.print(f"  {count} -> {status}")
        return 0
```

- [ ] **Step 5: Collect created keys and run the transition pass**

In `scripts/to_jira.py` `main`, change the create loop to iterate records+issues together and collect `(record, key)` for successes. Replace the existing loop body:

```python
    total = len(issues)
    created = 0
    failed = 0
    created_pairs: list[tuple[dict[str, Any], str | None]] = []
    try:
        for idx, (record, issue) in enumerate(zip(records, issues), 1):
            label = issue.get("summary") or f"item {idx}"
            rc, key, output = create_issue(issue)
            if rc == 0:
                created += 1
                created_pairs.append((record, key))
                console.print(f"[{idx}/{total}] created: {label}")
            else:
                failed += 1
                err_console.print(f"[{idx}/{total}] FAILED: {label}: {output.strip()}")
    except GHPMError as e:
        err_console.print(f"[red]Error: {e}[/red]")
        return 1

    console.print(f"Done: {created} created, {failed} failed")
```

Then append the transition pass after that summary line (before `return 0 if failed == 0 else 1`):

```python
    groups: dict[str, list[str]] = {}
    for record, key in created_pairs:
        if not key:
            continue
        target = status_target(
            record,
            status_field=parsed.status_field,
            status_map=status_map,
            initial_status=parsed.initial_status,
        )
        if target:
            groups.setdefault(target, []).append(key)

    for status, keys in groups.items():
        rc, out = transition_issues(keys, status)
        if rc != 0:
            rc, out = transition_issues(keys, status)  # retry once (indexing lag)
        if rc == 0:
            console.print(f"Transitioned {len(keys)} issue(s) -> {status}")
        else:
            err_console.print(
                f"[red]Failed to transition {len(keys)} issue(s) -> {status}: {out.strip()}[/red]"
            )
```

(Leave the final `return 0 if failed == 0 else 1` as the last statement.)

- [ ] **Step 6: Run the full test file, then format/lint/suite**

Run: `uv run pytest tests/test_to_jira.py -v`
Expected: PASS.
Run: `make format && make lint && make test`
Expected: ruff clean; all tests pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/to_jira.py tests/test_to_jira.py
git commit -m "feat: transition issues to mapped Jira status after create"
```

---

### Task 6: Document status flags in SKILL.md

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: the Phase 4 CLI from Task 5. Documentation only.

- [ ] **Step 1: Update the Import to Jira command**

In `SKILL.md`, replace the "Import to Jira" execution code block and its trailing note with:

```markdown
**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python -m scripts.to_jira --input <ghpm-export.json> --jira-project <KEY> [--type-field Type] [--default-type Task] [--priority-field Priority] [--priority-map-file <map.json>] [--status-field Status] [--status-map-file <map.json>] [--initial-status "To Do"] [--out <file>] [--dry-run] [--yes]
```
Writes `<project>-jira-YYYY-MM-DD.json` in the current directory when `--out` is omitted. Requires `acli` installed and `acli jira auth` completed. Imports Issues only (PRs/drafts skipped). Maps GHPM Priority to Jira priority (Urgent→Highest, Postponed→Lowest, others pass through). After creating issues, transitions each to the Jira status mapping its GHPM Status (Todo→To Do, etc.); issues already at the initial status are not transitioned. Unmapped priority/status values are skipped with a warning. Override maps with `--priority-map-file` / `--status-map-file`. `--dry-run` writes the file and prints the status transition plan without calling acli.
```

- [ ] **Step 2: Verify the suite still passes**

Run: `make test`
Expected: PASS (unchanged).

- [ ] **Step 3: Commit**

```bash
git add SKILL.md
git commit -m "docs: document status transition flags for to_jira"
```

---

## Self-Review

**Spec coverage:**
- `map_priority`→`map_value` generalization → Task 1.
- `DEFAULT_STATUS_MAP` + `load_status_map` (+ shared `load_value_map`, DRY) → Task 2.
- `create_issue` returns key via `--json` → Task 3.
- `transition_issues` batched wrapper (`--key a,b --status X --yes --ignore-errors`) → Task 4.
- Status not in create payload (`issue_to_jira`/`transform` untouched) → honored (only `main`/helpers change).
- Flags `--status-field`/`--status-map-file`/`--initial-status` → Task 5.
- Skip target == initial / unset / unmapped; warn once per distinct unmapped; batch by status; retry failed group once → Task 5 (`status_target` + transition pass).
- `--dry-run` prints transition plan, calls neither create nor transition → Task 5.
- SKILL.md docs → Task 6.
- Live verification (In Progress/Done/Todo against B14) → manual checkpoint, noted in spec.

**Placeholder scan:** none — every code/test step has complete content.

**Type consistency:** `map_value(value, value_map) -> str | None` (Task 1) used in `status_target` and warnings (Task 5); `load_status_map`/`load_value_map` (Task 2) signatures match call sites; `create_issue -> (int, str|None, str)` (Task 3) matches the `rc, key, output` unpack and the test mocks' 3-tuples (Task 5); `transition_issues(keys, status) -> (int, str)` (Task 4) matches `rc, out = transition_issues(...)` (Task 5); `status_target(...)` keyword-only params match both call sites (dry-run plan + transition pass). Patches target `scripts.to_jira.create_issue` / `scripts.to_jira.transition_issues`, both imported into `to_jira` in Task 5.

**Note for implementer:** Task 3 changes `create_issue` to a 3-tuple and updates the loop unpack to `rc, _, output`; Task 5 then rewrites that loop to `rc, key, output` with key collection. Ensure no leftover `rc, _, output` remains after Task 5, and that `transition_issues`/`Counter`/`load_status_map` imports are all used (no F401) once Task 5 lands.
