#!/usr/bin/env python3
"""MCP server exposing spec-registry operations to Claude Code, Cursor, Windsurf.

Install:  pip install mcp
Register as a stdio MCP server pointing to this file.

Exposes four tools:
    spec_create       new SPEC with impact scope
    workspace_attach  enter Epic worktree
    scope_verify      validate changed files against declared scope
    state_publish     publish concurrent heartbeat

FIX: scope_verify now uses _call_cli (unified code path) because
check_scope_command returns an int exit code instead of calling sys.exit().
The old direct sr.*() calls that bypassed the CLI are removed.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

# Import the CLI module by path so the server works from any cwd.
import importlib.util

_cli_path = str(Path(__file__).parent / "spec_registry.py")
_spec = importlib.util.spec_from_file_location("spec_registry", _cli_path)
sr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sr)

app = Server("spec-registry")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="spec_create",
            description=(
                "Create the next sequential SPEC with impact scope and epic assignment. "
                "Automatically assigns the next sequential ID and refreshes registry.json."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title":   {"type": "string"},
                    "task_id": {"type": "string"},
                    "epic":    {"type": "string"},
                    "owner":   {"type": "string"},
                    "summary": {"type": "string"},
                    "modules": {"type": "array", "items": {"type": "string"}, "default": []},
                    "files":   {"type": "array", "items": {"type": "string"}, "default": []},
                    "api_endpoints": {"type": "array", "items": {"type": "string"}, "default": []},
                    "db_entities":   {"type": "array", "items": {"type": "string"}, "default": []},
                    "depends_on":    {"type": "array", "items": {"type": "string"}, "default": []},
                    "breaking_changes": {"type": "boolean", "default": False},
                },
                "required": ["title", "task_id", "epic", "owner", "summary"],
            },
        ),
        Tool(
            name="workspace_attach",
            description=(
                "Create or reuse the Epic worktree for a given SPEC and move it from Draft "
                "to In-Progress. Verifies there are no file-level conflicts inside the Epic "
                "before creating the worktree."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {"type": "string"},
                    "base":    {"type": "string", "default": "HEAD"},
                },
                "required": ["spec_id"],
            },
        ),
        Tool(
            name="scope_verify",
            description=(
                "Check files changed in the current worktree against the SPEC impact_scope. "
                "Returns allowed and violation lists. strict=true causes 'blocked: true' and "
                "is suitable for CI gating. "
                "Note: api_endpoints and db_entities are semantic scope only; "
                "this tool validates physical files and modules."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id":  {"type": "string"},
                    "base":     {"type": "string", "default": "HEAD"},
                    "worktree": {"type": "string"},
                    "strict":   {"type": "boolean", "default": False},
                },
                "required": ["spec_id"],
            },
        ),
        Tool(
            name="state_publish",
            description=(
                "Publish a lightweight concurrent heartbeat for an active SPEC. "
                "For relay handoff (richer context transfer), use the peer-relay-v3 skill's "
                "'handoff' command instead."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id":       {"type": "string"},
                    "focus":         {"type": "string"},
                    "tool":          {"type": "string", "default": "unknown"},
                    "model":         {"type": "string", "default": "unknown"},
                    "context_level": {"type": "integer", "default": 50},
                    "notes":         {"type": "string", "default": ""},
                },
                "required": ["spec_id", "focus"],
            },
        ),
    ]


class MCPRegistryError(Exception):
    """Wrap RegistryError for JSON-RPC error responses."""


def _call_cli(args_list: list[str]) -> tuple[int, str, str]:
    """Run spec_registry main() in-process; return (exit_code, stdout, stderr).

    FIX: Captures SystemExit (including from check-scope violations in strict
    mode) instead of letting it propagate and kill the MCP server process.
    """
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_argv = sys.argv[:]
    exit_code = 0
    try:
        sys.argv = ["spec_registry.py", *args_list]
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            exit_code = sr.main()
    except SystemExit as exc:
        exit_code = int(exc.code) if exc.code is not None else 0
    finally:
        sys.argv = old_argv
    return exit_code, stdout_buf.getvalue().strip(), stderr_buf.getvalue().strip()


def _ok(output: str, **extra) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"success": True, "output": output, **extra}))]


def _err(message: str) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"success": False, "error": message}))]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "spec_create":
            args = [
                "new",
                "--title",   arguments["title"],
                "--task-id", arguments["task_id"],
                "--epic",    arguments["epic"],
                "--owner",   arguments["owner"],
                "--summary", arguments["summary"],
            ]
            for m in arguments.get("modules", []):
                args += ["--module", m]
            for f in arguments.get("files", []):
                args += ["--file", f]
            for a in arguments.get("api_endpoints", []):
                args += ["--api", a]
            for d in arguments.get("db_entities", []):
                args += ["--db", d]
            for dep in arguments.get("depends_on", []):
                args += ["--depends-on", dep]
            if arguments.get("breaking_changes"):
                args.append("--breaking-changes")
            code, out, err = _call_cli(args)
            if code != 0:
                return _err(err or out)
            return _ok(out)

        elif name == "workspace_attach":
            args = ["attach", "--spec", arguments["spec_id"]]
            if arguments.get("base"):
                args += ["--base", arguments["base"]]
            code, out, err = _call_cli(args)
            if code != 0:
                return _err(err or out)
            return _ok(out)

        elif name == "scope_verify":
            # FIX: Now uses _call_cli uniformly. check_scope_command returns exit
            # code 3 on strict violations (not sys.exit), so it no longer kills
            # the MCP server process.
            args = ["check-scope", "--spec", arguments["spec_id"], "--json"]
            if arguments.get("base"):
                args += ["--base", arguments["base"]]
            if arguments.get("worktree"):
                args += ["--worktree", arguments["worktree"]]
            if arguments.get("strict"):
                args.append("--strict")
            code, out, err = _call_cli(args)
            # exit code 3 = violations in strict mode (expected, not a crash)
            # exit code 2 = RegistryError (SPEC not found, etc.)
            if code == 2:
                return _err(err or out)
            try:
                payload = json.loads(out)
            except json.JSONDecodeError:
                payload = {"raw_output": out}
            payload["blocked"] = (code == 3)
            return [TextContent(type="text", text=json.dumps({"success": True, **payload}))]

        elif name == "state_publish":
            args = [
                "heartbeat",
                "--spec",          arguments["spec_id"],
                "--focus",         arguments["focus"],
                "--tool",          arguments.get("tool", "unknown"),
                "--model",         arguments.get("model", "unknown"),
                "--context-level", str(arguments.get("context_level", 50)),
                "--notes",         arguments.get("notes", ""),
            ]
            code, out, err = _call_cli(args)
            if code != 0:
                return _err(err or out)
            return _ok(out)

        else:
            return _err(f"unknown tool: {name}")

    except Exception as exc:  # noqa: BLE001
        return _err(str(exc))


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
