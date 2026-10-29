# teamwork 安装脚本（Windows PowerShell）
#
#   .\install\install.ps1                         安装为 Claude Code 个人技能
#   .\install\install.ps1 -Mode dsh               安装到 DeepSeek Harness 技能目录
#   .\install\install.ps1 -Mode dest -Dest D:\my-skills   自定义父目录
#   .\install\install.ps1 -Force -Test            覆盖安装并自检
#
# 环境变量：CLAUDE_SKILLS_DIR / DSH_SKILLS_DIR / PYTHON / TEAMWORK_RUNS_ROOT
[CmdletBinding()]
param(
    [ValidateSet("claude", "dsh", "dest")]
    [string]$Mode = "claude",
    [string]$Dest = "",
    [switch]$Force,
    [switch]$Test
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Src = Join-Path $RepoRoot "skills\teamwork"

switch ($Mode) {
    "claude" {
        $parent = if ($env:CLAUDE_SKILLS_DIR) { $env:CLAUDE_SKILLS_DIR } else { Join-Path $HOME ".claude\skills" }
    }
    "dsh" {
        $parent = if ($env:DSH_SKILLS_DIR) { $env:DSH_SKILLS_DIR } else { "D:\apps\deepseek-harness\data\skills" }
    }
    "dest" {
        if (-not $Dest) { throw "-Mode dest 需要 -Dest 目录参数" }
        $parent = $Dest
    }
}

$target = Join-Path $parent "teamwork"

# 选择 Python
$py = $null
$candidates = @()
if ($env:PYTHON) { $candidates += $env:PYTHON }
$candidates += @("python", "python3", "py")
foreach ($c in $candidates) {
    if ($c -and (Get-Command $c -ErrorAction SilentlyContinue)) { $py = $c; break }
}
if (-not $py) { throw "找不到 Python。请安装 Python 3.10+ 并确保在 PATH 中，或用 `$env:PYTHON 指定。" }

& $py -c "import yaml" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Python 缺少 PyYAML。请先运行：$py -m pip install pyyaml"
}

if (Test-Path $target) {
    if (-not $Force) {
        throw "目标已存在：$target。如需覆盖请加 -Force（会先备份为 $target.backup-<时间戳>）"
    }
    $backup = "$target.backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Move-Item $target $backup
    Write-Host "[ok] 已备份旧版本到 $backup"
}

New-Item -ItemType Directory -Path $parent -Force | Out-Null
Copy-Item -Path $Src -Destination $target -Recurse -Force
Get-ChildItem -Path $target -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $target -Recurse -Include "*.pyc", "*.pyo" |
    Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "[ok] 已安装 teamwork -> $target"
& $py (Join-Path $target "scripts\orchestrator.py") --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "安装后命令行入口不可用（orchestrator.py --help 失败）" }
Write-Host "[ok] 命令行入口可用"

if ($Test) {
    $testRoot = Join-Path $parent ".teamwork-selftest"
    Write-Host "[..] 运行自检（TEAMWORK_RUNS_ROOT=$testRoot）"
    $env:TEAMWORK_RUNS_ROOT = $testRoot
    & $py (Join-Path $target "scripts\selftest.py")
    if ($LASTEXITCODE -ne 0) { throw "自检失败" }
    Remove-Item -Recurse -Force $testRoot -ErrorAction SilentlyContinue
    Write-Host "[ok] 自检通过并已清理临时目录"
}

Write-Host ""
Write-Host "安装完成。接下来："
Write-Host "  Claude Code: 新开会话，输入 /teamwork:run N=3 <任务>；或直接说“用 teamwork 跑……”"
Write-Host "  DeepSeek Harness: 新开会话，输入  teamwork, N=3 <任务>"
Write-Host "  纯命令行: $py `"$target\scripts\orchestrator.py`" --help"
