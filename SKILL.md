---
name: spec-registry
description: Manage shared SPEC lifecycle awareness across multiple Codex tasks in one repository by maintaining .specs metadata, a registry, an overview, and impact-scope conflict checks.
metadata:
  short-description: Coordinate SPECs across parallel tasks
---

# Spec Registry

Use this skill when several Codex tasks work in the same repository and each task issues SPECs. Keep the ledger in the repository so every task can discover what other tasks have issued, completed, deprecated, or is actively changing.

The canonical layout is `<repo-root>/.specs/`:

- `SPEC-*.md`: human-readable specification with YAML frontmatter and detail sections.
- `registry.json`: generated machine-readable index; regenerate it after lifecycle changes rather than hand-editing it.
- `SPEC-OVERVIEW.md`: generated short context brief; keep this lightweight enough for task startup injection.

When Git worktrees are used, group related SPECs under one `epic_id` and reuse one worktree per Epic. Worktrees are transient execution sandboxes; SPEC files are the durable project ledger.

## Required Workflow

1. At task start, read `.specs/registry.json` if present. Regenerate it first when it is stale, missing, or disagrees with `SPEC-*.md`.
2. Check for relay handoffs: run `heartbeats` to read `.sync/MERGED_STATE.md`. If a `mode: relay` heartbeat exists for a SPEC in your scope, run `attach --spec <id>` before making any changes to reuse the same worktree. Then publish your own heartbeat with `--mode concurrent` to signal you have taken over.
3. Before issuing a new SPEC, compare intended modules, files, API endpoints, and database entities with active specs using the conflict checker.
4. Create every new SPEC through the CLI so IDs remain sequential and frontmatter follows the schema.
5. Update status as work progresses (`Draft`, `In-Progress`, `Completed`, `Deprecated`) and refresh generated artifacts after every lifecycle change.
6. When implementation needs physical isolation, run `attach --spec <id>` instead of creating branches or worktrees manually. Edit only inside the returned `.worktrees/epic-<epic_id>` directory.
7. During development, run `check-scope` for nonblocking warnings when files fall outside `impact_scope`. Note that `check-scope` validates physical files/modules against git diff; it does not detect API contract or database entity drift — use `check` for that (semantic four-dimension conflict detection).
8. Before final delivery, refresh the registry and run the conflict check against actual changed paths. Resolve real overlaps through dependencies, a revised SPEC, or an explicit note explaining why coexistence is safe.
9. After review passes and every SPEC assigned to an Epic is merged and marked Completed or Deprecated, run `finish --epic <id>` with the correct base branch to remove the worktree. Never delete `.specs/` history.

Run the bundled tool from the target repository root:

```powershell
python <skill-folder>\scripts\spec_registry.py init
python <skill-folder>\scripts\spec_registry.py new --title "Short title" --task-id TASK-A --epic order-refactor --owner "Task A" --summary "Purpose." --module services/order --file services/order/handler.py
python <skill-folder>\scripts\spec_registry.py set-status --id SPEC-001 --status Completed
python <skill-folder>\scripts\spec_registry.py sync
python <skill-folder>\scripts\spec_registry.py check --file services/order/handler.py
python <skill-folder>\scripts\spec_registry.py status --format json
python <skill-folder>\scripts\spec_registry.py attach --spec SPEC-001
python <skill-folder>\scripts\spec_registry.py check-scope --spec SPEC-001 --base main
python <skill-folder>\scripts\spec_registry.py finish --epic order-refactor --base main
python <skill-folder>\scripts\spec_registry.py worktrees
python <skill-folder>\scripts\spec_registry.py heartbeat --spec SPEC-001 --focus "Implementing token interceptor" --tool codex --model stealth-ox-alpha
python <skill-folder>\scripts\spec_registry.py heartbeats
python <skill-folder>\scripts\spec_registry.py watch --interval 5
```

## Interpretation Rules

- Treat `In-Progress` impact scopes as claims of intent, not proof of exclusive ownership. Surface conflicts early instead of silently overwriting another task's direction.
- Treat `Completed` scopes as the current baseline; open the relevant detailed SPEC when it affects the same contract or data model.
- Treat `Deprecated` scopes as historical context; do not inherit their contracts without checking whether a replacement exists.
- Prefer module-level declarations for broad work, then add exact files and entities when they materially improve conflict detection.
- If metadata and prose disagree, stop and correct metadata before implementation.
- Reuse one Epic worktree for related small fixes; create a new Epic only for genuinely independent parallel streams. Do not create a permanent worktree per SPEC.
- Treat development-time scope warnings as prompts to update the SPEC; reserve `check-scope --strict` for CI or reviewer gates where unreported changes must block delivery.
- `registry.json` and `SPEC-OVERVIEW.md` are disposable generated views. On merge conflicts between them, discard either side and rerun `sync`; never hand-merge them.
- At milestones during active development, publish a `heartbeat` so parallel agents know what you are doing. Heartbeats are ephemeral runtime state; SPEC files are durable contracts.
- For cross-tool integration (Claude Code, Cursor, Windsurf), expose this CLI via the bundled MCP server: `pip install mcp && python <skill-folder>/scripts/mcp_server.py`. Register it as a stdio MCP server in the target tool's settings.

Read [references/schema.md](references/schema.md) for field semantics and [README.md](README.md) for complete command examples and publishing notes.
