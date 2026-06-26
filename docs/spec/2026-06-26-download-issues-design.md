# Design: Download all project items (`download_issues.py`)

Date: 2026-06-26
Status: Approved

## Purpose

Add a script that exports all items on a GitHub project board — issues, pull
requests, and draft issues — together with their project field values, to a
JSON or CSV file. This becomes the fourth script in `scripts/`, following the
established pattern (parse → load config → fetch → format → write).

## CLI

```bash
uv run python scripts/download_issues.py --project <name> [--format json|csv] [--output-file PATH]
```

- `--project` (required) — project alias from `.env`, matched case-insensitively,
  exactly as `list_items.py` resolves it.
- `--format` — `json` (default) or `csv`.
- `--output-file` — optional path. When omitted, the file is auto-named
  `<project>-items-YYYY-MM-DD.<ext>` in the current working directory.

The script always writes to a file (no stdout output for the data). A single
confirmation line (item count + written path) is printed via `rich`.

## Scope

- **Included:** all project items — issues, PRs, and draft issues — with their
  project field values (Status, Iteration, Priority, and any other configured
  fields).
- **No filtering** in v1. The download is unconditional; `--status`,
  `--iteration`, `--open-only` are intentionally omitted (YAGNI). They can be
  added later if needed.
- **No stdout, no markdown format** in v1.

## Flow

Mirrors `list_items.py`:

1. Parse args.
2. Load config via `find_env_file()` / `load_config()`; verify auth with
   `check_gh_auth()`.
3. Resolve the project: `get_project_node_id()` → `get_project_fields()` →
   `get_project_items()` (paginated, all items).
4. Normalize each item to a record, then serialize via `export_to_json()` or
   `export_to_csv()`.
5. Write the file; print a confirmation line.

Errors surface through the existing `GHPMError` handling pattern, returning a
non-zero exit code with a clear message.

## Output shapes

### JSON

A wrapper object with metadata and the item list:

```json
{
  "project": "backend",
  "exported_at": "2026-06-26T14:32:00Z",
  "count": 42,
  "items": [
    {
      "number": 123,
      "title": "Fix login bug",
      "type": "Issue",
      "state": "OPEN",
      "url": "https://github.com/...",
      "assignees": ["alice"],
      "fields": {
        "Status": "In Progress",
        "Iteration": "Iteration 2",
        "Priority": "P1"
      }
    }
  ]
}
```

### CSV

Fixed core columns followed by one column per project field, with field columns
discovered from `get_project_fields()` (stable, deterministic order). An empty
cell is written when an item has no value for a field.

```
number,title,type,state,url,assignees,Status,Iteration,Priority
123,Fix login bug,Issue,OPEN,https://...,alice,In Progress,Iteration 2,P1
```

- Draft issues have no `number`/`url`; those cells are left empty.
- `assignees` is joined with `;` in CSV; it is a list in JSON.

## New code

All in `scripts/download_issues.py` unless a helper proves reusable enough to
move into `common.py`:

- `item_to_record(item) -> dict` — normalize a raw GraphQL item into
  `{number, title, type, state, url, assignees, fields}`. Handles Issue,
  PullRequest, and DraftIssue content shapes.
- `export_to_json(records, project, timestamp) -> str`.
- `export_to_csv(records, field_names) -> str` — `field_names` from project
  field defs gives stable column order.
- `main(args=None) -> int` — entry point.

The `exported_at` timestamp is passed into `export_to_json()` (not generated
inside serialization logic) so tests are deterministic.

## Testing (TDD)

New file `tests/test_download_issues.py`, reusing `conftest.py` fixtures and the
`gh`-mocking approach:

- `item_to_record` correctly normalizes issue, PR, and draft-issue items
  (including assignees and missing fields).
- `export_to_csv` emits correct headers and rows, including dynamic field
  columns and empty cells for absent values.
- `export_to_json` produces the expected structure and `count`.
- `main` end-to-end with mocked `gh` responses, writing to a tmp file, verified
  for both `json` and `csv` formats, including the auto-naming path.

Failing tests are written first, then implementation, per project TDD practice.
`make test`, `make lint`, and `make format` must pass before commit.

## Documentation / config updates

- `SKILL.md`: add a "Download Issues" command entry with an example
  (e.g. "ghpm: download backend issues to CSV") and the script invocation.
- `.claude/settings.local.json`: only if a new permission is required. Expected
  to reuse the existing `gh`/`uv` calls, so likely no change.

## Out of scope

- Filtering options.
- Stdout streaming.
- Markdown or other export formats.
- A `downloads/` subfolder — files land in the current working directory.
