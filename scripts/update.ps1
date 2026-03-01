# ═══════════════════════════════════════════════════════════════
#   HydraBot Updater (PowerShell)
#   Usage:  powershell -ExecutionPolicy Bypass -File scripts\update.ps1
# ═══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

# ── Colors ─────────────────────────────────────────────────────
function Green ($t)  { Write-Host "  $t" -ForegroundColor Green }
function Yellow($t)  { Write-Host "  $t" -ForegroundColor Yellow }
function Red   ($t)  { Write-Host "  $t" -ForegroundColor Red }
function Cyan  ($t)  { Write-Host "  $t" -ForegroundColor Cyan }
function DGray ($t)  { Write-Host "  $t" -ForegroundColor DarkGray }
function Hr    ()    { Write-Host ("`n" + "─"*50 + "`n") -ForegroundColor DarkGray }
function Ok    ($t)  { Green  "✓ $t" }
function Warn  ($t)  { Yellow "⚠ $t" }
function Err   ($t)  { Red    "✗ $t"; exit 1 }
function Inf   ($t)  { Cyan   "ℹ $t" }

$REPO = "https://raw.githubusercontent.com/Adaimade/HydraBot/main"

# ── Detect install directory ───────────────────────────────────
$SCRIPT_DIR = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $SCRIPT_DIR

# Verify we're in a HydraBot directory
if (-not ((Test-Path "main.py") -and (Test-Path "agent.py") -and (Test-Path "requirements.txt"))) {
    Err "请在 HydraBot 安装目录下运行此脚本"
}

# ── Banner ─────────────────────────────────────────────────────
Write-Host "`n" -ForegroundColor Cyan
Write-Host "  🐍 HydraBot Updater" -ForegroundColor Cyan
Hr

# ── Version check ──────────────────────────────────────────────
$LOCAL_VER = if (Test-Path "VERSION") { (Get-Content "VERSION").Trim() } else { "unknown" }

$REMOTE_VER = try {
    (Invoke-WebRequest -Uri "$REPO/VERSION" -UseBasicParsing -TimeoutSec 3).Content.Trim()
} catch {
    "unknown"
}

Inf "当前版本: $LOCAL_VER"
Inf "最新版本: $REMOTE_VER"

if ($LOCAL_VER -eq $REMOTE_VER -and $LOCAL_VER -ne "unknown") {
    Write-Host ""
    Green "✨ 已是最新版本！"
    DGray "如需强制更新，请运行: powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Force"
    Write-Host ""
    if ($args -notcontains "-Force") { exit 0 }
}

Write-Host ""
Yellow "即将更新以下核心文件（config.json / 自定义 tools / memory 不受影响）:"
Write-Host "  agent.py  bot.py  main.py  tools_builtin.py  requirements.txt  scripts\update.ps1  hydrabot.bat  VERSION" -ForegroundColor DarkGray
Write-Host ""

$confirm = Read-Host "继续更新？[Y/n]"
if ($confirm -match "^[Nn]$") {
    Write-Host "  已取消。`n" -ForegroundColor DarkGray
    exit 0
}
Write-Host ""

# ── Backup config ──────────────────────────────────────────────
if (Test-Path "config.json") {
    Copy-Item "config.json" "config.json.bak"
    Ok "已备份 config.json → config.json.bak"
}

# ── Count existing tools (before update) ───────────────────────
$OLD_TOOLS = if (Test-Path "tools_builtin.py") {
    ((Select-String '^\s+\(' "tools_builtin.py" -AllMatches).Matches.Count)
} else {
    "?"
}

# ── Download updates ───────────────────────────────────────────
Write-Host "  📥 下载更新..."
Hr

$CORE_FILES = @("agent.py","bot.py","main.py","tools_builtin.py","requirements.txt","scripts/update.ps1","hydrabot.bat","VERSION")
$FAILED = @()

New-Item -ItemType Directory -Force -Path "scripts" | Out-Null
foreach ($f in $CORE_FILES) {
    Write-Host "  $($f.PadRight(30))" -NoNewline
    try {
        $uri = "$REPO/$f"
        $tempFile = "$f.tmp"
        Invoke-WebRequest -Uri $uri -OutFile $tempFile -UseBasicParsing -TimeoutSec 10 | Out-Null
        Move-Item $tempFile $f -Force
        Write-Host "✓" -ForegroundColor Green
    } catch {
        if (Test-Path "$f.tmp") { Remove-Item "$f.tmp" -Force }
        Write-Host "⚠ (保留旧版)" -ForegroundColor Yellow
        $FAILED += $f
    }
}

# ── Update dependencies ────────────────────────────────────────
Write-Host "`n  📦 更新 Python 依赖...`n" -ForegroundColor Cyan

$PYTHON = $null
foreach ($cmd in @("python", "python3")) {
    try {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $PYTHON = $cmd
            break
        }
    } catch {}
}

if ($PYTHON) {
    # Activate venv if exists
    $VENV_ACTIVATE = if (Test-Path "venv\Scripts\activate.ps1") {
        "venv\Scripts\activate.ps1"
    } elseif (Test-Path "venv\bin\activate") {
        "venv\bin\activate"
    } else {
        $null
    }

    if ($VENV_ACTIVATE) {
        & $VENV_ACTIVATE
    }

    & $PYTHON -m pip install -r requirements.txt -q --upgrade --disable-pip-version-check
    Ok "依赖已更新"
} else {
    Warn "找不到 Python，跳过依赖更新"
}

# ── Show new tools ────────────────────────────────────────────
$NEW_TOOLS = if (Test-Path "tools_builtin.py") {
    ((Select-String '^\s+\(' "tools_builtin.py" -AllMatches).Matches.Count)
} else {
    "?"
}

$NEW_VER = if (Test-Path "VERSION") { (Get-Content "VERSION").Trim() } else { "unknown" }

Write-Host ""
Hr

Write-Host "  ✨ 更新完成！" -ForegroundColor Green
Write-Host ""
Write-Host "  版本:    " -NoNewline
Write-Host "$LOCAL_VER" -ForegroundColor DarkGray -NoNewline
Write-Host "  →  " -NoNewline
Write-Host "$NEW_VER" -ForegroundColor Green

if ($OLD_TOOLS -ne "?" -and $NEW_TOOLS -ne "?") {
    $DIFF = [int]$NEW_TOOLS - [int]$OLD_TOOLS
    if ($DIFF -gt 0) {
        Write-Host "  内建工具: " -NoNewline
        Write-Host "$OLD_TOOLS" -ForegroundColor DarkGray -NoNewline
        Write-Host "  →  " -NoNewline
        Write-Host "$NEW_TOOLS" -ForegroundColor Green -NoNewline
        Write-Host "  " -NoNewline
        Write-Host "(+$DIFF 新工具)" -ForegroundColor Green
    } else {
        Write-Host "  内建工具: " -NoNewline
        Write-Host "$NEW_TOOLS 个" -ForegroundColor Green
    }
}

if ($FAILED.Count -gt 0) {
    Warn "以下文件下载失败，已保留旧版: $($FAILED -join ', ')"
}

Write-Host ""
Cyan "重启 Bot 以应用更新"
Write-Host ""
