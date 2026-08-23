# spec-registry

A unified Codex skill that replaces three previously separate tools (spec-registry, universal-task-sync, and workspace.sh) with a single deterministic Python CLI. It covers the full multi-agent collaboration lifecycle:

| Layer | What it solves | Replaces |
|---|---|---|
| **L2: Static Contracts** | Who is changing what, which modules, API contracts, DB entities, dependencies | Original spec-registry |
| **L1: Physical Isolation** | Git worktree lifecycle per Epic; create on attach, destroy after merge | workspace.sh (proposed, never shipped) |
| **L3: Runtime Awareness** | UAS v2.0 heartbeats, concurrent sync, relay handoff, cross-platform watcher | universal-task-sync + fswatch/inotify |

All three layers share one Python CLI, one metadata schema, one set of generated artifacts, and one MCP server for non-Codex tools.

## Architecture

```
.specs/                          # Durable contracts (source of truth)
  ├── SPEC-001.md                #   YAML frontmatter + Markdown detail
  ├── SPEC-TEMPLATE.md           #   Standard template
  ├── registry.json              #   Generated machine-readable index
  └── SPEC-OVERVIEW.md           #   Generated LLM context brief

.sync/                           # Ephemeral heartbeats (runtime bus)
  ├── task-SPEC-001.json         #   UAS v2.0 snapshot per active SPEC
  ├── MERGED_STATE.md            #   Aggregated view for all agents
  └── watcher.pid                #   Cross-platform polling watcher

.worktrees/                      # Transient sandboxes (git-ignored)
  └── epic-order-refactor/       #   One per Epic, reused across SPECs
```

The three layers are connected by design:

- `heartbeat --spec SPEC-001` reads `.specs/registry.json` to populate `spec_id`, `epic`, and `worktree` in the UAS payload.
- `check-scope --spec SPEC-001` validates actual git diff (files/modules) against declared impact_scope. For semantic conflict detection across all four dimensions (modules, files, API endpoints, DB entities), use `check`.
- `finish --epic order-refactor` verifies all Epic SPECs are Completed/Deprecated before destroying the worktree.
- `heartbeats` merges all `.sync/task-*.json` into `MERGED_STATE.md` for parallel agents to read.

## Install

### One-command deploy

Run from any directory. The script downloads this repo, installs to your AI tools skills folder, and verifies.

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/wingontiger/spec-registry/main/install.ps1 | iex
```

macOS / Linux:

```bash
curl -sSL https://raw.githubusercontent.com/wingontiger/spec-registry/main/install.sh | bash
```

Or from a local clone:

```powershell
.\install.ps1
```

```bash
bash install.sh
```

### Manual install

Copy the entire `spec-registry/` folder to:

- Codex: `%USERPROFILE%\.codex\skills\spec-registry` (Windows) or `~/.codex/skills/spec-registry`
- Claude Code: `%USERPROFILE%\.claude\skills\spec-registry` or `~/.claude/skills/spec-registry`

Restart your AI tool after installation.

## Quick Start

```powershell
# 1. Initialize .specs/ in your project root
python <skill-folder>\scripts\spec_registry.py init

# 2. Create a SPEC with impact scope and Epic assignment
python <skill-folder>\scripts\spec_registry.py new `
  --title "Order timeout cancellation" `
  --task-id TASK-A `
  --epic order-refactor `
  --owner "Backend Agent" `
  --summary "Cancel timed-out orders and release inventory." `
  --module services/order `
  --file services/order/service.py

# 3. Check for conflicts before starting implementation
python <skill-folder>\scripts\spec_registry.py check --module services/order

# 4. Enter the Epic worktree
python <skill-folder>\scripts\spec_registry.py attach --spec SPEC-001

# 5. During development, publish heartbeat milestones
python <skill-folder>\scripts\spec_registry.py heartbeat --spec SPEC-001 --focus "Implementing timeout logic" --tool codex

# 6. Verify scope before delivery (soft warning by default)
python <skill-folder>\scripts\spec_registry.py check-scope --spec SPEC-001 --base main --worktree .worktrees\epic-order-refactor

# 7. Hard gate for CI: exit 3 on out-of-scope changes
python <skill-folder>\scripts\spec_registry.py check-scope --spec SPEC-001 --base main --worktree .worktrees\epic-order-refactor --strict

# 8. After merge and completion, clean up
python <skill-folder>\scripts\spec_registry.py finish --epic order-refactor --base main
```

## All Commands

| Command | Purpose | Layer |
|---|---|---|
| `init` | Create `.specs/` directory and initial artifacts | L2 |
| `new` | Create next sequential SPEC with frontmatter | L2 |
| `set-status` | Change SPEC lifecycle status | L2 |
| `sync` | Regenerate registry.json and SPEC-OVERVIEW.md from markdown | L2 |
| `status` | Show concise SPEC ledger | L2 |
| `check` | Compare intended scope against existing SPECs for conflicts | L2 |
| `attach` | Create or reuse Epic worktree; move Draft to In-Progress | L1 |
| `check-scope` | Validate physical file/module changes against declared impact_scope | L2+L1 |
| `finish` | Remove Epic worktree after merge and completion | L1 |
| `worktrees` | List all Epic-to-worktree mappings | L1 |
| `heartbeat` | Publish UAS v2.0 runtime snapshot for an active SPEC | L3 |
| `heartbeats` | List active heartbeats and refresh merged state | L3 |
| `watch` | Cross-platform polling watcher for .sync/ changes | L3 |

## MCP Server (for non-Codex tools)

For Claude Code, Cursor, Windsurf, Google Antigravity, or any MCP-compatible tool:

1. Install the MCP package: `pip install mcp`
2. Register as a stdio server pointing to `scripts/mcp_server.py`

Four atomic tools are exposed:

| MCP Tool | Maps to CLI | Purpose |
|---|---|---|
| `spec_create` | `new` | Create SPEC with impact scope |
| `workspace_attach` | `attach` | Enter Epic worktree |
| `scope_verify` | `check-scope` | Validate diff against scope |
| `state_publish` | `heartbeat` | Publish runtime awareness |

This single server replaces the need for separate universal-task-sync and workspace.sh integrations.

## How This Unifies peer-relay-dev, Worktree, and Multi-task

Previously you needed three tools:

| Old tool | Problem solved | Limitation |
|---|---|---|
| **claude-relay** (Mode A) | Session handoff between Claude Code tasks | Claude Code only; no SPEC awareness |
| **universal-task-sync** (Modes B+C) | Cross-tool file bus with fswatch/inotify | No SPEC validation; Bash-only watcher; no worktree binding |
| **workspace.sh** (proposed) | Epic worktree lifecycle + scope gating | Never actually shipped; Bash-only |

**spec-registry replaces all three** with these key improvements:

1. **SPEC-aware heartbeats**: A heartbeat carries `spec_id`, `epic_id`, and validated `worktree_path`, not just a focus string. Agents know exactly which contract governs the current work.
2. **Lifecycle-gated heartbeats**: Only Draft/In-Progress SPECs can publish. A Completed SPEC cannot send stale signals.
3. **Cross-platform**: Pure Python polling replaces macOS/Linux-only fswatch/inotify.
4. **One CLI, one schema**: All operations go through `spec_registry.py`; no shell script fragmentation across platforms.
5. **Relay mode built in**: Set `--mode relay` on heartbeat to signal handoff. The receiving agent enters the same worktree via `attach`.
6. **MCP bridge**: Non-Codex tools access the same CLI through standardized tool calls rather than raw shell commands.

## Generated Artifacts

- `registry.json`: compact machine-readable index for task startup, automation, and conflict checks.
- `SPEC-OVERVIEW.md`: lightweight context brief for LLM injection (active + recent history).
- `.sync/MERGED_STATE.md`: runtime awareness dashboard aggregated from all active heartbeats.
- Individual `SPEC-*.md` files: durable detailed source of truth.

Commit `.specs/` artifacts with related implementation changes so other tasks inherit the same project state. Add `.sync/` and `.worktrees/` to `.gitignore` unless you want to persist heartbeat history.

