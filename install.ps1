#Requires -Version 5.1
<#
.SYNOPSIS
    One-command installer for spec-registry skill.
.DESCRIPTION
    Copies this folder to Codex and/or Claude Code skills directories.
    Detects Python, verifies CLI compiles, and reports next steps.
#>

$ErrorActionPreference = "Stop"

$SkillName = "spec-registry"
$SourceDir = $PSScriptRoot

Write-Host ""
Write-Host "=== spec-registry installer ===" -ForegroundColor Cyan
Write-Host "source: $SourceDir"

# Verify required files exist
$required = @("SKILL.md", "scripts\spec_registry.py")
foreach ($file in $required) {
    if (-not (Test-Path (Join-Path $SourceDir $file))) {
        Write-Host "[ERROR] missing required file: $file" -ForegroundColor Red
        exit 1
    }
}

# Check Python
Write-Host "`n[ checking Python ]"
$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "^Python 3\.") {
            $pythonCmd = $cmd
            break
        }
    } catch { continue }
}
if ($pythonCmd) {
    Write-Host "  [OK] $(& $pythonCmd --version)" -ForegroundColor Green
} else {
    Write-Host "  [WARN] Python 3 not found; the skill requires Python to run" -ForegroundColor Yellow
}

# Compile check
if ($pythonCmd) {
    Write-Host "`n[ compile check ]"
    $cliPath = Join-Path $SourceDir "scripts\spec_registry.py"
    & $pythonCmd -m py_compile $cliPath 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] spec_registry.py compiles" -ForegroundColor Green
    } else {
        Write-Host "  [ERROR] spec_registry.py failed to compile" -ForegroundColor Red
        exit 1
    }
}

# Determine install targets
$targets = @()

$codexSkills = if ($env:USERPROFILE) {
    Join-Path $env:USERPROFILE ".codex\skills\$SkillName"
} else {
    Join-Path $HOME ".codex\skills\$SkillName"
}
$targets += @{ Path = $codexSkills; Label = "Codex" }

$claudeSkills = if ($env:USERPROFILE) {
    Join-Path $env:USERPROFILE ".claude\skills\$SkillName"
} else {
    Join-Path $HOME ".claude\skills\$SkillName"
}
if (Test-Path (Split-Path $claudeSkills)) {
    $targets += @{ Path = $claudeSkills; Label = "Claude Code" }
}

# Install to each target
Write-Host "`n[ installing ]"
foreach ($target in $targets) {
    $dest = $target.Path
    $label = $target.Label
    try {
        New-Item -ItemType Directory -Force -Path $dest | Out-Null
        Copy-Item -Path (Join-Path $SourceDir "*") -Destination $dest -Recurse -Force
        # Remove __pycache__ from destination if present
        Get-ChildItem -Path "$dest\scripts" -Filter "*.pyc" -ErrorAction SilentlyContinue |
            Remove-Item -Force
        Write-Host "  [OK] installed to $label -> $dest" -ForegroundColor Green
    } catch {
        Write-Host "  [WARN] could not write to $label ($($_.Exception.Message.Trim()))" -ForegroundColor Yellow
        Write-Host "         manual copy: robocopy `"$SourceDir`" `"$dest`" /E" -ForegroundColor Yellow
    }
}

# MCP optional check
Write-Host "`n[ MCP server (optional) ]"
if ($pythonCmd) {
    & $pythonCmd -c "import mcp" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] mcp package installed; MCP server ready" -ForegroundColor Green
    } else {
        Write-Host "  [INFO] for Claude Code/Cursor/Windsurf integration:" -ForegroundColor Gray
        Write-Host "         pip install mcp" -ForegroundColor Gray
        Write-Host "         register scripts/mcp_server.py as a stdio server" -ForegroundColor Gray
    }
}

Write-Host "`n=== done ===" -ForegroundColor Cyan
Write-Host "restart your AI tool to pick up the new skill."
Write-Host ""
