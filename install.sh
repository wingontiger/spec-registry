#!/usr/bin/env bash
# One-command installer for spec-registry skill (macOS/Linux).

set -euo pipefail

SKILL_NAME="spec-registry"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "=== spec-registry installer ==="
echo "source: ${SOURCE_DIR}"

# Verify required files
for f in SKILL.md scripts/spec_registry.py; do
    if [ ! -f "${SOURCE_DIR}/${f}" ]; then
        echo "[ERROR] missing required file: ${f}"
        exit 1
    fi
done

# Check Python
echo ""
echo "[ checking Python ]"
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null && "$cmd" --version 2>&1 | grep -q "^Python 3"; then
        PYTHON_CMD="$cmd"
        break
    fi
done
if [ -n "$PYTHON_CMD" ]; then
    echo "  [OK] $($PYTHON_CMD --version)"
else
    echo "  [WARN] Python 3 not found; the skill requires Python to run"
fi

# Compile check
if [ -n "$PYTHON_CMD" ]; then
    echo ""
    echo "[ compile check ]"
    if "$PYTHON_CMD" -m py_compile "${SOURCE_DIR}/scripts/spec_registry.py" 2>/dev/null; then
        echo "  [OK] spec_registry.py compiles"
    else
        echo "  [ERROR] spec_registry.py failed to compile"
        exit 1
    fi
fi

# Install targets
echo ""
echo "[ installing ]"
TARGETS=(
    "${HOME}/.codex/skills/${SKILL_NAME}"
)

# Add Claude Code target if its skills directory exists
if [ -d "${HOME}/.claude/skills" ]; then
    TARGETS+=("${HOME}/.claude/skills/${SKILL_NAME}")
fi

for dest in "${TARGETS[@]}"; do
    mkdir -p "$dest"
    cp -R "${SOURCE_DIR}/"* "$dest/"
    # Clean pycache
    find "$dest/scripts" -name "*.pyc" -delete 2>/dev/null || true
    find "$dest/scripts" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    label="unknown"
    [[ "$dest" == *".codex"* ]] && label="Codex"
    [[ "$dest" == *".claude"* ]] && label="Claude Code"
    echo "  [OK] installed to ${label} -> ${dest}"
done

# MCP optional check
echo ""
echo "[ MCP server (optional) ]"
if [ -n "$PYTHON_CMD" ]; then
    if "$PYTHON_CMD" -c "import mcp" 2>/dev/null; then
        echo "  [OK] mcp package installed; MCP server ready"
    else
        echo "  [INFO] for Claude Code/Cursor/Windsurf integration:"
        echo "         pip install mcp"
        echo "         register scripts/mcp_server.py as a stdio server"
    fi
fi

echo ""
echo "=== done ==="
echo "restart your AI tool to pick up the new skill."
echo ""
