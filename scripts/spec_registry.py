#!/usr/bin/env python3
"""Maintain a shared SPEC registry for parallel development tasks."""

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

TEMPLATE = '''---
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
            candidates = [(key_indent, value) for key_indent, value in last_key_by_indent.items() if key_indent <= indent]
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
    missing = [field for field in required if field not in meta or meta[field] in (None, "")]
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
        raise RegistryError(f"{path}: impact_scope must declare at least one module, file, endpoint, or entity")

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


def scan_specs() -> list[dict[str, Any]]:
    if not SPECS_DIR.is_dir():
        raise RegistryError(".specs does not exist; run 'init' first")
    specs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in sorted(SPECS_DIR.glob("SPEC-*.md")):
        if path.name == "SPEC-TEMPLATE.md" or not ID_PATTERN.fullmatch(path.stem):
            continue
        spec = normalize_spec(path)
        if spec["id"] in seen_ids:
            raise RegistryError(f"duplicate SPEC id: {spec['id']}")
        seen_ids.add(spec["id"])
        specs.append(spec)

    for spec in specs:
        unknown = sorted(set(spec["depends_on"] + spec["blocks"]) - seen_ids)
        if unknown:
            raise RegistryError(f"{spec['source_path']}: unknown referenced SPEC IDs: {', '.join(unknown)}")

    # Warn about asymmetric blocks declarations (not a hard error).
    spec_by_id = {spec["id"]: spec for spec in specs}
    for spec in specs:
        for blocked_id in spec["blocks"]:
            blocked_spec = spec_by_id.get(blocked_id)
            if blocked_spec and spec["id"] not in blocked_spec.get("depends_on", []):
                print(
                    f"warning: {blocked_id} does not list {spec['id']} in depends_on "
                    f"but is declared as blocked by it",
                    file=sys.stderr,
                )

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

    return sorted(specs, key=lambda item: int(ID_PATTERN.fullmatch(item["id"]).group(1)))


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
            impact_text = ", ".join(f"`{value}`" for value in impacts[:12])
            if len(impacts) > 12:
                impact_text += ", ..."
            breaking = "; **BREAKING**" if spec["breaking_changes"] else ""
            dependencies = f"; depends on {', '.join(spec['depends_on'])}" if spec["depends_on"] else ""
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


def init_command(_args: argparse.Namespace) -> None:
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
            api_endpoints=[],
            db_entities=[],
            summary="One-sentence purpose.",
        )
        TEMPLATE_PATH.write_text(body, encoding="utf-8")
        print(f"created {TEMPLATE_PATH}")
    sync()


def new_command(args: argparse.Namespace) -> None:
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


def find_spec(specs: list[dict[str, Any]], spec_id: str) -> dict[str, Any]:
    matches = [spec for spec in specs if spec["id"].lower() == spec_id.lower()]
    if not matches:
        raise RegistryError(f"unknown SPEC id: {spec_id}")
    return matches[0]


def set_status_command(args: argparse.Namespace) -> None:
    specs = scan_specs()
    spec = find_spec(specs, args.id)
    path = Path(spec["source_path"])
    text = path.read_text(encoding="utf-8")
    updated, replacements = re.subn(r"(?m)^status:.*$", f'status: "{args.status}"', text, count=1)
    if replacements != 1:
        raise RegistryError(f"could not locate status field in {path}")
    updated = re.sub(r"(?m)^updated_at:.*$", f'updated_at: "{today()}"', updated, count=1)
    path.write_text(updated, encoding="utf-8")
    sync()
    print(f"{spec['id']} -> {args.status}")


def status_command(args: argparse.Namespace) -> None:
    specs = scan_specs()
    if args.format == "json":
        print(json.dumps({"specs": specs}, ensure_ascii=False, indent=2))
        return
    for spec in specs:
        print(f"{spec['id']:9} {spec['status']:11} {spec['task_id']:18} {spec['title']}")


def collect_query(args: argparse.Namespace) -> tuple[list[str], list[str], list[str], list[str]]:
    return (
        [normalize_relative(item) for item in args.modules],
        [normalize_relative(item) for item in args.files],
        list(args.api_endpoints),
        list(args.db_entities),
    )


def overlaps(spec: dict[str, Any], query: tuple[list[str], list[str], list[str], list[str]]) -> list[str]:
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


def check_command(args: argparse.Namespace) -> None:
    specs = scan_specs()
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


def attach_command(args: argparse.Namespace) -> None:
    specs = scan_specs()
    spec = find_spec(specs, args.spec)
    epic_id = spec["epic_id"]
    path = Path(spec["source_path"])

    if spec["status"] in ("Completed", "Deprecated"):
        raise RegistryError(f"{spec['id']} is {spec['status']}; it cannot be attached")

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

    if spec["status"] == "Draft":
        set_status_in_file(path, "In-Progress")
        sync(quiet=True)

    # Copy AFTER status update so the worktree copy matches the main checkout.
    worktree_specs = destination / SPECS_DIR
    worktree_specs.mkdir(exist_ok=True)
    shutil.copy2(path, worktree_specs / path.name)

    action = "created" if created_worktree else "reused"
    print(f"{action} worktree {destination}")
    print(f"branch: {branch}")
    print(f"spec:   {spec['id']} ({Path(spec['source_path'])})")
    print("edit only inside this worktree until delivery")


def set_status_in_file(path: Path, status: str) -> None:
    if not update_frontmatter_field(path, "status", status):
        raise RegistryError(f"could not locate status field in {path}")
    update_frontmatter_field(path, "updated_at", today())


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
    reasons: list[str] = []
    normalized_changed = normalize_relative(changed)
    for file_path in scope["files"]:
        if normalized_changed == normalize_relative(file_path):
            return True, []
    for module in scope["modules"]:
        module_path = normalize_relative(module)
        if module_path and (normalized_changed == module_path or normalized_changed.startswith(module_path + "/")):
            return True, []
    reasons.append("file is outside impact_scope.files and all impact_scope.modules")
    return False, reasons


def check_scope_command(args: argparse.Namespace) -> int:
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
        matched, _reasons = scope_matches(item, spec["impact_scope"])
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
    exit_code = 0
    if violations and args.strict:
        exit_code = 3
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
    return exit_code


def finish_command(args: argparse.Namespace) -> None:
    specs = scan_specs()
    epics = read_epics(specs)
    if args.epic not in epics:
        raise RegistryError(f"no SPECs are assigned to epic '{args.epic}'")
    epic_specs = epics[args.epic]
    incomplete = [spec["id"] for spec in epic_specs if spec["status"] not in ("Completed", "Deprecated")]
    if incomplete:
        raise RegistryError(f"cannot finish epic '{args.epic}'; these SPECs are still active: {', '.join(incomplete)}")

    branch = epic_branch(args.epic)
    destination = epic_worktree_path(args.epic).resolve()
    if destination.exists():
        current_branch = git("-C", str(destination), "rev-parse", "--abbrev-ref", "HEAD")
        if current_branch != branch:
            raise RegistryError(f"worktree {destination} is on unexpected branch {current_branch}")
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
            # Generated indexes may legitimately differ between branches;
            # they are rebuilt from Markdown and are never authoritative.
            git("worktree", "remove", "--force", str(destination))
        print(f"removed worktree {destination}")
    else:
        print("no local worktree to remove")
    git("worktree", "prune")
    print(f"finished epic {args.epic}; SPEC records remain archived in .specs/")


def worktrees_command(_args: argparse.Namespace) -> None:
    specs = scan_specs()
    epics = read_epics(specs)
    rows: list[tuple[str, str, str, int]] = []
    for epic_id, epic_specs in sorted(epics.items()):
        active = sum(1 for spec in epic_specs if spec["status"] in ("Draft", "In-Progress"))
        total = len(epic_specs)
        destination = epic_worktree_path(epic_id)
        state = "active" if destination.exists() else "absent"
        rows.append((epic_id, f"spec/{epic_slug(epic_id)}", state, total))
        print(f"{epic_id:24} branch=spec/{epic_slug(epic_id):30} worktree={state:7} active={active} total={total}")
    if not rows:
        print("No Epic assignments found.")


# ---------------------------------------------------------------------------
# Heartbeat (UAS runtime awareness)
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
        "mode": args.mode,
        "sender_continues": args.mode == "concurrent",
        "timestamp": utc_now(),
        "context_level": args.context_level,
        "worktree": str(epic_worktree_path(spec["epic_id"]).as_posix()),
        "current_focus": args.focus or "",
        "completed": [],
        "in_progress": [],
        "blockers": [],
        "next_steps": [],
        "key_decisions": [],
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


def heartbeat_command(args: argparse.Namespace) -> None:
    specs = scan_specs()
    spec = find_spec(specs, args.spec)
    if spec["status"] in ("Completed", "Deprecated"):
        raise RegistryError(f"{spec['id']} is {spec['status']}; cannot publish a heartbeat for an inactive SPEC")
    uas = build_uas(spec, args)
    SYNC_DIR.mkdir(exist_ok=True)
    path = heartbeat_path(spec["id"])
    write_json_atomic(path, uas)
    sync_heartbeats(quiet=True)
    print(f"heartbeat published: {path}")


def heartbeats_command(args: argparse.Namespace) -> None:
    states = load_heartbeats()
    if args.json:
        print(json.dumps({"heartbeats": states}, ensure_ascii=False, indent=2))
    else:
        for s in states:
            mode = "relay" if not s.get("sender_continues") else "concurrent"
            print(f"{s['task_id']:12} {s.get('epic', 'default'):24} {s.get('agent_tool', '?'):16} {s.get('current_focus', '')[:50]}")
        if not states:
            print("No active heartbeats.")
    sync_heartbeats(quiet=True)


def watch_command(args: argparse.Namespace) -> None:
    """Cross-platform polling watcher. Replaces fswatch/inotify."""
    SYNC_DIR.mkdir(exist_ok=True)
    pid_file = SYNC_DIR / "watcher.pid"
    if pid_file.exists():
        try:
            old_pid = int(pid_file.read_text().strip())
            os.kill(old_pid, 0)
            print(f"watcher already running (PID {old_pid})")
            return
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create .specs and initial generated files")
    init_parser.set_defaults(handler=init_command)

    new_parser = subparsers.add_parser("new", help="create the next sequential SPEC")
    new_parser.add_argument("--title", required=True)
    new_parser.add_argument("--task-id", required=True)
    new_parser.add_argument("--epic", required=True, dest="epic_id", help="Epic identifier used to reuse one worktree")
    new_parser.add_argument("--owner", required=True)
    new_parser.add_argument("--summary", required=True)
    new_parser.add_argument("--module", action="append", default=[], dest="modules")
    new_parser.add_argument("--file", action="append", default=[], dest="files")
    new_parser.add_argument("--api", action="append", default=[], dest="api_endpoints")
    new_parser.add_argument("--db", action="append", default=[], dest="db_entities")
    new_parser.add_argument("--depends-on", action="append", default=[], dest="depends_on")
    new_parser.add_argument("--blocks", action="append", default=[])
    new_parser.add_argument("--breaking-changes", action="store_true")
    new_parser.add_argument("--open", action="store_true", help="open the created file with EDITOR")
    new_parser.set_defaults(handler=new_command)

    status_set_parser = subparsers.add_parser("set-status", help="change a SPEC lifecycle status")
    status_set_parser.add_argument("--id", required=True)
    status_set_parser.add_argument("--status", required=True, choices=STATUSES)
    status_set_parser.set_defaults(handler=set_status_command)

    sync_parser = subparsers.add_parser("sync", help="scan markdown and regenerate registry/overview")
    sync_parser.set_defaults(handler=lambda _args: sync())

    status_parser = subparsers.add_parser("status", help="show a concise SPEC ledger")
    status_parser.add_argument("--format", choices=("table", "json"), default="table")
    status_parser.set_defaults(handler=status_command)

    check_parser = subparsers.add_parser("check", help="check intended scope against existing SPECs")
    check_parser.add_argument("--module", action="append", default=[], dest="modules")
    check_parser.add_argument("--file", action="append", default=[], dest="files")
    check_parser.add_argument("--api", action="append", default=[], dest="api_endpoints")
    check_parser.add_argument("--db", action="append", default=[], dest="db_entities")
    check_parser.add_argument("--all", action="store_true", help="include Completed and Deprecated SPECs")
    check_parser.add_argument("--json", action="store_true")
    check_parser.set_defaults(handler=check_command)

    attach_parser = subparsers.add_parser("attach", help="create or reuse an Epic worktree for a SPEC")
    attach_parser.add_argument("--spec", required=True)
    attach_parser.add_argument("--base", default="HEAD", help="Git revision to branch from when creating a worktree")
    attach_parser.set_defaults(handler=attach_command)

    scope_parser = subparsers.add_parser(
        "check-scope",
        help="compare changed files with a SPEC's declared impact scope",
        description="Development-time warnings are the default; use --strict in CI/review gates.",
    )
    scope_parser.add_argument("--spec", required=True)
    scope_parser.add_argument("--base", default="HEAD", help="Git diff base; use main or origin/main for review")
    scope_parser.add_argument("--worktree", help="path to an Epic worktree; defaults to the current directory")
    scope_parser.add_argument("--strict", action="store_true", help="exit nonzero on out-of-scope changes (CI gate)")
    scope_parser.add_argument("--json", action="store_true")
    scope_parser.set_defaults(handler=check_scope_command)

    finish_parser = subparsers.add_parser("finish", help="remove an Epic worktree after all its SPECs are merged/completed")
    finish_parser.add_argument("--epic", required=True)
    finish_parser.add_argument("--base", default="main", help="branch that must already contain the Epic branch")
    finish_parser.set_defaults(handler=finish_command)

    worktrees_parser = subparsers.add_parser("worktrees", help="show Epic-to-worktree mappings and activity")
    worktrees_parser.set_defaults(handler=worktrees_command)

    heartbeat_parser = subparsers.add_parser("heartbeat", help="publish a UAS runtime heartbeat for a SPEC")
    heartbeat_parser.add_argument("--spec", required=True)
    heartbeat_parser.add_argument("--focus", required=True, help="one-sentence current focus")
    heartbeat_parser.add_argument("--tool", default="unknown", help="agent tool name (codex/claude-code/zcode/...)")
    heartbeat_parser.add_argument("--model", default="unknown", help="model name")
    heartbeat_parser.add_argument("--mode", choices=("concurrent", "relay"), default="concurrent")
    heartbeat_parser.add_argument("--context-level", type=int, default=50)
    heartbeat_parser.add_argument("--notes", default="")
    heartbeat_parser.set_defaults(handler=heartbeat_command)

    heartbeats_parser = subparsers.add_parser("heartbeats", help="list active UAS heartbeats and refresh merged view")
    heartbeats_parser.add_argument("--json", action="store_true")
    heartbeats_parser.set_defaults(handler=heartbeats_command)

    watch_parser = subparsers.add_parser("watch", help="cross-platform .sync watcher (polling)")
    watch_parser.add_argument("--interval", type=float, default=5.0, help="poll interval in seconds")
    watch_parser.set_defaults(handler=watch_command)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
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
