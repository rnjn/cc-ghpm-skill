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
uv run python scripts/list_items.py --project <name> [--missing-field <field>] [--iteration <iter>] [--status <status>] [--open-only]
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
uv run python scripts/update_items.py --project <name> --items <nums> --field <field> --value <value> [--yes]
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
