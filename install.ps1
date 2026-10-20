# spec-registry 一键安装 (Windows PowerShell 5.1+ / PowerShell 7)
# 注意: 此脚本没有在真实 Windows 环境验证过, 首次使用请先加 -DryRun 看一遍。
#
#   .\install.ps1                      安装 skill 到 ~\.claude\skills\spec-registry
#   .\install.ps1 -Init [-Dir 项目]     初始化项目(默认当前目录)
#   .\install.ps1 -All  [-Dir 项目]     两步一起做
#   .\install.ps1 -Uninstall [-Dir 项目]
# 选项: -SkillsDir  -WithCI  -DryRun  -From <目录或.zip>  -Repo OWNER/REPO  -Ref main
# 远程(公开仓库): irm https://raw.githubusercontent.com/OWNER/REPO/main/install.ps1 -OutFile i.ps1; .\i.ps1 -Repo OWNER/REPO -All
# 私有仓库: 先设置 $env:GITHUB_TOKEN
param(
  [switch]$Init, [switch]$All, [switch]$Uninstall, [string]$Dir = ".",
  [string]$SkillsDir = (Join-Path $HOME ".claude\skills"),
  [switch]$WithCI, [switch]$DryRun, [string]$From = "",
  [string]$Repo = $env:SPEC_REGISTRY_REPO, [string]$Ref = "main"
)
$ErrorActionPreference = "Stop"
$Name = "spec-registry"
function Info($m) { Write-Host "[INFO] $m" }
function Do($desc, [scriptblock]$sb) { if ($DryRun) { Write-Host "[DRY] $desc" } else { & $sb } }

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) { throw "需要 python 3" }
& $py.Source -c "import yaml" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Warning "缺少 pyyaml: 请运行  $($py.Source) -m pip install --user pyyaml" }

function Upsert-Block($file, $blockText, $begin, $end) {
  $txt = if (Test-Path $file) { [IO.File]::ReadAllText($file) } else { "" }
  $blk = $blockText.Trim()
  if ($txt.Contains($begin) -and $txt.Contains($end)) {
    $txt = [regex]::Replace($txt, [regex]::Escape($begin) + "(?s).*?" + [regex]::Escape($end), { param($m) $blk })
  } else { $txt = ($(if ($txt.Trim()) { $txt.TrimEnd() + "`n`n" } else { "" })) + $blk + "`n" }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
  [IO.File]::WriteAllText($file, $txt, (New-Object Text.UTF8Encoding($false)))
}
function Remove-Block($file, $begin, $end) {
  if (-not (Test-Path $file)) { return }
  $txt = [IO.File]::ReadAllText($file)
  $new = [regex]::Replace($txt, "\s*" + [regex]::Escape($begin) + "(?s).*?" + [regex]::Escape($end) + "\s*", "`n").Trim()
  if ($new) { [IO.File]::WriteAllText($file, $new + "`n", (New-Object Text.UTF8Encoding($false))) } else { Remove-Item $file }
}

# ---- 来源
$Src = $null; $Tmp = $null
if (-not $Uninstall) {
  $here = Split-Path -Parent $MyInvocation.MyCommand.Path
  if ($From) {
    if (Test-Path $From -PathType Container) { $Src = (Resolve-Path $From).Path }
    else { $Tmp = Join-Path $env:TEMP ("sr-" + [guid]::NewGuid()); Expand-Archive $From $Tmp; $Src = (Get-ChildItem $Tmp -Recurse -Directory -Filter skills | Select-Object -First 1).Parent.FullName }
  } elseif ($here -and (Test-Path (Join-Path $here "skills\$Name\SKILL.md"))) { $Src = $here }
  elseif ($Repo) {
    $Tmp = Join-Path $env:TEMP ("sr-" + [guid]::NewGuid()); New-Item -ItemType Directory $Tmp | Out-Null
    $zip = Join-Path $Tmp "src.zip"
    if ($env:GITHUB_TOKEN) { Invoke-WebRequest "https://api.github.com/repos/$Repo/zipball/$Ref" -Headers @{Authorization="Bearer $env:GITHUB_TOKEN"} -OutFile $zip }
    else { Invoke-WebRequest "https://codeload.github.com/$Repo/zip/$Ref" -OutFile $zip }
    Expand-Archive $zip (Join-Path $Tmp "x"); $Src = (Get-ChildItem (Join-Path $Tmp "x") -Recurse -Directory -Filter skills | Select-Object -First 1).Parent.FullName
  } else { throw "找不到安装来源: 请在仓库目录里运行, 或用 -From / -Repo 指定" }
  if (-not (Test-Path (Join-Path $Src "skills\$Name\SKILL.md"))) { throw "来源里没有 skills\$Name\SKILL.md" }
}

function Install-Skill {
  $dest = Join-Path $SkillsDir $Name
  Info "安装 skill -> $dest"
  Do "复制到 $dest" { New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null; if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }; Copy-Item -Recurse (Join-Path $Src "skills\$Name") $dest }
}

function Get-MainRoot($d) {
  $top = (git -C $d rev-parse --show-toplevel 2>$null); if (-not $top) { throw "$d 不是 git 仓库" }
  $common = (Resolve-Path (Join-Path $top (git -C $top rev-parse --git-common-dir))).Path
  return (Split-Path -Parent $common)
}

function Init-Project {
  $top = Get-MainRoot $Dir; Info "初始化项目: $top"
  $s = Join-Path $Src "skills\$Name"
  Do "复制脚本" { New-Item -ItemType Directory -Force -Path (Join-Path $top "scripts\spec-registry"), (Join-Path $top ".specs") | Out-Null; Copy-Item -Recurse -Force (Join-Path $s "scripts\*") (Join-Path $top "scripts\spec-registry"); if (-not (Test-Path (Join-Path $top ".specs\.gitkeep"))) { New-Item (Join-Path $top ".specs\.gitkeep") -ItemType File | Out-Null } }
  Do ".gitattributes" { Upsert-Block (Join-Path $top ".gitattributes") ([IO.File]::ReadAllText((Join-Path $s "templates\gitattributes.txt"))) "# spec-registry managed begin" "# spec-registry managed end" }
  $rules = [IO.File]::ReadAllText((Join-Path $s "templates\rules-block.md"))
  foreach ($rf in @("AGENTS.md", "CLAUDE.md", ".claude\CLAUDE.md")) {
    $p = Join-Path $top $rf
    if ($rf -eq "AGENTS.md" -or (Test-Path $p)) { Info "写入协作纪律 -> $rf"; Do "upsert $rf" { Upsert-Block $p $rules "<!-- spec-registry:begin -->" "<!-- spec-registry:end -->" } }
  }
  if ($WithCI) { Do "workflow" { New-Item -ItemType Directory -Force -Path (Join-Path $top ".github\workflows") | Out-Null; Copy-Item (Join-Path $s "templates\spec_registry.workflow.yml") (Join-Path $top ".github\workflows\spec_registry.yml") } }
  Info "安装 pre-commit hook"
  Do "install-hooks" { Push-Location $top; try { & $py.Source "scripts\spec-registry\workspace.py" install-hooks } finally { Pop-Location } }
  Info "完成。请提交: scripts/spec-registry/  .specs/  AGENTS.md  .gitattributes"
  Info "入口: scripts\spec-registry\workspace.cmd --help (需要先设置 SPEC_ROLE / SPEC_AGENT / SPEC_MODEL)"
}

function Do-Uninstall {
  Info "移除 skill: $(Join-Path $SkillsDir $Name)"
  Do "移除 skill" { Remove-Item -Recurse -Force (Join-Path $SkillsDir $Name) -ErrorAction SilentlyContinue }
  if ($PSBoundParameters.ContainsKey("Dir")) {
    $top = Get-MainRoot $Dir; Info "移除项目脚手架: $top (保留 .specs)"
    $ws = Join-Path $top "scripts\spec-registry\workspace.py"
    if ((Test-Path $ws) -and -not $DryRun) { Push-Location $top; try { & $py.Source $ws install-hooks --remove } finally { Pop-Location } }
    foreach ($rf in @("AGENTS.md", "CLAUDE.md", ".claude\CLAUDE.md")) { Do "移除 $rf 块" { Remove-Block (Join-Path $top $rf) "<!-- spec-registry:begin -->" "<!-- spec-registry:end -->" } }
    Do "移除 .gitattributes 块" { Remove-Block (Join-Path $top ".gitattributes") "# spec-registry managed begin" "# spec-registry managed end" }
    Do "移除脚本" { Remove-Item -Recurse -Force (Join-Path $top "scripts\spec-registry") -ErrorAction SilentlyContinue; Remove-Item (Join-Path $top ".github\workflows\spec_registry.yml") -ErrorAction SilentlyContinue }
  }
}

try {
  if ($Uninstall) { Do-Uninstall }
  elseif ($All) { Install-Skill; Init-Project }
  elseif ($Init) { Init-Project }
  else { Install-Skill }
} finally { if ($Tmp -and (Test-Path $Tmp)) { Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue } }
