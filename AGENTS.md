# Agent Working Agreement

## Default Directory

All Codex conversations, project files, and generated artifacts are stored under `D:\AI Tech Discussion\Codex`. The previous location `C:\Users\wzwzy\Documents\Codex` is deprecated.

## Code Quality Discipline

These rules were established after a peer review found six defects that self-review missed. They apply to every skill, CLI tool, or script delivered by this agent.

### 1. Exit Codes and Process Safety

- All subcommand handler functions return an `int` exit code; only `main()` calls `sys.exit()`.
- Never call `sys.exit()` inside a handler that may be embedded in a long-running host process (MCP server, daemon, watcher).
- If a workaround (bypassing a function, catching an exception to suppress a crash) is needed, treat it as a signal that the underlying design has a defect. Fix the root cause before proceeding.

### 2. Side-Effect Ordering

- When a function performs multiple mutating operations (copy + modify, write + rename), add a comment above each step explaining why it must occur at that point in the sequence.
- If two copies of the same data exist after an operation (e.g., main checkout vs worktree), verify they are identical before proceeding.

### 3. Declarative Field Consistency

- When metadata fields have implicit logical constraints between them (e.g., `blocks: [X]` implies X should list this SPEC in `depends_on`), validate those constraints during scan/parse.
- Output warnings for inconsistencies rather than hard errors when the mismatch may be transient.

### 4. Happy Path Is Not Enough

- Every CLI command needs at least three test scenarios: normal path, boundary condition (empty input, zero items, max values), and error path.
- Integration tests must cover cross-layer interactions: calling a command via MCP server, running inside a git worktree, executing from a different working directory.

### 5. Documentation Must Cover All Perspectives

- SKILL.md or equivalent SOP documents must address every role: task initiator, relay receiver, CI reviewer, human operator.
- Commands with similar names but different semantics (`check` vs `check-scope`) must have their distinction explicitly documented at the point of use.
- README directory examples must match the exact filenames produced by the code, verified character by character.

## Review Checklist (run before every delivery)

- [ ] No `sys.exit()` outside `main()`
- [ ] Multi-step mutations have ordering comments
- [ ] Implicit field constraints validated with warnings
- [ ] At least one boundary-case test per command
- [ ] MCP server can invoke every tool without crashing
- [ ] SKILL.md covers initiator, receiver, and reviewer perspectives
- [ ] README file paths match actual output exactly
