# GHPM - GitHub Projects Manager

A Claude Code skill for managing GitHub Projects via natural language commands.

## Features

- **Move issues** between iterations (e.g., rollover incomplete work to the next sprint)
- **List/filter issues** by missing fields, iteration, status
- **Bulk update** field values across multiple issues
- **View iterations** including completed ones

## Prerequisites

1. [GitHub CLI](https://cli.github.com/) installed and authenticated
2. Project scope enabled: `gh auth refresh -s project`
3. [uv](https://github.com/astral-sh/uv) for running Python scripts

## Installation

### As a Claude Code Skill

```bash
# Clone or symlink to skills directory
ln -s /path/to/ghpm ~/.claude/skills/ghpm

# Copy and configure .env
cp ~/.claude/skills/ghpm/.env.example ~/.claude/skills/ghpm/.env
# Edit .env with your project details
```

### Standalone

```bash
git clone <repo-url> ghpm
cd ghpm
make install
cp .env.example .env
# Edit .env with your project details
```

## Configuration

Edit `.env` to configure your projects:

```bash
# Projects (add as many as needed)
PROJECT_1_OWNER=myorg
PROJECT_1_ID=123
PROJECT_1_NAME=backend

PROJECT_2_OWNER=myorg
PROJECT_2_ID=456
PROJECT_2_NAME=frontend

# Field defaults
DEFAULT_STATUS_FIELD=Status
DEFAULT_ITERATION_FIELD=Iteration
DONE_STATUS=Done
```

Find project IDs with:
```bash
gh project list --owner @me
gh project list --owner <org-name>
```

## Usage

All commands start with `ghpm:` followed by natural language:

### List Issues
```
ghpm: list backend issues missing Priority
ghpm: find issues in current iteration without Product
ghpm: show frontend issues where Status is In Progress
```

### Move Issues
```
ghpm: move open issues from previous to current
ghpm: move items from current to next iteration for backend
```

### Update Issues
```
ghpm: set Priority to P2 for issues 123, 456
ghpm: update backend issues 123, 456 set Product to API
```

### Show Iterations
```
ghpm: show iterations for backend
ghpm: what's the current iteration for frontend?
```

### Show Projects
```
ghpm: show projects
ghpm: list configured projects
```

## Development

```bash
# Install dependencies
make install

# Run tests
make test

# Lint
make lint

# Format
make format
```

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/list_items.py` | List and filter project items |
| `scripts/move_items.py` | Move items between iterations |
| `scripts/update_items.py` | Update field values |
| `scripts/common.py` | Shared utilities (config, GraphQL, etc.) |

## License

MIT
