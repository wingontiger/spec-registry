# spec-registry

Multi-task SPEC lifecycle governance for parallel agent development.

Maintains a shared `.specs/` ledger so every task and agent can discover what
others are changing, detect conflicts before implementation, and use isolated
Epic worktrees for physical separation.

## What it fixes (vs v1)

| Issue | v1 | v2 (this) |
|---|---|---|
| `check-scope` kills MCP server | `sys.exit()` propagated | handlers return `int`; `main()` owns `sys.exit` |
| worktree SPEC copy has stale status | copy before status update | status update first, then copy |
| same-Epic file conflicts silently allowed | no check in `attach` | `attach` rejects overlapping `scope_files` |
| `blocks`/`depends_on` asymmetry invisible | not checked | `sync` emits WARNING |
| no per-task filtering | global view only | `--task-id` on `status` and `check` |
| relay mixed into heartbeat | single `heartbeat --mode relay` | relay delegated to **peer-relay-v3** |

## Architecture

```
.specs/              L2 static contracts  (source of truth, committed to Git)
  SPEC-NNN.md          individual SPEC with YAML frontmatter
  registry.json        generated machine-readable index
  SPEC-OVERVIEW.md     generated LLM context brief

.worktrees/          L1 physical sandboxes (gitignored, transient)
  epic-<slug>/         one per Epic, reused across SPECs

.sync/               L3 concurrent heartbeats (managed by peer-relay-v3)
```

## Install

```bash
# Claude Code / Codex global skills
cp -r spec-registry/ ~/.claude/skills/

# MCP server (optional, for Claude Code / Cursor / Windsurf)
pip install mcp
```

Register MCP server:
```json
{
  "mcpServers": {
    "spec-registry": {
      "command": "python",
      "args": ["~/.claude/skills/spec-registry/scripts/mcp_server.py"]
    }
  }
}
```

## Quick Start

```bash
# 1. Initialize .specs/
python spec_registry.py init

# 2. Check for conflicts before creating a SPEC
python spec_registry.py check --module services/auth --task-id TASK-A

# 3. Create SPEC
python spec_registry.py new \
  --title "JWT authentication" \
  --task-id TASK-A --epic auth-refactor \
  --owner "Agent A" --summary "Add JWT middleware" \
  --module services/auth --file services/auth/handler.py

# 4. Enter isolated worktree
python spec_registry.py attach --spec SPEC-001

# 5. Check scope during development (soft warning)
python spec_registry.py check-scope --spec SPEC-001 --base main

# 6. Strict gate for CI (exit 3 on violations)
python spec_registry.py check-scope --spec SPEC-001 --base main --strict

# 7. Mark complete and clean up
python spec_registry.py set-status --id SPEC-001 --status Completed
python spec_registry.py sync
python spec_registry.py finish --epic auth-refactor --base main
```

## SPEC File Format

```markdown
---
id: SPEC-001
title: "JWT authentication middleware"
task_id: "TASK-A"
epic_id: "auth-refactor"
status: "Draft"
owner: "Agent A"
created_at: "2026-08-24"
updated_at: "2026-08-24"
depends_on: []
blocks: []
impact_scope:
  modules:
    - "services/auth"
  files:
    - "services/auth/handler.py"
  api_endpoints:
    - "POST /api/v1/auth/login"
  db_entities: []
summary: "Add JWT middleware with refresh token support"
breaking_changes: false
---
```

**File naming**: `SPEC-NNN.md` only (e.g. `SPEC-001.md`). Slug-named files like
`SPEC-001-auth.md` are silently skipped by the scanner.

## All Commands

| Command | Purpose |
|---|---|
| `init` | Create `.specs/` and initial generated artifacts |
| `new` | Create next sequential SPEC |
| `set-status` | Change SPEC lifecycle status |
| `sync` | Regenerate `registry.json` and `SPEC-OVERVIEW.md` |
| `status [--task-id T]` | Show SPEC ledger, optionally filtered by task |
| `check [--task-id T]` | Conflict check against active SPECs |
| `attach` | Create/reuse Epic worktree; Draft→In-Progress |
| `check-scope [--strict]` | Validate git diff against declared scope |
| `finish` | Remove Epic worktree after all SPECs merged |
| `worktrees` | Show Epic-to-worktree mapping |
| `heartbeat` | Publish lightweight concurrent awareness signal |
| `heartbeats` | List active heartbeats |
| `watch` | Cross-platform `.sync/` polling watcher |

## MCP Tools

| Tool | Maps to |
|---|---|
| `spec_create` | `new` |
| `workspace_attach` | `attach` |
| `scope_verify` | `check-scope` |
| `state_publish` | `heartbeat` |

## Relay Handoff

For context relay between agents, use the companion **peer-relay-v3** skill.
spec-registry's `heartbeat` command is for concurrent awareness only.

## .gitignore

```
.sync/
.worktrees/
```

Commit `.specs/` with implementation changes so other tasks inherit the same state.
