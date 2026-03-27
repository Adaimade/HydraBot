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
    Err "請在 HydraBot 安裝目錄下執行此腳本"
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

Inf "目前版本: $LOCAL_VER"
Inf "最新版本: $REMOTE_VER"

if ($LOCAL_VER -eq $REMOTE_VER -and $LOCAL_VER -ne "unknown") {
    Write-Host ""
    Green "✨ 已是最新版本！"
    DGray "如需強制更新，請執行: powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -Force"
    Write-Host ""
    if ($args -notcontains "-Force") { exit 0 }
}

Write-Host ""
Yellow "即將更新以下核心檔案（config.json / 自定義 tools / memory 不受影響）："
Write-Host "  agent.py  bot.py  main.py  tools_builtin.py  requirements.txt  scripts\update.ps1  hydrabot.bat  VERSION" -ForegroundColor DarkGray
Write-Host ""

$confirm = Read-Host "繼續更新？[Y/n]"
if ($confirm -match "^[Nn]$") {
    Write-Host "  已取消。`n" -ForegroundColor DarkGray
    exit 0
}
Write-Host ""

# ── Backup user data ───────────────────────────────────────────
Write-Host ""
Cyan "💾 備份用戶數據..."
Write-Host ""

if (Test-Path "config.json") {
    Copy-Item "config.json" "config.json.bak" -Force
    Ok "已備份 config.json"
}

if (Test-Path "tools" -PathType Container) {
    $toolsFiles = @(Get-ChildItem "tools" -Recurse -File 2>$null | Measure-Object).Count
    if ($toolsFiles -gt 0) {
        Compress-Archive -Path "tools" -DestinationPath "tools.zip" -Force -CompressionLevel Fastest
        Ok "已備份自定義 tools"
    }
}

if (Test-Path "memory.json") {
    Copy-Item "memory.json" "memory.json.bak" -Force
    Ok "已備份 memory.json"
}

# ── Count existing tools (before update) ───────────────────────
$OLD_TOOLS = if (Test-Path "tools_builtin.py") {
    ((Select-String '^\s+\(' "tools_builtin.py" -AllMatches).Matches.Count)
} else {
    "?"
}

# ── Download updates ───────────────────────────────────────────
Write-Host "  📥 下載更新..."
Hr

$CORE_FILES = @("agent.py","bot.py","main.py","cli.py","discord_bot.py","learning.py","tools_builtin.py","scheduler.py","requirements.txt","scripts/update.ps1","hydrabot.cmd","VERSION")
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
        Write-Host "⚠ (保留舊版)" -ForegroundColor Yellow
        $FAILED += $f
    }
}

# ── Restore user data ──────────────────────────────────────────
Write-Host ""
Cyan "📥 復原用戶數據..."
Write-Host ""

if (Test-Path "config.json.bak") {
    Copy-Item "config.json.bak" "config.json" -Force
    Ok "已復原 config.json（保留您的設定）"
}

if (Test-Path "tools.zip") {
    Expand-Archive -Path "tools.zip" -DestinationPath "." -Force
    Remove-Item "tools.zip" -Force
    Ok "已復原自定義 tools"
}

if (Test-Path "memory.json.bak") {
    Copy-Item "memory.json.bak" "memory.json" -Force
    Ok "已復原 memory.json（保留對話歷史）"
}

# ── Update dependencies ────────────────────────────────────────
Write-Host ""
Write-Host "  📦 更新 Python 依賴..." -ForegroundColor Cyan
Write-Host ""

$PYTHON = $null
foreach ($cmd in @("python", "python3")) {
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        $PYTHON = $cmd
        break
    }
}

if (-not $PYTHON) {
    Warn "找不到 Python，略過依賴更新"
}
else {
    # Activate venv if exists (Windows: Scripts\activate.ps1)
    $VENV_ACTIVATE = $null
    if (Test-Path "venv\Scripts\activate.ps1") {
        $VENV_ACTIVATE = "venv\Scripts\activate.ps1"
    }
    elseif (Test-Path "venv\bin\activate") {
        $VENV_ACTIVATE = "venv\bin\activate"
    }

    if ($null -ne $VENV_ACTIVATE) {
        & $VENV_ACTIVATE
    }

    try {
        & $PYTHON -m pip install -r requirements.txt -q --upgrade --disable-pip-version-check
        Ok "依賴已更新"
    }
    catch {
        Warn "pip 更新失敗，請手動執行: $PYTHON -m pip install -r requirements.txt"
    }
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
        Write-Host "  內建工具: " -NoNewline
        Write-Host "$OLD_TOOLS" -ForegroundColor DarkGray -NoNewline
        Write-Host "  →  " -NoNewline
        Write-Host "$NEW_TOOLS" -ForegroundColor Green -NoNewline
        Write-Host "  " -NoNewline
        Write-Host "(+$DIFF 新工具)" -ForegroundColor Green
    } else {
        Write-Host "  內建工具: " -NoNewline
        Write-Host "$NEW_TOOLS 個" -ForegroundColor Green
    }
}

if ($FAILED.Count -gt 0) {
    Warn "以下檔案下載失敗，已保留舊版: $($FAILED -join ', ')"
}

Write-Host ""
Cyan "重啟 Bot 以套用更新"
Write-Host ""
