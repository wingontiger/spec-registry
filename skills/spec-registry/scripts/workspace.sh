#!/usr/bin/env bash
# SPEC Registry v0.2 入口: 实际逻辑在 workspace.py (需要 python3 + pyyaml)
set -euo pipefail
exec python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/workspace.py" "$@"
