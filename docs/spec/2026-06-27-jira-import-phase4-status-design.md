# Design: Jira import Phase 4 — Status → post-create transition

Date: 2026-06-27
Status: Approved

Parent roadmap: `docs/spec/2026-06-26-jira-import-design.md` (Phase 4).

## Purpose

After issues are created, move each to the Jira status matching its GHPM
`Status` field, using a batched post-create transition pass. Builds on the
per-issue `acli jira workitem create` path (Phase 1) and the mapping module
introduced in Phase 2.

## Verified facts (probed against real Jira, project B14)

- Transition command: `acli jira workitem transition --key "K1,K2" --status "<name>" --yes [--ignore-errors]`.
- B14's workflow statuses all exist and are freely reachable: `To Do, In Progress,
  In Review, Blocked, Done`.
- Newly created issues start in `To Do`.
- `acli jira workitem create --from-json <file> --json` returns the created issue
  resource with a top-level `key`.
- **Indexing lag:** a just-created issue can transiently fail a delete/transition
  by key for a short period after creation ("Issue does not exist or you do not
  have permission"). A batched pass after all creates, plus one retry, mitigates
  this.
- workX `Status` values: `Todo (210), In Review (37), In Progress (19),
  Blocked (7), Done (6)`.

## Mapping

Default GHPM → Jira status map (case-insensitive keys):

| GHPM value  | Jira status  |
|-------------|--------------|
| Todo        | To Do        |
| In Progress | In Progress  |
| In Review   | In Review    |
| Blocked     | Blocked      |
| Done        | Done         |

- Unset/`None` status → skip transition, no warning.
- Mapped value equal to the initial status (`--initial-status`, default `To Do`)
  → skip (new issues already land there; avoids ~210 no-op calls for workX).
- A non-empty value not in the map → skip, warn **once per distinct value**.
- Never fail an import over a status; transition failures are reported, not fatal.

## Changes to `scripts/jira_mapping.py`

- Generalize the existing lookup into `map_value(value: str | None, value_map:
  dict[str, str]) -> str | None` (the current `map_priority` body is already
  generic). Update the two existing call sites (`issue_to_jira`, `main`) to use
  `map_value`; `map_priority` is removed in favor of the generic name.
- Add `DEFAULT_STATUS_MAP: dict[str, str]` (the table above, lowercase keys).
- Add `load_status_map(path: str | None) -> dict[str, str]` — defaults,
  optionally overridden/extended by a JSON object file (mirrors
  `load_priority_map`; raises `GHPMError` on missing/invalid/non-object file).

## Changes to `scripts/acli_client.py`

- `create_issue(issue) -> tuple[int, str | None, str]` — run
  `acli jira workitem create --from-json <file> --json`; on success parse the
  top-level `key` from stdout JSON; return `(returncode, key_or_None,
  combined_output)`. If stdout is not parseable JSON (e.g. failure), `key` is
  `None`. Still raises `GHPMError` when acli is absent.
- `transition_issues(keys: list[str], status: str) -> tuple[int, str]` — run
  `acli jira workitem transition --key "<comma-joined>" --status "<status>"
  --yes --ignore-errors`; return `(returncode, combined_output)`. Raises
  `GHPMError` when acli is absent. (No-op safe to skip if `keys` is empty — the
  caller does not call it with an empty list.)

## Changes to `scripts/to_jira.py`

Status is metadata, not part of the acli create payload (Jira sets status via
workflow), so `issue_to_jira`/`transform` are unchanged.

`main`:

- New flags: `--status-field` (default `Status`), `--status-map-file` (optional),
  `--initial-status` (default `To Do`).
- Load the status map via `load_status_map(parsed.status_map_file)` (GHPMError →
  print + return 1).
- **Pass 1 (create):** iterate `zip(iter_issue_records(export), issues)` so each
  created key is paired with its source record; `create_issue` now returns the
  key. Collect `(record, key)` for successful creates. Per-issue progress and the
  created/failed summary are retained.
- **Pass 2 (transition):** skip entirely if nothing was created. Otherwise:
  - Compute distinct unmapped non-empty status values across created records and
    warn once each (mirrors the priority warning).
  - Build `groups: dict[str, list[str]]` of created key → target status, where
    target = `map_value(record.fields[status_field], status_map)`, skipping when
    target is falsy or equals `parsed.initial_status`.
  - For each `(status, keys)` group, call `transition_issues(keys, status)`; if
    it returns non-zero, call it once more (idempotent retry for indexing lag).
    Print a per-status result line. Transition failures do not change the exit
    code set by the create pass.
- `--dry-run`: in addition to writing the inspection file and skipping create,
  print the **transition plan** — the count of issues that would move to each
  target status, plus counts skipped (initial/unset) and unmapped — and call
  neither `create_issue` nor `transition_issues`.

## Testing (TDD)

`tests/test_jira_mapping.py`:
- `DEFAULT_STATUS_MAP` content; `map_value` generic (identity, case-insensitive,
  None/empty/unknown → None, non-string safe); `load_status_map` defaults +
  merge + error cases.
- Update the former `map_priority` tests to `map_value` (rename).

`tests/test_acli_client.py`:
- `create_issue` returns `(rc, key, output)` with key parsed from `--json` stdout;
  key is None on non-JSON/failed output; command includes `--json`.
- `transition_issues` builds `--key "a,b" --status X --yes --ignore-errors`,
  returns `(rc, output)`; raises `GHPMError` when acli missing.

`tests/test_to_jira.py`:
- Update existing `create_issue` mocks/asserts to the new 3-tuple return.
- Pass 2: created keys are grouped by mapped status and transitioned; targets
  equal to initial status / unset / unmapped are skipped; one warning per
  distinct unmapped status; a status group whose first transition returns
  non-zero is retried exactly once; `--dry-run` prints the plan and calls neither
  `create_issue` nor `transition_issues`.

All acli interaction remains mocked through `scripts.acli_client`.

## Live verification (manual, after implementation)

Import a small slice covering `In Progress`, `Done`, and a `Todo` issue; confirm
via `acli jira workitem view <key> --fields status --json` that mapped statuses
land and the `Todo` one stays `To Do` (no transition). Delete the test issues.

## Out of scope

- Iteration → Sprint (Phase 5).
- Custom fields / `acli jira field create` (Phase 3) and the Phase 3
  "fields-to-create preview + wait" preflight (separately captured).
- Assignee, labels.
- A transition-only/re-run mode (failed transitions are currently re-applied by
  the in-run retry; a standalone re-run mode can be added later if needed).
