# SPEC Metadata Schema

YAML frontmatter is the structured contract. Markdown sections carry detail for humans and later task context.

## Fields

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | Stable identifier in `SPEC-NNN` format. |
| `title` | string | yes | Short user-facing change title. |
| `task_id` | string | yes | Issuing task or branch identifier, such as `TASK-A`. |
| `epic_id` | string | recommended | Group identifier for related SPECs that share one transient worktree, such as `order-refactor`. Defaults to `default`. |
| `status` | enum | yes | `Draft`, `In-Progress`, `Completed`, or `Deprecated`. |
| `owner` | string | yes | Owning agent role, task name, or person. |
| `created_at` | date | yes | ISO date when the SPEC was issued. |
| `updated_at` | date | yes | ISO date of the latest meaningful update. |
| `depends_on` | string array | no | SPEC IDs that must be understood or completed first. |
| `blocks` | string array | no | Explicitly affected downstream SPEC IDs or task identifiers. |
| `impact_scope.modules` | string array | yes* | Repository-relative directories or logical modules. At least one impact field must be nonempty. |
| `impact_scope.files` | string array | no | Exact repository-relative files expected to change. |
| `impact_scope.api_endpoints` | string array | no | Endpoint signatures such as `POST /api/v1/orders`. |
| `impact_scope.db_entities` | string array | no | Tables, collections, fields, migrations, or indexes. |
| `summary` | string | yes | One-sentence purpose and outcome. |
| `breaking_changes` | boolean | yes | Whether compatibility requires coordinated migration. |

Unknown fields may be retained in source files, but generated indexes prioritize these fields.

## Markdown Sections

Use these headings in order:

1. `Background and Motivation`
2. `Technical Design`
3. `Dependencies and Side Effects`
4. `Acceptance Criteria`

Acceptance criteria must be concrete enough for another task to verify completion. For breaking changes, document the old contract, new contract, migration path, and rollback boundary.

## Worktree Mapping

The CLI maps an Epic deterministically:

- Branch: `spec/<epic-slug>`
- Worktree: `.worktrees/epic-<epic-slug>`
- SPEC files: durable records in `.specs/`

Related small changes should share the same `epic_id`. A new Epic is justified by an independent parallel stream or materially different review boundary, not merely by the number of bugfix SPECs. After merge and completion, remove the worktree with `finish`; keep the SPEC record forever.
