#!/usr/bin/env python3
"""Maintain a shared SPEC registry for parallel development tasks.

Changes from uploaded v1:
  - All command handlers return int exit code; main() calls sys.exit().
    Fixes MCP server termination when check-scope finds violations.
  - attach: checks for file-level conflicts inside an Epic before creating
    the worktree; fixes SPEC copy order (status update first, then copy).
  - scan_specs: emits WARNING when blocks/depends_on are inconsistent.
  - status / check: accept --task-id filter.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SPECS_DIR = Path(".specs")
REGISTRY_PATH = SPECS_DIR / "registry.json"
OVERVIEW_PATH = SPECS_DIR / "SPEC-OVERVIEW.md"
TEMPLATE_PATH = SPECS_DIR / "SPEC-TEMPLATE.md"
WORKTREES_DIR = Path(".worktrees")
SYNC_DIR = Path(".sync")
ID_PATTERN = re.compile(r"^SPEC-(\d+)$")
STATUSES = ("Draft", "In-Progress", "Completed", "Deprecated")
UAS_SCHEMA_VERSION = "2.0"

TEMPLATE = '''\
---
id: {spec_id}
title: "{title}"
task_id: "{task_id}"
epic_id: "{epic_id}"
status: "{status}"
owner: "{owner}"
created_at: "{today}"
updated_at: "{today}"
depends_on:{dependencies}
blocks: []
impact_scope:
  modules:{modules}
  files:{files}
  api_endpoints:{api_endpoints}
  db_entities:{db_entities}
summary: "{summary}"
breaking_changes: false
---

## Background and Motivation

Explain the problem, user need, or defect being addressed.

## Technical Design

- Data/model changes:
- API/contract changes:
- Core behavior:

## Dependencies and Side Effects

- Upstream requirements:
- Breaking changes and migration:
- Operational or rollout notes:

## Acceptance Criteria

- [ ] Automated tests cover the main behavior.
- [ ] Contract/API expectations are verified.
- [ ] Migration and rollback implications are checked (or marked not applicable).
'''


class RegistryError(Exception):
    """Expected user-facing command error."""


@dataclass(frozen=True)
class ImpactScope:
    modules: list[str]
    files: list[str]
    api_endpoints: list[str]
    db_entities: list[str]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    return date.today().isoformat()


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_list(values: list[str], indent: str) -> str:
    return "".join(f"\n{indent}- {yaml_quote(value)}" for value in values) or " []"


def parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        try:
            return raw[1:-1].encode().decode("unicode_escape")
        except UnicodeDecodeError:
            return raw[1:-1]
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def parse_inline_list(raw: str) -> list[Any]:
    inner = raw.strip()[1:-1].strip()
    if not inner:
        return []
    return [parse_scalar(item.strip()) for item in inner.split(",")]


def load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.DOTALL)
    if not match:
        raise RegistryError(f"{path}: missing YAML frontmatter")

    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(0, result)]
    last_key_by_indent: dict[int, tuple[dict[str, Any], str]] = {}

    frontmatter_lines = match.group(1).splitlines()
    for line_index, source in enumerate(frontmatter_lines):
        line_no = line_index + 2
        stripped = source.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(source) - len(source.lstrip(" "))
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()

        if stripped.startswith("- "):
            candidates = [
                (ki, v) for ki, v in last_key_by_indent.items() if ki <= indent
            ]
            if not candidates:
                raise RegistryError(f"{path}:{line_no}: list item has no owning key")
            _, (owner_obj, owner_key) = max(candidates, key=lambda pair: pair[0])
            if not isinstance(owner_obj.get(owner_key), list):
                raise RegistryError(f"{path}:{line_no}: unexpected list item")
            owner_obj[owner_key].append(parse_scalar(stripped[2:]))
            continue

        key_part, separator, raw_value = stripped.partition(":")
        if not separator:
            raise RegistryError(f"{path}:{line_no}: expected 'key:'")
        key = key_part.strip()
        parent = stack[-1][1]
        raw_value = raw_value.strip()

        following = ""
        for candidate in frontmatter_lines[line_index + 1:]:
            candidate = candidate.strip()
            if candidate and not candidate.startswith("#"):
                following = candidate
                break

        if raw_value == "" and following.startswith("- "):
            parent[key] = []
        elif raw_value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent + 1, child))
        elif raw_value.startswith("[") and raw_value.endswith("]"):
            parent[key] = parse_inline_list(raw_value)
        else:
            parent[key] = parse_scalar(raw_value)
        last_key_by_indent[indent] = (parent, key)

    return result


def as_str_list(value: Any, field: str, path: Path) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise RegistryError(f"{path}: {field} must be a string or string list")


def as_bool(value: Any, field: str, path: Path) -> bool:
    if isinstance(value, bool):
        return value
    raise RegistryError(f"{path}: {field} must be true or false")


def normalize_spec(path: Path) -> dict[str, Any]:
    meta = load_yaml(path)
    required = ("id", "title", "task_id", "status", "owner", "created_at", "updated_at", "summary")
    missing = [f for f in required if f not in meta or meta[f] in (None, "")]
    if missing:
        raise RegistryError(f"{path}: missing required fields: {', '.join(missing)}")

    spec_id = str(meta["id"])
    if not ID_PATTERN.fullmatch(spec_id):
        raise RegistryError(f"{path}: id must match SPEC-NNN")
    if meta["status"] not in STATUSES:
        raise RegistryError(f"{path}: invalid status {meta['status']!r}")

    scope_raw = meta.get("impact_scope") or {}
    if not isinstance(scope_raw, dict):
        raise RegistryError(f"{path}: impact_scope must be a mapping")
    scope = ImpactScope(
        modules=as_str_list(scope_raw.get("modules"), "impact_scope.modules", path),
        files=as_str_list(scope_raw.get("files"), "impact_scope.files", path),
        api_endpoints=as_str_list(scope_raw.get("api_endpoints"), "impact_scope.api_endpoints", path),
        db_entities=as_str_list(scope_raw.get("db_entities"), "impact_scope.db_entities", path),
    )
    if not any((scope.modules, scope.files, scope.api_endpoints, scope.db_entities)):
        raise RegistryError(
            f"{path}: impact_scope must declare at least one module, file, endpoint, or entity"
        )

    return {
        "id": spec_id,
        "title": str(meta["title"]),
        "task_id": str(meta["task_id"]),
        "epic_id": str(meta.get("epic_id") or "default"),
        "status": str(meta["status"]),
        "owner": str(meta["owner"]),
        "created_at": str(meta["created_at"]),
        "updated_at": str(meta["updated_at"]),
        "depends_on": as_str_list(meta.get("depends_on"), "depends_on", path),
        "blocks": as_str_list(meta.get("blocks"), "blocks", path),
        "impact_scope": scope.__dict__,
        "summary": str(meta["summary"]),
        "breaking_changes": as_bool(meta.get("breaking_changes", False), "breaking_changes", path),
        "source_path": path.as_posix(),
    }


def scan_specs(warn: bool = True) -> list[dict[str, Any]]:
    """Load, validate, and sort all SPEC-NNN.md files in SPECS_DIR.

    Emits stderr WARNINGs (not errors) for blocks/depends_on asymmetry so
    that CI pipelines are not broken by partially-written SPECs.
    """
    if not SPECS_DIR.is_dir():
        raise RegistryError(".specs does not exist; run 'init' first")
    specs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(SPECS_DIR.glob("SPEC-*.md")):
        # Skip template and any slug-named files (SPEC-001-slug.md)
        if path.name == "SPEC-TEMPLATE.md" or not ID_PATTERN.fullmatch(path.stem):
            continue
        spec = normalize_spec(path)
        if spec["id"] in seen_ids:
            raise RegistryError(f"duplicate SPEC id: {spec['id']}")
        seen_ids.add(spec["id"])
        specs.append(spec)

    # Validate cross-references
    for spec in specs:
        unknown = sorted(set(spec["depends_on"] + spec["blocks"]) - seen_ids)
        if unknown:
            raise RegistryError(
                f"{spec['source_path']}: unknown referenced SPEC IDs: {', '.join(unknown)}"
            )

    # Cycle detection via DFS (3-colour)
    graph = {spec["id"]: set(spec["depends_on"]) for spec in specs}
    state: dict[str, int] = {}

    def visit(node: str, trail: list[str]) -> None:
        if state.get(node) == 1:
            cycle_start = trail.index(node)
            cycle = " -> ".join(trail[cycle_start:] + [node])
            raise RegistryError(f"circular dependency: {cycle}")
        if state.get(node) == 2:
            return
        state[node] = 1
        for dep in graph[node]:
            visit(dep, trail + [dep])
        state[node] = 2

    for node in graph:
        visit(node, [])

    # FIX: blocks / depends_on symmetry check (WARNING only, not error)
    if warn:
        id_to_spec = {s["id"]: s for s in specs}
        for spec in specs:
            for blocked_id in spec["blocks"]:
                blocked = id_to_spec.get(blocked_id)
                if blocked and spec["id"] not in blocked["depends_on"]:
                    print(
                        f"WARNING: {spec['id']} declares blocks: {blocked_id} "
                        f"but {blocked_id}.depends_on does not list {spec['id']}",
                        file=sys.stderr,
                    )

    return sorted(specs, key=lambda item: int(ID_PATTERN.fullmatch(item["id"]).group(1)))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def build_overview(specs: list[dict[str, Any]]) -> str:
    lines = [
        "# SPEC Overview",
        "",
        f"_Generated from `{REGISTRY_PATH.as_posix()}` at {utc_now()}. Do not edit by hand._",
        "",
        "Open individual SPECs only when their declared scope affects current work.",
        "",
    ]
    groups = (
        ("Active", ("In-Progress", "Draft")),
        ("Completed", ("Completed",)),
        ("Deprecated", ("Deprecated",)),
    )
    for label, statuses in groups:
        selected = [spec for spec in specs if spec["status"] in statuses]
        lines.extend([f"## {label}", ""])
        if not selected:
            lines.extend(["_None._", ""])
            continue
        for spec in selected:
            impacts: list[str] = []
            for key in ("modules", "files", "api_endpoints", "db_entities"):
                impacts.extend(spec["impact_scope"][key])
            impact_text = ", ".join(f"`{v}`" for v in impacts[:12])
            if len(impacts) > 12:
                impact_text += ", ..."
            breaking = "; **BREAKING**" if spec["breaking_changes"] else ""
            dependencies = (
                f"; depends on {', '.join(spec['depends_on'])}" if spec["depends_on"] else ""
            )
            lines.append(
                f"- **{spec['id']}** - {spec['title']} - `{spec['status']}` "
                f"| task `{spec['task_id']}`{breaking}{dependencies} | {impact_text or 'no declared impact'}"
            )
            lines.append(f"  {spec['summary']} (`{spec['source_path']}`)")
        lines.append("")
    return "\n".join(lines)


def sync(quiet: bool = False) -> list[dict[str, Any]]:
    specs = scan_specs()
    SPECS_DIR.mkdir(exist_ok=True)
    write_json_atomic(REGISTRY_PATH, {"last_updated": utc_now(), "specs": specs})
    OVERVIEW_PATH.write_text(build_overview(specs), encoding="utf-8")
    if not quiet:
        print(f"synced {len(specs)} SPECs -> {REGISTRY_PATH}, {OVERVIEW_PATH}")
    return specs


def next_spec_id(specs: list[dict[str, Any]]) -> str:
    numbers = [int(ID_PATTERN.fullmatch(spec["id"]).group(1)) for spec in specs]
    return f"SPEC-{max(numbers, default=0) + 1:03d}"


def normalize_relative(value: str) -> str:
    val = value.replace("\\", "/")
    if val.startswith("./"):
        val = val[2:]
    return val.rstrip("/")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def init_command(_args: argparse.Namespace) -> int:
    SPECS_DIR.mkdir(exist_ok=True)
    if TEMPLATE_PATH.exists():
        print(f"template already exists: {TEMPLATE_PATH}")
    else:
        body = TEMPLATE.format(
            spec_id="SPEC-000",
            title="Example title",
            task_id="TASK-ID",
            epic_id="example-epic",
            status="Draft",
            owner="Owner",
            today=today(),
            dependencies=yaml_list([], "  "),
            modules=yaml_list(["services/example"], "    "),
            files=yaml_list(["services/example/file.py"], "    "),
            api_endpoints=yaml_list([], "    "),
            db_entities=yaml_list([], "    "),
            summary="One-sentence purpose.",
        )
        TEMPLATE_PATH.write_text(body, encoding="utf-8")
        print(f"created {TEMPLATE_PATH}")
    sync()
    return 0


def new_command(args: argparse.Namespace) -> int:
    specs = sync(quiet=True)
    if not any((args.modules, args.files, args.api_endpoints, args.db_entities)):
        raise RegistryError("declare at least one --module, --file, --api, or --db impact")
    spec_id = next_spec_id(specs)
    path = SPECS_DIR / f"{spec_id}.md"
    body = TEMPLATE.format(
        spec_id=spec_id,
        title=args.title,
        task_id=args.task_id,
        epic_id=args.epic_id,
        status="Draft",
        owner=args.owner,
        today=today(),
        dependencies=yaml_list(args.depends_on, "  "),
        modules=yaml_list(args.modules, "    "),
        files=yaml_list(args.files, "    "),
        api_endpoints=yaml_list(args.api_endpoints, "    "),
        db_entities=yaml_list(args.db_entities, "    "),
        summary=args.summary,
    ).replace(
        "breaking_changes: false",
        "breaking_changes: true" if args.breaking_changes else "breaking_changes: false",
    )
    path.write_text(body, encoding="utf-8")
    sync()
    print(f"created {path}")
    if args.open and os.environ.get("EDITOR"):
        subprocess.run([os.environ["EDITOR"], str(path)], check=False)
    return 0


def find_spec(specs: list[dict[str, Any]], spec_id: str) -> dict[str, Any]:
    matches = [spec for spec in specs if spec["id"].lower() == spec_id.lower()]
    if not matches:
        raise RegistryError(f"unknown SPEC id: {spec_id}")
    return matches[0]


def set_status_in_file(path: Path, status: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, n = re.subn(r"(?m)^status:.*$", f'status: "{status}"', text, count=1)
    if n != 1:
        raise RegistryError(f"could not locate status field in {path}")
    updated = re.sub(r"(?m)^updated_at:.*$", f'updated_at: "{today()}"', updated, count=1)
    path.write_text(updated, encoding="utf-8")


def set_status_command(args: argparse.Namespace) -> int:
    specs = scan_specs()
    spec = find_spec(specs, args.id)
    path = Path(spec["source_path"])
    set_status_in_file(path, args.status)
    sync()
    print(f"{spec['id']} -> {args.status}")
    return 0


def status_command(args: argparse.Namespace) -> int:
    specs = scan_specs()
    # FIX: --task-id filter
    if args.task_id:
        specs = [s for s in specs if s["task_id"].lower() == args.task_id.lower()]
    if args.format == "json":
        print(json.dumps({"specs": specs}, ensure_ascii=False, indent=2))
    else:
        for spec in specs:
            print(f"{spec['id']:9} {spec['status']:11} {spec['task_id']:18} {spec['title']}")
    return 0


def collect_query(args: argparse.Namespace) -> tuple[list[str], list[str], list[str], list[str]]:
    return (
        [normalize_relative(item) for item in args.modules],
        [normalize_relative(item) for item in args.files],
        list(args.api_endpoints),
        list(args.db_entities),
    )


def overlaps(
    spec: dict[str, Any], query: tuple[list[str], list[str], list[str], list[str]]
) -> list[str]:
    query_modules, query_files, query_apis, query_dbs = query
    scope = spec["impact_scope"]
    matches: list[str] = []
    for requested, declared, label in (
        (query_modules, scope["modules"], "module"),
        (query_files, scope["files"], "file"),
        (query_apis, scope["api_endpoints"], "API"),
        (query_dbs, scope["db_entities"], "database entity"),
    ):
        for value in requested:
            if value in declared:
                matches.append(f"{label}: {value}")
    return matches


def check_command(args: argparse.Namespace) -> int:
    specs = scan_specs()
    # FIX: --task-id filter
    if args.task_id:
        specs = [s for s in specs if s["task_id"].lower() != args.task_id.lower()]
    query = collect_query(args)
    statuses = STATUSES if args.all else ("Draft", "In-Progress")
    conflicts: list[dict[str, Any]] = []
    for spec in specs:
        if spec["status"] not in statuses:
            continue
        matched = overlaps(spec, query)
        if matched:
            conflicts.append({
                "spec": spec["id"],
                "status": spec["status"],
                "task_id": spec["task_id"],
                "overlaps": matched,
            })
    if args.json:
        print(json.dumps({"conflicts": conflicts}, ensure_ascii=False, indent=2))
    elif conflicts:
        print("Potential SPEC overlaps:")
        for item in conflicts:
            print(f"- {item['spec']} ({item['status']}, {item['task_id']}): {'; '.join(item['overlaps'])}")
    else:
        print("No declared SPEC overlaps found.")
    return 0


# ---------------------------------------------------------------------------
# Git / Worktree helpers
# ---------------------------------------------------------------------------

def require_git_repo() -> None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RegistryError("not inside a Git repository; worktree commands require Git")


def git(*arguments: str) -> str:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise RegistryError(f"git {' '.join(arguments)} failed: {message}")
    return result.stdout.strip()


def epic_slug(epic_id: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", epic_id.lower()).strip("-")
    if not slug:
        raise RegistryError("epic_id must contain at least one letter or digit")
    return slug


def epic_branch(epic_id: str) -> str:
    return f"spec/{epic_slug(epic_id)}"


def epic_worktree_path(epic_id: str) -> Path:
    return WORKTREES_DIR / f"epic-{epic_slug(epic_id)}"


def read_epics(specs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    epics: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        epics.setdefault(spec["epic_id"], []).append(spec)
    return epics


def update_frontmatter_field(path: Path, field: str, value: str) -> bool:
    text = path.read_text(encoding="utf-8")
    updated, replacements = re.subn(
        rf"(?m)^{re.escape(field)}:.*$",
        f'{field}: "{value}"',
        text,
        count=1,
    )
    if replacements == 1:
        path.write_text(updated, encoding="utf-8")
    return replacements == 1


def attach_command(args: argparse.Namespace) -> int:
    require_git_repo()
    specs = scan_specs()
    spec = find_spec(specs, args.spec)
    epic_id = spec["epic_id"]
    path = Path(spec["source_path"])

    if spec["status"] in ("Completed", "Deprecated"):
        raise RegistryError(f"{spec['id']} is {spec['status']}; it cannot be attached")

    # FIX: Check for file-level conflicts among In-Progress SPECs in the same Epic
    same_epic_active = [
        s for s in specs
        if s["epic_id"] == epic_id
        and s["id"] != spec["id"]
        and s["status"] == "In-Progress"
    ]
    new_files = set(spec["impact_scope"]["files"])
    for other in same_epic_active:
        overlap = new_files & set(other["impact_scope"]["files"])
        if overlap:
            raise RegistryError(
                f"file conflict inside Epic '{epic_id}': "
                f"{spec['id']} and {other['id']} both declare: {sorted(overlap)}. "
                f"Add depends_on or resolve before attaching."
            )

    if not WORKTREES_DIR.is_dir():
        WORKTREES_DIR.mkdir()

    branch = epic_branch(epic_id)
    destination = epic_worktree_path(epic_id).resolve()
    repo_root = Path(git("rev-parse", "--show-toplevel")).resolve()
    if not destination.is_relative_to(repo_root):
        raise RegistryError("resolved worktree path escaped the repository")

    created_worktree = False
    if destination.exists():
        existing_branch = git("-C", str(destination), "rev-parse", "--abbrev-ref", "HEAD")
        if existing_branch != branch:
            raise RegistryError(
                f"worktree {destination} exists but is on {existing_branch}, expected {branch}"
            )
    else:
        branches = git("branch", "--list", branch).splitlines()
        if branches:
            git("worktree", "add", str(destination), branch)
        else:
            git("worktree", "add", "-b", branch, str(destination), args.base)
        created_worktree = True

    # FIX: Update status in source file FIRST, then copy so the copy carries
    # the correct In-Progress status (not the stale Draft).
    if spec["status"] == "Draft":
        set_status_in_file(path, "In-Progress")
        sync(quiet=True)
        # Re-read path after sync (source_path unchanged, but file content updated)

    worktree_specs = destination / SPECS_DIR
    worktree_specs.mkdir(exist_ok=True)
    shutil.copy2(path, worktree_specs / path.name)

    action = "created" if created_worktree else "reused"
    print(f"{action} worktree {destination}")
    print(f"branch: {branch}")
    print(f"spec:   {spec['id']} ({Path(spec['source_path'])})")
    print("edit only inside this worktree until delivery")
    return 0


def changed_files(base: str, worktree: Path | None = None) -> list[str]:
    prefix = ["-C", str(worktree)] if worktree else []
    output = git(*prefix, "diff", "--name-only", base)
    untracked = git(*prefix, "ls-files", "--others", "--exclude-standard")
    specs_posix = normalize_relative(SPECS_DIR.as_posix())
    sync_posix = normalize_relative(SYNC_DIR.as_posix())
    files: set[str] = set()
    for item in (output + "\n" + untracked).splitlines():
        norm = normalize_relative(item)
        if not norm:
            continue
        if norm == specs_posix or norm.startswith(specs_posix + "/"):
            continue
        if norm == sync_posix or norm.startswith(sync_posix + "/"):
            continue
        files.add(norm)
    return sorted(files)


def scope_matches(changed: str, scope: dict[str, Any]) -> tuple[bool, list[str]]:
    """Check if a changed file path is within the declared impact scope.

    NOTE: api_endpoints and db_entities are semantic scope dimensions used by
    'check' (pre-work conflict detection). 'check-scope' operates on physical
    git diffs and only validates files and modules.
    """
    normalized_changed = normalize_relative(changed)
    for file_path in scope["files"]:
        if normalized_changed == normalize_relative(file_path):
            return True, []
    for module in scope["modules"]:
        module_path = normalize_relative(module)
        if module_path and (
            normalized_changed == module_path
            or normalized_changed.startswith(module_path + "/")
        ):
            return True, []
    return False, ["file is outside impact_scope.files and all impact_scope.modules"]


def check_scope_command(args: argparse.Namespace) -> int:
    """FIX: Returns exit code instead of calling sys.exit() directly.
    This allows MCP server to call this without terminating the process.
    """
    specs = scan_specs()
    spec = find_spec(specs, args.spec)
    worktree: Path | None = None
    if args.worktree:
        candidate = Path(args.worktree).resolve()
        if not candidate.is_dir():
            raise RegistryError(f"worktree does not exist: {candidate}")
        worktree = candidate
    files = changed_files(args.base, worktree)
    violations: list[str] = []
    allowed: list[str] = []
    for item in files:
        matched, _ = scope_matches(item, spec["impact_scope"])
        if matched:
            allowed.append(item)
        else:
            violations.append(item)
    payload = {
        "spec": spec["id"],
        "base": args.base,
        "changed_files": files,
        "allowed": allowed,
        "violations": violations,
        "strict": args.strict,
    }
    exit_code = 3 if (violations and args.strict) else 0
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif violations:
        label = "Out-of-scope changes:" if args.strict else "Unreported changed files:"
        print(label)
        for item in violations:
            print(f"- {item}")
        if not args.strict:
            print("update the SPEC impact_scope or confirm these files are intentionally shared")
    else:
        print("All changed files match the declared impact scope.")
    return exit_code   # caller (main or MCP) decides whether to sys.exit


def finish_command(args: argparse.Namespace) -> int:
    require_git_repo()
    specs = scan_specs()
    epics = read_epics(specs)
    if args.epic not in epics:
        raise RegistryError(f"no SPECs are assigned to epic '{args.epic}'")
    epic_specs = epics[args.epic]
    incomplete = [
        s["id"] for s in epic_specs if s["status"] not in ("Completed", "Deprecated")
    ]
    if incomplete:
        raise RegistryError(
            f"cannot finish epic '{args.epic}'; these SPECs are still active: {', '.join(incomplete)}"
        )

    branch = epic_branch(args.epic)
    destination = epic_worktree_path(args.epic).resolve()
    if destination.exists():
        current_branch = git("-C", str(destination), "rev-parse", "--abbrev-ref", "HEAD")
        if current_branch != branch:
            raise RegistryError(
                f"worktree {destination} is on unexpected branch {current_branch}"
            )
        merged = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch, args.base],
            capture_output=True,
            text=True,
        )
        if merged.returncode != 0:
            raise RegistryError(
                f"branch {branch} has not been merged into {args.base}; merge it before finish"
            )
        try:
            git("worktree", "remove", str(destination))
        except RegistryError:
            git("worktree", "remove", "--force", str(destination))
        print(f"removed worktree {destination}")
    else:
        print("no local worktree to remove")
    git("worktree", "prune")
    print(f"finished epic {args.epic}; SPEC records remain archived in .specs/")
    return 0


def worktrees_command(_args: argparse.Namespace) -> int:
    require_git_repo()
    specs = scan_specs()
    epics = read_epics(specs)
    if not epics:
        print("No Epic assignments found.")
        return 0
    for epic_id, epic_specs in sorted(epics.items()):
        active = sum(1 for s in epic_specs if s["status"] in ("Draft", "In-Progress"))
        total = len(epic_specs)
        destination = epic_worktree_path(epic_id)
        state = "active" if destination.exists() else "absent"
        print(
            f"{epic_id:24} branch=spec/{epic_slug(epic_id):30} "
            f"worktree={state:7} active={active} total={total}"
        )
    return 0


# ---------------------------------------------------------------------------
# Heartbeat (UAS runtime awareness — lightweight concurrent only)
# Full relay/handoff is handled by the peer-relay-v3 skill.
# ---------------------------------------------------------------------------

def heartbeat_path(spec_id: str) -> Path:
    return SYNC_DIR / f"task-{spec_id}.json"


def build_uas(spec: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": UAS_SCHEMA_VERSION,
        "skill": "spec-registry",
        "task_id": spec["id"],
        "spec_id": spec["id"],
        "epic": spec["epic_id"],
        "agent_model": args.model or "unknown",
        "agent_tool": args.tool or "unknown",
        "mode": "concurrent",
        "sender_continues": True,
        "timestamp": utc_now(),
        "context_level": args.context_level,
        "worktree": str(epic_worktree_path(spec["epic_id"]).as_posix()),
        "current_focus": args.focus or "",
        "notes": args.notes or "",
    }


def load_heartbeats() -> list[dict[str, Any]]:
    if not SYNC_DIR.is_dir():
        return []
    states: list[dict[str, Any]] = []
    for path in sorted(SYNC_DIR.glob("task-*.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(state, dict) and state.get("task_id"):
                states.append(state)
        except (json.JSONDecodeError, OSError):
            pass
    return states


def render_merged_heartbeats(states: list[dict[str, Any]]) -> str:
    lines = [
        "# Active Task Heartbeats",
        "",
        f"_Generated at {utc_now()} | {len(states)} active task(s)_",
        "",
    ]
    for s in states:
        mode_label = "Relay (sender stopped)" if not s.get("sender_continues") else "Concurrent"
        lines.extend([
            f"## {s.get('task_id', 'unknown')} ({mode_label})",
            f"- tool/model: {s.get('agent_tool', '?')} / {s.get('agent_model', '?')}",
            f"- epic: `{s.get('epic', 'default')}`",
            f"- worktree: `{s.get('worktree', 'N/A')}`",
            f"- context: {s.get('context_level', '?')}%",
            f"- focus: {s.get('current_focus', '(not set)')}",
            "",
        ])
    return "\n".join(lines)


def sync_heartbeats(quiet: bool = False) -> list[dict[str, Any]]:
    states = load_heartbeats()
    SYNC_DIR.mkdir(exist_ok=True)
    merged = SYNC_DIR / "MERGED_STATE.md"
    merged.write_text(render_merged_heartbeats(states), encoding="utf-8")
    if not quiet:
        print(f"synced {len(states)} heartbeat(s) -> {merged}")
    return states


def heartbeat_command(args: argparse.Namespace) -> int:
    specs = scan_specs()
    spec = find_spec(specs, args.spec)
    if spec["status"] in ("Completed", "Deprecated"):
        raise RegistryError(
            f"{spec['id']} is {spec['status']}; cannot publish a heartbeat for an inactive SPEC"
        )
    uas = build_uas(spec, args)
    SYNC_DIR.mkdir(exist_ok=True)
    path = heartbeat_path(spec["id"])
    write_json_atomic(path, uas)
    sync_heartbeats(quiet=True)
    print(f"heartbeat published: {path}")
    return 0


def heartbeats_command(args: argparse.Namespace) -> int:
    states = load_heartbeats()
    if args.json:
        print(json.dumps({"heartbeats": states}, ensure_ascii=False, indent=2))
    else:
        for s in states:
            mode = "relay" if not s.get("sender_continues") else "concurrent"
            print(
                f"{s['task_id']:12} {s.get('epic', 'default'):24} "
                f"{s.get('agent_tool', '?'):16} {s.get('current_focus', '')[:50]}"
            )
        if not states:
            print("No active heartbeats.")
    sync_heartbeats(quiet=True)
    return 0


def watch_command(args: argparse.Namespace) -> int:
    SYNC_DIR.mkdir(exist_ok=True)
    pid_file = SYNC_DIR / "watcher.pid"
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)
            print(f"watcher already running (PID {old_pid})")
            return 0
        except (ProcessLookupError, ValueError, PermissionError):
            pid_file.unlink(missing_ok=True)

    interval = args.interval
    print(f"watching .sync/ every {interval}s (Ctrl+C to stop)")
    pid_file.write_text(str(os.getpid()))
    try:
        while True:
            sync_heartbeats(quiet=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        pid_file.unlink(missing_ok=True)
        print("watcher stopped")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    # init
    p = sub.add_parser("init", help="create .specs and initial generated files")
    p.set_defaults(handler=init_command)

    # new
    p = sub.add_parser("new", help="create the next sequential SPEC")
    p.add_argument("--title", required=True)
    p.add_argument("--task-id", required=True)
    p.add_argument("--epic", required=True, dest="epic_id")
    p.add_argument("--owner", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--module", action="append", default=[], dest="modules")
    p.add_argument("--file", action="append", default=[], dest="files")
    p.add_argument("--api", action="append", default=[], dest="api_endpoints")
    p.add_argument("--db", action="append", default=[], dest="db_entities")
    p.add_argument("--depends-on", action="append", default=[], dest="depends_on")
    p.add_argument("--blocks", action="append", default=[])
    p.add_argument("--breaking-changes", action="store_true")
    p.add_argument("--open", action="store_true")
    p.set_defaults(handler=new_command)

    # set-status
    p = sub.add_parser("set-status", help="change a SPEC lifecycle status")
    p.add_argument("--id", required=True)
    p.add_argument("--status", required=True, choices=STATUSES)
    p.set_defaults(handler=set_status_command)

    # sync
    p = sub.add_parser("sync", help="regenerate registry/overview from markdown")
    p.set_defaults(handler=lambda _args: (sync(), 0)[1])

    # status — FIX: added --task-id
    p = sub.add_parser("status", help="show SPEC ledger")
    p.add_argument("--format", choices=("table", "json"), default="table")
    p.add_argument("--task-id", default="", help="filter by task ID")
    p.set_defaults(handler=status_command)

    # check — FIX: added --task-id (excludes own task's SPECs from conflict check)
    p = sub.add_parser("check", help="check intended scope against existing SPECs")
    p.add_argument("--module", action="append", default=[], dest="modules")
    p.add_argument("--file", action="append", default=[], dest="files")
    p.add_argument("--api", action="append", default=[], dest="api_endpoints")
    p.add_argument("--db", action="append", default=[], dest="db_entities")
    p.add_argument("--all", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--task-id", default="",
        help="exclude this task's own SPECs from the conflict check"
    )
    p.set_defaults(handler=check_command)

    # attach
    p = sub.add_parser("attach", help="create or reuse an Epic worktree for a SPEC")
    p.add_argument("--spec", required=True)
    p.add_argument("--base", default="HEAD")
    p.set_defaults(handler=attach_command)

    # check-scope
    p = sub.add_parser("check-scope", help="validate changed files against SPEC impact_scope")
    p.add_argument("--spec", required=True)
    p.add_argument("--base", default="HEAD")
    p.add_argument("--worktree")
    p.add_argument("--strict", action="store_true", help="exit 3 on violations (CI gate)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=check_scope_command)

    # finish
    p = sub.add_parser("finish", help="remove Epic worktree after all SPECs are merged")
    p.add_argument("--epic", required=True)
    p.add_argument("--base", default="main")
    p.set_defaults(handler=finish_command)

    # worktrees
    p = sub.add_parser("worktrees", help="show Epic-to-worktree mappings")
    p.set_defaults(handler=worktrees_command)

    # heartbeat (concurrent only; relay is handled by peer-relay-v3)
    p = sub.add_parser("heartbeat", help="publish a lightweight concurrent awareness signal")
    p.add_argument("--spec", required=True)
    p.add_argument("--focus", required=True)
    p.add_argument("--tool", default="unknown")
    p.add_argument("--model", default="unknown")
    p.add_argument("--context-level", type=int, default=50)
    p.add_argument("--notes", default="")
    p.set_defaults(handler=heartbeat_command)

    # heartbeats
    p = sub.add_parser("heartbeats", help="list active heartbeats and refresh merged view")
    p.add_argument("--json", action="store_true")
    p.set_defaults(handler=heartbeats_command)

    # watch
    p = sub.add_parser("watch", help="cross-platform .sync/ polling watcher")
    p.add_argument("--interval", type=float, default=5.0)
    p.set_defaults(handler=watch_command)

    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        # FIX: All handlers return int; main() is the single sys.exit() call site.
        result = args.handler(args)
        return result if isinstance(result, int) else 0
    except RegistryError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except OSError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
