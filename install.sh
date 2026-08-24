#!/usr/bin/env bash
# spec-registry install script
# Works from a local clone or via: curl -sSL <raw_url>/install.sh | bash

set -euo pipefail

SKILL_NAME="spec-registry"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || pwd)"

# ── Locate install base ──────────────────────────────────────────────────────
if [[ -n "${CLAUDE_SKILLS_DIR:-}" ]]; then
    INSTALL_BASE="$CLAUDE_SKILLS_DIR"
elif [[ -d "$HOME/.claude/skills" ]]; then
    INSTALL_BASE="$HOME/.claude/skills"
elif [[ -d "$HOME/.codex/skills" ]]; then
    INSTALL_BASE="$HOME/.codex/skills"
else
    INSTALL_BASE="$HOME/.claude/skills"
fi

INSTALL_DIR="$INSTALL_BASE/$SKILL_NAME"

# ── If running from pipe (curl | bash), clone from GitHub first ──────────────
if [[ ! -f "$SCRIPT_DIR/SKILL.md" ]]; then
    REPO_URL="https://github.com/wingontiger/spec-registry"
    TMP_DIR="$(mktemp -d)"
    echo "Cloning $SKILL_NAME from $REPO_URL ..."
    git clone --depth 1 "$REPO_URL" "$TMP_DIR/$SKILL_NAME"
    SCRIPT_DIR="$TMP_DIR/$SKILL_NAME"
fi

# ── Install ──────────────────────────────────────────────────────────────────
echo "Installing $SKILL_NAME → $INSTALL_DIR"
mkdir -p "$INSTALL_DIR/scripts"

cp "$SCRIPT_DIR/SKILL.md"  "$INSTALL_DIR/"
cp "$SCRIPT_DIR/README.md" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/scripts/spec_registry.py" "$INSTALL_DIR/scripts/"
cp "$SCRIPT_DIR/scripts/mcp_server.py"    "$INSTALL_DIR/scripts/"

# ── Verify Python ────────────────────────────────────────────────────────────
if command -v python3 &>/dev/null; then
    python3 -c "import ast; ast.parse(open('$INSTALL_DIR/scripts/spec_registry.py').read())" \
        && echo "  python3 syntax OK" \
        || echo "  WARNING: spec_registry.py syntax check failed"
else
    echo "  NOTE: python3 not found — install Python 3.9+ before using this skill"
fi

echo ""
echo "✅  $SKILL_NAME installed to $INSTALL_DIR"
echo ""
echo "Quick start:"
echo "  cd your-project"
echo "  python3 \$INSTALL_DIR/scripts/spec_registry.py init"
echo ""
echo "MCP server (Claude Code / Cursor / Windsurf):"
echo "  pip install mcp"
echo "  # register $INSTALL_DIR/scripts/mcp_server.py as a stdio MCP server"
