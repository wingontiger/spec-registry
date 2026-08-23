#!/usr/bin/env python3
"""Minimal MCP server exposing spec-registry operations to non-Codex tools.

Uses the Model Context Protocol stdio transport. Install with:
    pip install mcp

Register with Claude Code / Cursor / Windsurf as a stdio server:
    python <skill-folder>/scripts/mcp_server.py

Exposes four tools matching the Gemini proposal:
    spec_create, workspace_attach, scope_verify, state_publish
"""

from __future__ import annotations

import argparse
import json
import sys
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

app = Server("spec-registry-harness")


@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="spec_create",
            description="Create the next sequential SPEC with impact scope and epic assignment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "task_id": {"type": "string"},
                    "epic": {"type": "string"},
                    "owner": {"type": "string"},
                    "summary": {"type": "string"},
                    "modules": {"type": "array", "items": {"type": "string"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "task_id", "epic", "owner", "summary"],
            },
        ),
        Tool(
            name="workspace_attach",
            description="Create or reuse an Epic worktree for the given SPEC and move it to In-Progress.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {"type": "string"},
                    "base": {"type": "string", "default": "HEAD"},
                },
                "required": ["spec_id"],
            },
        ),
        Tool(
            name="scope_verify",
            description="Check changed files against SPEC impact_scope. Returns violations; strict mode blocks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {"type": "string"},
                    "base": {"type": "string", "default": "HEAD"},
                    "worktree": {"type": "string"},
                    "strict": {"type": "boolean", "default": False},
                },
                "required": ["spec_id"],
            },
        ),
        Tool(
            name="state_publish",
            description="Publish a UAS heartbeat for an active SPEC.",
            inputSchema={
                "type": "object",
                "properties": {
                    "spec_id": {"type": "string"},
                    "focus": {"type": "string"},
                    "tool": {"type": "string", "default": "unknown"},
                    "model": {"type": "string", "default": "unknown"},
                    "mode": {"type": "string", "enum": ["concurrent", "relay"], "default": "concurrent"},
                    "context_level": {"type": "integer", "default": 50},
                },
                "required": ["spec_id", "focus"],
            },
        ),
    ]


class MCPRegistryError(Exception):
    """Wrap RegistryError for JSON-RPC error responses."""


def _call_cli(args_list: list[str]) -> dict:
    """Run spec_registry.py main() in-process and capture output."""
    import io
    from contextlib import redirect_stdout, redirect_stderr
    import os

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    old_argv = sys.argv[1:]
    try:
        sys.argv[1:] = args_list
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            code = sr.main()
        if code != 0:
            raise MCPRegistryError(stderr_capture.getvalue().strip())
        return {"success": True, "output": stdout_capture.getvalue().strip()}
    except sr.RegistryError as e:
        raise MCPRegistryError(str(e)) from None
    finally:
        sys.argv[1:] = old_argv


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "spec_create":
            args = [
                "new",
                "--title", arguments["title"],
                "--task-id", arguments["task_id"],
                "--epic", arguments["epic"],
                "--owner", arguments["owner"],
                "--summary", arguments["summary"],
            ]
            for mod in arguments.get("modules", []):
                args.extend(["--module", mod])
            for f in arguments.get("files", []):
                args.extend(["--file", f])
            result = _call_cli(args)

        elif name == "workspace_attach":
            args = ["attach", "--spec", arguments["spec_id"]]
            if arguments.get("base"):
                args.extend(["--base", arguments["base"]])
            result = _call_cli(args)

        elif name == "scope_verify":
            args = ["check-scope", "--spec", arguments["spec_id"]]
            if arguments.get("base"):
                args.extend(["--base", arguments["base"]])
            if arguments.get("worktree"):
                args.extend(["--worktree", arguments["worktree"]])
            if arguments.get("strict"):
                args.append("--strict")
            args.append("--json")
            # check-scope exits nonzero on violations in strict mode;
            # we need the JSON regardless, so call scan directly.
            specs = sr.scan_specs()
            spec = sr.find_spec(specs, arguments["spec_id"])
            base = arguments.get("base") or "HEAD"
            wt = Path(arguments["worktree"]).resolve() if arguments.get("worktree") else None
            files = sr.changed_files(base, wt)
            violations = [f for f in files if not sr.scope_matches(f, spec["impact_scope"])[0]]
            allowed = [f for f in files if sr.scope_matches(f, spec["impact_scope"])[0]]
            blocked = bool(violations) and bool(arguments.get("strict"))
            result = {
                "success": not blocked,
                "spec": spec["id"],
                "changed_files": files,
                "allowed": allowed,
                "violations": violations,
                "blocked": blocked,
            }

        elif name == "state_publish":
            args = [
                "heartbeat",
                "--spec", arguments["spec_id"],
                "--focus", arguments["focus"],
                "--tool", arguments.get("tool", "unknown"),
                "--model", arguments.get("model", "unknown"),
                "--mode", arguments.get("mode", "concurrent"),
                "--context-level", str(arguments.get("context_level", 50)),
            ]
            result = _call_cli(args)

        else:
            raise MCPRegistryError(f"unknown tool: {name}")

        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]
    except MCPRegistryError as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(run())
