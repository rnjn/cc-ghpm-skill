# Design: GHPM export → Jira import via acli (`to_jira.py`)

Date: 2026-06-26
Status: Approved

## Purpose

Import GitHub project issues into Jira from a GHPM JSON export, using Atlassian's
`acli` tool (`acli jira workitem create-bulk --from-json`). The work has two
coupled parts in the ghpm repo:

1. Extend the existing exporter (`download_issues.py`) to include each issue's
   **body**, so it can become the Jira description.
2. A new `to_jira.py` script that transforms a GHPM JSON export into acli's
   bulk-create JSON, writes that file, and — after a confirmation gate —
   invokes `acli`.

## Target format (acli)

`acli jira workitem create-bulk --from-json <file>` expects:

```json
{
  "issues": [
    {
      "summary": "...",
      "projectKey": "PROJ",
      "issueType": "Task",
      "description": { "...ADF..." },
      "label": ["..."],
      "assignee": "user@example.com"
    }
  ]
}
```

`--from-json` is chosen over `--from-csv` because issue bodies are multi-line /
markdown, which CSV handles poorly.

## Part 1 — Extend the exporter

- Add `body` to the Issue fragment in the `get_project_items` GraphQL query in
  `scripts/common.py`. (Only Issues are imported, so PR/draft bodies are not
  needed.)
- Add `body` to the record produced by `item_to_record` in
  `scripts/download_issues.py`.
- `body` surfaces in the **JSON** export only. CSV remains the existing
  core-columns + dynamic-field-columns layout (no `body` column — avoids giant
  multi-line cells). This requires no change to `export_to_csv`, since it writes
  only `CORE_COLUMNS + field_names`.

## Part 2 — `to_jira.py`

### CLI

```bash
uv run python -m scripts.to_jira --input <ghpm-export.json> \
  --jira-project KEY [--type-field Type] [--default-type Task] \
  [--out <file>] [--dry-run] [--yes]
```

- `--input` (required): path to a GHPM JSON export.
- `--jira-project` (required): Jira project key, used as `projectKey`.
- `--type-field` (default `Type`): GHPM field whose value becomes the Jira
  `issueType`.
- `--default-type` (default `Task`): Jira type used when the field is unset.
- `--out`: output path for the acli JSON file. Auto-named
  `<project>-jira-YYYY-MM-DD.json` in the current directory when omitted.
- `--dry-run`: write the acli file, print a summary, and do **not** call acli.
- `--yes`: skip the confirmation prompt and pass `--yes` to acli.

### Field mapping (per Issue → acli issue object)

| acli field      | Source                                                                 |
|-----------------|------------------------------------------------------------------------|
| `summary`       | record `title`                                                         |
| `projectKey`    | `--jira-project`                                                       |
| `issueType`     | value of the GHPM field named by `--type-field`; fall back to `--default-type`. The field value is used directly as the Jira type name. |
| `description`   | ADF document built from `body`, plus a trailing paragraph `Imported from GitHub: <url>` |
| `assignee`      | omitted                                                                |
| `label`         | omitted (v1)                                                           |
| `parentIssueId` | omitted (v1)                                                           |

### Filter

Only records with `type == "Issue"`. PullRequests and draft issues are skipped.

### Flow (`main`)

1. Parse args.
2. Load and parse the GHPM JSON export file.
3. `transform()` → filter to Issues, map each via `issue_to_jira()`.
4. Write `{"issues": [...]}` to the output file.
5. If `--dry-run`: print summary (count, output path) and return 0.
6. Otherwise: verify `acli` is on PATH; print the count; if not `--yes`, prompt
   for confirmation; on confirm run
   `acli jira workitem create-bulk --from-json <file>` (append `--yes` when
   `--yes` was given). Surface acli's stderr on failure; return its exit status.

Assumes the user has already authenticated via `acli jira auth`.

## Components (pure, unit-tested)

In `scripts/to_jira.py`:

- `build_adf_description(body: str, url: str | None) -> dict` — wrap plain text
  body into an ADF `doc` (paragraphs), appended with an "Imported from GitHub"
  paragraph when `url` is present.
- `issue_to_jira(record, *, project_key, type_field, default_type) -> dict` —
  map one GHPM record to one acli issue object.
- `transform(export, *, project_key, type_field, default_type) -> list[dict]` —
  filter the export's `items` to Issues and map each.
- `parse_args(args=None) -> argparse.Namespace`.
- `main(args=None) -> int`.

## Testing (TDD)

- Exporter: a test asserting the items query now requests `body`, and that
  `item_to_record` includes `body`.
- `build_adf_description`: ADF structure for a body with/without URL, and empty
  body.
- `issue_to_jira`: summary/projectKey/issueType mapping; issueType from the
  field vs the default fallback; description wiring.
- `transform`: filters out PRs/drafts; maps all Issues.
- `main`: `--dry-run` writes the file and does **not** invoke acli; the default
  path invokes acli (subprocess mocked) after the confirm gate; acli failure
  returns non-zero. `acli` is mocked via `subprocess.run` (the existing test
  pattern).

`make format`, `make lint`, and `make test` must pass before any commit.

## Known risk / verification step

acli's documented ADF `description` format comes from single `create`. Before a
real bulk import, verify `create-bulk --from-json` accepts an ADF `description`
by importing **one** issue. If acli requires a plain string instead,
`build_adf_description` swaps to returning a string — an isolated change behind
one function.

## Out of scope (v1)

- Labels and parent/sub-task linking.
- Assignee mapping (GitHub login → Jira identity).
- Reading from the CSV export (JSON only).
- acli authentication (assumed already done).
- Status/workflow transitions after creation.
