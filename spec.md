# GHPM - GitHub Projects Manager Skill

## Overview

A Claude Code skill for managing GitHub Projects via natural language commands. The skill provides scripts for bulk operations on project items, focusing on iteration management and field auditing.

## Problem Statement

Managing GitHub Projects involves repetitive manual tasks:
1. Every Monday, moving incomplete issues from the previous iteration to the current iteration
2. Finding issues with missing field values (e.g., Priority, Product)
3. Bulk updating fields across multiple issues

This skill automates these workflows through natural language commands interpreted by Claude Code.

---

## Installation

### Location
```
~/.claude/skills/ghpm/
├── SKILL.md              # Claude Code skill instructions
├── .env                  # Project configuration
├── pyproject.toml        # Python dependencies
└── scripts/
    ├── move_items.py     # Bulk move between iterations
    ├── list_items.py     # Find issues with filters
    └── update_items.py   # Set field values
```

Can be symlinked from a separate repository:
```bash
ln -s /path/to/ghpm-repo ~/.claude/skills/ghpm
```

### Dependencies
- Python 3.x
- `uv` for running scripts
- `gh` CLI (authenticated)

Python packages:
- `python-dotenv` — load `.env` configuration
- `rich` — formatted table output

### Prerequisites
1. GitHub CLI installed and authenticated (`gh auth login`)
2. `project` scope enabled (`gh auth refresh -s project`)
3. `uv` installed for running Python scripts

---

## Configuration

### `.env` File

```bash
# ===================
# Projects
# ===================
# Format: PROJECT_<N>_OWNER, PROJECT_<N>_ID, PROJECT_<N>_NAME
# NAME is a short alias for natural language reference

PROJECT_1_OWNER=myorg
PROJECT_1_ID=123
PROJECT_1_NAME=backend

PROJECT_2_OWNER=myorg
PROJECT_2_ID=456
PROJECT_2_NAME=frontend

PROJECT_3_OWNER=myorg
PROJECT_3_ID=789
PROJECT_3_NAME=mobile

PROJECT_4_OWNER=myuser
PROJECT_4_ID=101
PROJECT_4_NAME=personal

# ===================
# Field Defaults
# ===================
# These can be overridden per-command

DEFAULT_STATUS_FIELD=Status
DEFAULT_ITERATION_FIELD=Iteration
DONE_STATUS=Done
```

### Finding Project IDs

Use the GitHub CLI to find project IDs:
```bash
# List projects for a user
gh project list --owner @me

# List projects for an organization
gh project list --owner myorg
```

---

## Invocation

### Trigger Pattern
All commands start with `ghpm:` followed by natural language:

```
ghpm: <natural language command>
```

### Supported Intents

| Intent | Example Phrases |
|--------|-----------------|
| Move issues | "move open issues from previous to current" |
| | "move items from current to next iteration" |
| | "move open issues to current iteration for backend" |
| List/find issues | "list backend issues missing Priority" |
| | "find issues in current iteration without Product" |
| | "show frontend issues where Estimate is not set" |
| Update issues | "set Priority to P2 for issues 123, 456" |
| | "update those issues, set Product to API" |
| Show iterations | "show iterations for backend" |
| | "what's the current iteration for frontend?" |
| List projects | "show projects" |
| | "list configured projects" |

---

## Scripts Specification

### Common Behavior

All scripts:
1. Auto-detect `.env` from script directory
2. Check `gh auth status` before running; prompt user if not authenticated
3. Use `gh api graphql` for GitHub API calls
4. Output formatted tables via `rich`
5. Exit with non-zero code on failure

### 1. `move_items.py`

Move open issues between iterations.

#### Usage
```bash
uv run python scripts/move_items.py \
  --from-iteration <previous|current|next> \
  --to-iteration <previous|current|next> \
  [--project <name>] \
  [--dry-run]
```

#### Arguments
| Argument | Required | Description |
|----------|----------|-------------|
| `--from-iteration` | Yes | Source iteration: `previous`, `current`, or `next` |
| `--to-iteration` | Yes | Target iteration: `previous`, `current`, or `next` |
| `--project` | No | Project short name (from `.env`). If omitted, runs on all projects |
| `--dry-run` | No | Preview changes without executing |

#### Behavior
1. Resolve iteration keywords to actual iteration IDs via GraphQL
2. Fetch items in source iteration where:
   - Issue is **open** (not closed)
   - Status is **not "Done"**
3. Display summary: "Found X items to move in project Y"
4. If `--dry-run`: show what would be moved, exit
5. Otherwise: move items and show summary per project
6. On error: ask user whether to retry or skip to next project

#### Output
```
Project: backend
  Found 5 items to move from "Iteration 3" → "Iteration 4"

Project: frontend
  Found 3 items to move from "Iteration 3" → "Iteration 4"

Total: 8 items moved across 2 projects
```

Dry-run output:
```
[DRY RUN] Project: backend
  Would move 5 items from "Iteration 3" → "Iteration 4":
    #123  Fix login bug
    #124  Update navbar
    #130  Refactor auth
    #145  Add caching
    #152  Write tests

[DRY RUN] No changes made.
```

---

### 2. `list_items.py`

Find issues with filters (missing fields, iteration, status, etc.).

#### Usage
```bash
uv run python scripts/list_items.py \
  --project <name> \
  [--missing-field <field_name>] \
  [--iteration <previous|current|next>] \
  [--status <status_value>] \
  [--open-only]
```

#### Arguments
| Argument | Required | Description |
|----------|----------|-------------|
| `--project` | Yes | Project short name (from `.env`) |
| `--missing-field` | No | Find issues where this field is not set |
| `--iteration` | No | Filter by iteration: `previous`, `current`, `next`, or exact name |
| `--status` | No | Filter by status value |
| `--open-only` | No | Only show open issues (default: false) |

#### Behavior
1. Fetch project's field definitions (dynamic discovery)
2. Validate that specified fields exist
3. Fetch items matching filters
4. Display compact table with issue numbers

#### Output
```
Project: backend | Filter: missing "Priority" | Iteration: current

  #     Title                    Status         Priority
 ─────────────────────────────────────────────────────────
  123   Fix login bug            In Progress    (empty)
  456   Add dark mode            Todo           (empty)
  789   Update API docs          In Review      (empty)

Found 3 issues
```

---

### 3. `update_items.py`

Set field values on specified issues.

#### Usage
```bash
uv run python scripts/update_items.py \
  --project <name> \
  --items <issue_numbers> \
  --field <field_name> \
  --value <field_value>
```

#### Arguments
| Argument | Required | Description |
|----------|----------|-------------|
| `--project` | Yes | Project short name (from `.env`) |
| `--items` | Yes | Comma-separated issue numbers (e.g., `123,456,789`) |
| `--field` | Yes | Field name to update |
| `--value` | Yes | Value to set |

#### Behavior
1. Fetch project's field definitions
2. Validate field exists and value is valid (for enum fields)
3. Resolve issue numbers to project item IDs
4. Display confirmation prompt:
   ```
   About to update 3 issues:
     #123  Fix login bug
     #456  Add dark mode
     #789  Update API docs
   
   Set "Priority" = "P2"
   
   Proceed? [y/N]
   ```
5. On confirmation: update items, show results
6. On error: report which items failed, ask to retry

#### Output
```
Updated 3 issues:
  #123  Fix login bug            Priority: P2 ✓
  #456  Add dark mode            Priority: P2 ✓
  #789  Update API docs          Priority: P2 ✓
```

---

## SKILL.md Content

```markdown
# GHPM - GitHub Projects Manager

## Trigger
Activate this skill when user message starts with `ghpm:`.

## Configuration
- Config location: `~/.claude/skills/ghpm/.env`
- Scripts location: `~/.claude/skills/ghpm/scripts/`

## Available Commands

### Move Issues
**Intent**: Move open issues between iterations
**Script**: `move_items.py`
**Example invocations**:
- "ghpm: move open issues from previous to current"
- "ghpm: move items to current iteration for backend"

**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python scripts/move_items.py --from-iteration <from> --to-iteration <to> [--project <name>] [--dry-run]
```

### List Issues
**Intent**: Find issues with filters
**Script**: `list_items.py`
**Example invocations**:
- "ghpm: list backend issues missing Priority"
- "ghpm: find frontend issues in current iteration"

**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python scripts/list_items.py --project <name> [--missing-field <field>] [--iteration <iter>]
```

### Update Issues
**Intent**: Set field values on issues
**Script**: `update_items.py`
**Example invocations**:
- "ghpm: set Priority to P2 for issues 123, 456"
- "ghpm: update backend issues 123, 456 set Product to API"

**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python scripts/update_items.py --project <name> --items <nums> --field <field> --value <value>
```

### Show Iterations
**Intent**: Display iteration info for a project
**Example invocations**:
- "ghpm: show iterations for backend"
- "ghpm: what's the current iteration?"

**Execution**:
```bash
cd ~/.claude/skills/ghpm
uv run python scripts/list_items.py --project <name> --show-iterations
```

### List Projects
**Intent**: Show configured projects
**Example invocations**:
- "ghpm: show projects"
- "ghpm: list configured projects"

**Execution**: Read `.env` and display project names and IDs.

## Workflow Guidelines

1. **For move operations**: Always offer `--dry-run` first if user hasn't specified
2. **For updates**: Always run `list_items.py` first to show what will be affected, then confirm before running `update_items.py`
3. **On errors**: Report the error clearly and ask if user wants to retry
4. **Field names**: Fetch dynamically from project; don't assume field names exist

## Error Handling

If `gh auth status` fails:
- Tell user: "GitHub CLI not authenticated. Run `gh auth login` then `gh auth refresh -s project`"

If project name not found:
- List available projects from `.env`

If field name not found:
- List available fields for that project
```

---

## GraphQL Queries Reference

### Fetch Project's Fields
```graphql
query($projectId: ID!) {
  node(id: $projectId) {
    ... on ProjectV2 {
      fields(first: 50) {
        nodes {
          ... on ProjectV2Field {
            id
            name
            dataType
          }
          ... on ProjectV2IterationField {
            id
            name
            configuration {
              iterations {
                id
                title
                startDate
                duration
              }
            }
          }
          ... on ProjectV2SingleSelectField {
            id
            name
            options {
              id
              name
            }
          }
        }
      }
    }
  }
}
```

### Fetch Project Items
```graphql
query($projectId: ID!, $cursor: String) {
  node(id: $projectId) {
    ... on ProjectV2 {
      items(first: 100, after: $cursor) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          content {
            ... on Issue {
              number
              title
              state
              url
            }
            ... on PullRequest {
              number
              title
              state
              url
            }
          }
          fieldValues(first: 20) {
            nodes {
              ... on ProjectV2ItemFieldTextValue {
                field { ... on ProjectV2Field { name } }
                text
              }
              ... on ProjectV2ItemFieldSingleSelectValue {
                field { ... on ProjectV2SingleSelectField { name } }
                name
              }
              ... on ProjectV2ItemFieldIterationValue {
                field { ... on ProjectV2IterationField { name } }
                iterationId
                title
              }
            }
          }
        }
      }
    }
  }
}
```

### Update Item Field
```graphql
mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: ProjectV2FieldValue!) {
  updateProjectV2ItemFieldValue(input: {
    projectId: $projectId
    itemId: $itemId
    fieldId: $fieldId
    value: $value
  }) {
    projectV2Item {
      id
    }
  }
}
```

---

## File Structure

```
~/.claude/skills/ghpm/
├── SKILL.md                      # Claude Code instructions
├── .env                          # Project configuration
├── .env.example                  # Template for .env
├── pyproject.toml                # Python project config
└── scripts/
    ├── __init__.py
    ├── common.py                 # Shared utilities (auth check, config loading, GraphQL)
    ├── move_items.py             # Move issues between iterations
    ├── list_items.py             # List/filter issues
    └── update_items.py           # Update field values
```

### `pyproject.toml`
```toml
[project]
name = "ghpm"
version = "0.1.0"
description = "GitHub Projects Manager - Claude Code Skill"
requires-python = ">=3.10"
dependencies = [
    "python-dotenv",
    "rich",
]

[tool.uv]
dev-dependencies = []
```

### `.env.example`
```bash
# Projects (add as many as needed)
PROJECT_1_OWNER=your-org
PROJECT_1_ID=1
PROJECT_1_NAME=myproject

# Field defaults
DEFAULT_STATUS_FIELD=Status
DEFAULT_ITERATION_FIELD=Iteration
DONE_STATUS=Done
```

---

## Example Workflows

### Monday Iteration Rollover
```
User: ghpm: move open issues from previous to current

Claude: Running move with --dry-run first...

[DRY RUN] Project: backend
  Would move 5 items from "Iteration 3" → "Iteration 4"

[DRY RUN] Project: frontend  
  Would move 3 items from "Iteration 3" → "Iteration 4"

Proceed with moving 8 items across 2 projects? [y/N]

User: y

Claude: Done! Moved 8 items:
  - backend: 5 items
  - frontend: 3 items
```

### Audit Missing Fields
```
User: ghpm: list backend issues missing Priority

Claude: 
Project: backend | Filter: missing "Priority" | Iteration: all

  #     Title                    Status         Priority
 ─────────────────────────────────────────────────────────
  123   Fix login bug            In Progress    (empty)
  456   Add dark mode            Todo           (empty)
  789   Update API docs          In Review      (empty)

Found 3 issues. Would you like to update them?

User: ghpm: set Priority to P2 for those issues

Claude:
About to update 3 issues:
  #123  Fix login bug
  #456  Add dark mode  
  #789  Update API docs

Set "Priority" = "P2"

Proceed? [y/N]

User: y

Claude:
Updated 3 issues:
  #123  Fix login bug            Priority: P2 ✓
  #456  Add dark mode            Priority: P2 ✓
  #789  Update API docs          Priority: P2 ✓
```

---

## Future Enhancements (Post-V1)

- Create new iterations
- Archive completed iterations
- Bulk add issues to a project
- Custom filters (assignee, labels, date ranges)
- Scheduled automation (cron-style)
- Multi-field updates in single command
- Export to CSV/JSON