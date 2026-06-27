# Design: Jira import Phase 2 — Priority field mapping

Date: 2026-06-27
Status: Approved

Parent roadmap: `docs/spec/2026-06-26-jira-import-design.md` (Phase 2).

## Purpose

Carry the GHPM `Priority` field into Jira's standard `priority` field during
import. This is the only standard field that applies to the workX project today
(`Status` → Phase 4 transitions, `Iteration` → Phase 5 sprint, and the GHPM
export carries no GitHub labels). Builds on the per-issue
`acli jira workitem create --from-json` path established in Phase 1.

## Verified facts (probed against real Jira, project B14)

- acli single-create sets priority via
  `additionalAttributes: {"priority": {"name": "<JiraName>"}}`. A top-level
  `priority` key is rejected (`json: unknown field "priority"`).
- B14 uses Jira's default priority scheme: `Highest, High, Medium, Low, Lowest`.
  An invalid name (e.g. `Urgent`) is rejected with "The priority selected is
  invalid", which would fail that issue's creation — so unmappable values must be
  omitted, not passed through.
- workX `Priority` values observed: `Low, High, Medium` (match Jira directly),
  `Urgent` (20), `Postponed` (1), and unset/`None` (25).

## Mapping

Default GHPM → Jira priority map (case-insensitive keys):

| GHPM value | Jira priority |
|------------|---------------|
| Low        | Low           |
| Medium     | Medium        |
| High       | High          |
| Urgent     | Highest       |
| Postponed  | Lowest        |

- Unset / `None` priority → omit (Jira applies its own scheme default); no warning.
- A non-empty value not in the map → omit priority for that issue and warn
  **once per distinct value**. Never fail an issue over priority.

## New module: `scripts/jira_mapping.py`

Keeps field-mapping logic out of `to_jira.py` and sets up later phases.

- `DEFAULT_PRIORITY_MAP: dict[str, str]` — the table above, keyed lowercase.
- `load_priority_map(path: str | None) -> dict[str, str]` — returns
  `DEFAULT_PRIORITY_MAP` when `path` is None; otherwise reads a JSON object
  `{"GHPMValue": "JiraName"}` and merges it over the defaults (override + extend),
  lowercasing keys. Raises `GHPMError` on a missing/invalid file.
- `map_priority(value: str | None, value_map: dict[str, str]) -> str | None` —
  returns the Jira priority name, or `None` when `value` is falsy or not present
  in `value_map` (case-insensitive lookup).

## Changes to `scripts/to_jira.py`

- `issue_to_jira(record, *, project_key, type_field, default_type, priority_field,
  priority_map)` — unchanged for summary/projectKey/type/description; additionally,
  if `map_priority(record["fields"].get(priority_field), priority_map)` returns a
  name, add `"additionalAttributes": {"priority": {"name": <name>}}` to the issue
  object. If it returns `None`, omit `additionalAttributes` entirely.
- `transform(...)` gains the same `priority_field` / `priority_map` params and
  forwards them to `issue_to_jira`.
- A small helper exposes the filtered Issue records so `main` can compute unmapped
  warnings without duplicating the `type == "Issue"` filter
  (e.g. `iter_issue_records(export) -> list[dict]`, used by both `transform` and
  the warning step).
- `main`:
  - New flags: `--priority-field` (default `Priority`) and `--priority-map-file`
    (optional path).
  - Load the priority map via `load_priority_map(parsed.priority_map_file)`.
  - After transform, compute the set of distinct non-empty priority values that
    map to `None` and print one warning per value to `err_console`.
  - Pass `priority_field` / `priority_map` through to `transform`.
  - Everything else (write inspection file, dry-run, confirm-gate, per-issue
    create loop, created/failed summary) is unchanged from Phase 1.

The written inspection file now includes `additionalAttributes` for issues that
have a mapped priority, so `--dry-run` shows exactly what will be sent.

## Testing (TDD)

Unit:
- `map_priority`: identity for Low/Medium/High; `Urgent→Highest`; `Postponed→Lowest`;
  `None`/empty → None; unknown value → None; case-insensitive lookup.
- `load_priority_map`: None path → defaults; override file merges over defaults
  (override an existing key + add a new one); missing/invalid file → `GHPMError`.
- `issue_to_jira`: adds `additionalAttributes.priority.name` when mapped; omits
  `additionalAttributes` when priority is unset or unmapped; respects a custom
  `priority_field`.
- `main`: warns once per distinct unmapped value (assert via captured stderr);
  the written file contains the expected `additionalAttributes.priority` for a
  mapped issue and none for an unmapped/unset one.

All `acli` interaction remains mocked through `scripts.acli_client`.

## Live verification (manual, after implementation)

Import a small slice of workX issues covering `High`, `Urgent`, and an unset
priority; confirm via `acli jira workitem view <key> --fields priority --json`
that `High→High` and `Urgent→Highest`, and that the unset one has Jira's default.
Delete the test issues afterward.

## Out of scope (later phases)

- Status (Phase 4 transitions), Iteration → Sprint (Phase 5).
- Labels, assignee.
- Custom fields / `acli jira field create` (Phase 3).
- A `--no-priority` opt-out (can be added later if needed).
