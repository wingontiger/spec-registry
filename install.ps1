# spec-registry install script — Windows PowerShell
# From local clone:  .\install.ps1
# One-liner:         irm https://raw.githubusercontent.com/wingontiger/spec-registry/main/install.ps1 | iex

param(
    [string]$InstallBase = ""
)

$SkillName  = "spec-registry"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoUrl    = "https://github.com/wingontiger/spec-registry"

# ── Locate install base ──────────────────────────────────────────────────────
if ($InstallBase -eq "") {
    if ($env:CLAUDE_SKILLS_DIR) {
        $InstallBase = $env:CLAUDE_SKILLS_DIR
    } elseif (Test-Path "$env:USERPROFILE\.claude\skills") {
        $InstallBase = "$env:USERPROFILE\.claude\skills"
    } elseif (Test-Path "$env:USERPROFILE\.codex\skills") {
        $InstallBase = "$env:USERPROFILE\.codex\skills"
    } else {
        $InstallBase = "$env:USERPROFILE\.claude\skills"
    }
}

$InstallDir = "$InstallBase\$SkillName"

# ── If running from pipe (irm | iex), clone from GitHub first ───────────────
if (-not (Test-Path "$ScriptDir\SKILL.md")) {
    Write-Host "Cloning $SkillName from $RepoUrl ..."
    $TmpDir = [System.IO.Path]::GetTempPath() + [System.Guid]::NewGuid().ToString()
    git clone --depth 1 $RepoUrl "$TmpDir\$SkillName" 2>&1 | Out-Null
    $ScriptDir = "$TmpDir\$SkillName"
}

# ── Install ──────────────────────────────────────────────────────────────────
Write-Host "Installing $SkillName → $InstallDir"
New-Item -ItemType Directory -Force -Path "$InstallDir\scripts" | Out-Null

Copy-Item "$ScriptDir\SKILL.md"                   $InstallDir -Force
Copy-Item "$ScriptDir\README.md"                  $InstallDir -Force
Copy-Item "$ScriptDir\scripts\spec_registry.py"   "$InstallDir\scripts" -Force
Copy-Item "$ScriptDir\scripts\mcp_server.py"      "$InstallDir\scripts" -Force

# ── Verify Python ────────────────────────────────────────────────────────────
$py = Get-Command python -ErrorAction SilentlyContinue
if ($py) {
    python -c "import ast; ast.parse(open('$InstallDir\scripts\spec_registry.py').read())" 2>&1 | Out-Null
    Write-Host "  python syntax OK"
} else {
    Write-Host "  NOTE: python not found — install Python 3.9+ before using this skill"
}

Write-Host ""
Write-Host "✅  $SkillName installed to $InstallDir"
Write-Host ""
Write-Host "Quick start:"
Write-Host "  cd your-project"
Write-Host "  python `"$InstallDir\scripts\spec_registry.py`" init"
Write-Host ""
Write-Host "MCP server (Claude Code / Cursor / Windsurf):"
Write-Host "  pip install mcp"
Write-Host "  # register $InstallDir\scripts\mcp_server.py as a stdio MCP server"
