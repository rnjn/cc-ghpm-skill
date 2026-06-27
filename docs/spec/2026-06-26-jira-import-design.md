# Design: GHPM export → Jira import via acli (roadmap)

Date: 2026-06-26
Status: Approved (roadmap); implement incrementally, one phase at a time

## Purpose

Import GitHub project issues into Jira from a GHPM JSON export, using Atlassian's
`acli`. Beyond basic title/description, carry over GHPM fields: map standard
fields to Jira built-ins, auto-create Jira custom fields for the rest, and set
Jira status via a post-create transition.

This is a **phased roadmap**. Phase 1 is specified in implementation-ready
detail; later phases are specified enough to guide architecture and will be
refined (and re-validated against real Jira) before each is built. We implement
one phase at a time with a review checkpoint between phases.

## Architecture overview

New/changed code in the ghpm repo (Python, same tooling):

- `scripts/common.py` — add `body` to the items GraphQL query (Phase 1).
- `scripts/download_issues.py` — add `body` to each record (Phase 1).
- `scripts/acli_client.py` — thin wrapper around `acli` subprocess calls
  (`create_issue`, later `field_create`, `transition`). One place to mock in
  tests. Introduced in Phase 1, extended later.
- `scripts/to_jira.py` — the importer: load a GHPM JSON export, transform,
  write the acli input file, confirm-gate, invoke acli. Grows across phases.
- `scripts/jira_mapping.py` — field classification + value transforms. Split out
  of `to_jira.py` when it appears in Phase 2 (keeps `to_jira.py` focused).

### Create strategy

- Phase 1 uses per-issue `acli jira workitem create --from-json`, one acli call
  per issue, continuing past individual failures and reporting a created/failed
  summary.
- **Why not `create-bulk`:** verified during Phase 1 testing that `create-bulk
  --from-json` cannot carry an ADF `description` — it stringifies the object
  (stored as a `map[...]` dump) and rejects any plain-string description
  containing a newline. Per-issue `create` accepts the ADF object and renders
  multi-paragraph descriptions correctly. The per-issue path is also the
  direction later phases need anyway (custom-field `additionalAttributes` and
  per-issue transitions are single-create only).
- Trade-off accepted: per-issue is N API calls (slower for large imports) in
  exchange for correct, readable descriptions.

> Note: the per-issue payload uses the key `type` (not `issueType`, which is the
> `create-bulk` spelling).

### acli target formats (verified via `acli ... --generate-json`)

- Bulk: `{"issues": [{summary, projectKey, issueType, label[], assignee}]}`.
- Single create: also supports `description` (ADF), `additionalAttributes`
  (`customfield_xxxxx` → value), `reporter`, `parentIssueId`.
- `acli jira field create --name --type --searcher-key [--json]` creates a custom
  field; `--json` returns the new field id.
- `acli jira workitem transition` moves an issue to a target status.

## Cross-cutting design

- **Field classification (auto by name/type).** For each GHPM project field
  (from `get_project_fields`):
  - `Title` → `summary`; the configured type field (default `Type`) →
    `issueType`; `Status` → handled by transition (Phase 4).
  - `Priority` → Jira `priority` (Phase 2), via a value-transform map.
  - `Iteration` → Sprint (Phase 5).
  - Anything else → a Jira **custom field** (Phase 3), typed from the GHPM field
    kind: single-select → `select`, text → `textfield`, date → `datepicker`,
    iteration → `textfield` (until Phase 5).
- **Value transforms.** Small configurable maps (e.g. `P0→Highest, P1→High`).
  Unmapped values pass through unchanged with a warning.
- **Idempotent field-id map.** A project-scoped JSON file (e.g.
  `<project>-jira-fields.json`) recording GHPM field name → `{id, type}`. On run,
  existing entries are reused; only missing fields are created and appended.
  Risk: acli has no `field list`, so a lost map file can cause duplicate field
  creation — documented, and re-runs warn before creating.
- **Assignee** is omitted in all phases (GitHub login ≠ Jira identity).
- **Filter:** only records with `type == "Issue"` (PRs/drafts skipped) in all
  phases.

---

## Phase 1 — Core import (foundation)

**Goal:** working import of basic issues, end-to-end against real Jira.

### Exporter change

- Add `body` to the Issue fragment of the `get_project_items` query in
  `common.py` (Issues only; PR/draft bodies not needed).
- Add `body` to `item_to_record`. `body` appears in the **JSON** export only;
  CSV is unchanged (writes `CORE_COLUMNS + field_names`).

### `to_jira.py` (Phase 1 surface)

CLI:
```bash
uv run python -m scripts.to_jira --input <ghpm-export.json> \
  --jira-project KEY [--type-field Type] [--default-type Task] \
  [--out <file>] [--dry-run] [--yes]
```

Mapping (per Issue → acli issue object):

| acli field    | Source                                                              |
|---------------|--------------------------------------------------------------------|
| `summary`     | record `title`                                                     |
| `projectKey`  | `--jira-project`                                                   |
| `type`        | value of the `--type-field` field; fall back to `--default-type`    |
| `description` | ADF doc from `body`, plus a trailing `Imported from GitHub: <url>` |

Flow (`main`):
1. Parse args; load + parse the GHPM JSON export.
2. `transform()` → filter to Issues, map each via `issue_to_jira()`.
3. Short-circuit to a clean message + return 0 if there are no Issues.
4. Write `{"issues": [...]}` to the output file as an inspection artifact
   (auto-named `<project>-jira-YYYY-MM-DD.json` in cwd when `--out` omitted).
5. `--dry-run`: print summary (count, path); return 0.
6. Otherwise: verify `acli` on PATH; prompt unless `--yes`; then create each
   issue with `acli jira workitem create --from-json` (one temp file per issue),
   continuing past failures, printing per-issue progress and a final
   `created/failed` summary. Return 0 if all succeeded, non-zero if any failed.

Components (pure, unit-tested): `build_adf_description(body, url)`,
`issue_to_jira(record, *, project_key, type_field, default_type)`,
`transform(export, ...)`, `parse_args`, `main`. `acli_client.create_issue(issue)
-> (rc, output)` wraps the per-issue subprocess call.

**Phase 1 verification (manual) — completed:** confirmed against real Jira
(project B14) that per-issue `create` renders the ADF `description` correctly
(multi-paragraph body + URL footer). `create-bulk` was rejected for this purpose
(see Create strategy above).

---

## Phase 2 — Standard field mapping

**Goal:** carry standard fields to Jira built-ins.

- `jira_mapping.py`: classify fields; map `Priority` → `priority` with a
  value-transform map (`--priority-map` or a config file). Optionally GHPM
  values → `label`s.
- Determine whether `priority` is settable via bulk; if not, move issue creation
  to per-issue `create --from-json` (carrying `additionalAttributes`/standard
  fields). Document the switch.
- Tests: priority mapping incl. value transform and unmapped-value warning.
- Verification: import a few issues; confirm priority lands correctly.

---

## Phase 3 — Custom field provisioning + values

**Goal:** create Jira custom fields for unmapped GHPM fields and populate them.

- Discover unmapped fields; for each, look up the idempotent field-id map; if
  absent, `acli jira field create` (type from GHPM kind), capture the id
  (`--json`), append to the map file.
- Build per-issue payloads with `additionalAttributes` (`customfield_id` →
  value) and create per-issue.
- Handle/document the **post-create setup gap**: a newly created custom field
  usually must be added to the project's screens, and single-select fields need
  their **options/context** configured, before values apply. If acli can't do
  this, the tool detects/values-fail and emits clear manual-setup instructions;
  re-running after setup is safe (idempotent map).
- Tests: classification, field-create invocation + id capture (mocked), payload
  assembly, idempotent reuse.
- Verification: dry provision, then one issue, then bulk.

---

## Phase 4 — Status transition

**Goal:** move imported issues into the Jira status matching GHPM `Status`.

- After create, `acli jira workitem transition` per issue to a target status
  resolved from a status-name map (GHPM value → Jira status; `--status-map` or
  config). Unmatched values are skipped with a warning.
- Requires capturing each created issue key from the create step.
- Tests: status resolution + unmatched handling; transition invocation (mocked).
- Verification: confirm issues land in the right status.

---

## Phase 5 (optional) — Iteration → Sprint

**Goal:** map GHPM `Iteration` to a Jira Sprint.

- Resolve/locate sprints via `acli jira sprint`; set the sprint custom field.
  Sprints must exist on the relevant board. Most complex; deferred and optional.

---

## Known risks / constraints

- **Status not settable at create** → handled by Phase 4 transitions.
- **Custom-field creation is admin + needs screen/context/option setup** → Phase
  3 detects and documents the manual step; idempotent re-run.
- **Bulk create can't carry custom/most non-basic fields** → switch to per-issue
  create from Phase 2/3.
- **No `acli field list`** → idempotency relies on the local field-id map file;
  losing it risks duplicate fields (warned).
- **ADF vs plain `description`** → verified in Phase 1 on one issue.

## Testing approach

Pure transform/mapping functions are unit-tested. All `acli` interaction goes
through `acli_client.py` and is mocked via `subprocess.run` (existing pattern).
Each phase has a manual real-Jira verification step because field creation,
workflows, and bulk-field support can only be confirmed live. `make format`,
`make lint`, `make test` must pass before each commit.

## Out of scope

- Assignee mapping (GitHub login → Jira identity).
- Reading from the CSV export (JSON only).
- acli authentication (assumed done via `acli jira auth`).
- Two-way sync / updates to already-imported issues (create-only).
