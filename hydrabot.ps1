# ═════════════════════════════════════════════════════════════
#   HydraBot CLI (PowerShell for Windows)
#   Usage: .\hydrabot.ps1 start
# ═════════════════════════════════════════════════════════════

param([string]$Command = "help", [string]$Arg = "")

$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $SCRIPT_DIR

# ── Find Python (prefer venv) ────────────────────────────────
$PYTHON = ""
if (Test-Path "$SCRIPT_DIR\venv\Scripts\python.exe") {
    $PYTHON = "$SCRIPT_DIR\venv\Scripts\python.exe"
}

# ── Colors ───────────────────────────────────────────────────
function Green ($t)  { Write-Host "  $t" -ForegroundColor Green }
function Yellow($t)  { Write-Host "  $t" -ForegroundColor Yellow }
function Red   ($t)  { Write-Host "  $t" -ForegroundColor Red }
function Cyan  ($t)  { Write-Host "  $t" -ForegroundColor Cyan }
function Ok    ($t)  { Green  "OK  $t" }
function Warn  ($t)  { Yellow "WRN $t" }
function Err   ($t)  { Red    "ERR $t"; exit 1 }
function Inf   ($t)  { Cyan   "... $t" }

# ── Get Version ──────────────────────────────────────────────
$VER = "?"
if (Test-Path "VERSION") {
    $VER = (Get-Content "VERSION" -Raw).Trim()
}

# ── Commands ─────────────────────────────────────────────────
switch ($Command.ToLower()) {
    "start" {
        Write-Host ""
        Write-Host "  🐍 HydraBot v$VER" -ForegroundColor Cyan
        Write-Host "  ─────────────────────────────────────────────────────" -ForegroundColor DarkGray
        Write-Host ""

        if (-not (Test-Path "config.json")) {
            Err "找不到 config.json！"
        }

        if (-not $PYTHON) {
            Err "找不到 Python！"
        }

        if (-not (Test-Path "tools")) { mkdir "tools" | Out-Null }
        if (-not (Test-Path "mcp_servers")) { mkdir "mcp_servers" | Out-Null }

        Write-Host "  啟動中..." -ForegroundColor White
        Write-Host ""

        & $PYTHON "$SCRIPT_DIR\main.py"
    }

    "config" {
        if (-not (Test-Path "config.json")) {
            Err "config.json 不存在"
        }
        Start-Process notepad "config.json"
    }

    "status" {
        Write-Host ""
        Write-Host "  🐍 HydraBot Status  v$VER" -ForegroundColor Cyan
        Write-Host "  ─────────────────────────────────────────────────────" -ForegroundColor DarkGray
        Write-Host ""

        if (Test-Path "config.json") {
            Ok "設定檔存在"
        } else {
            Write-Host "  設定檔: 不存在" -ForegroundColor Red
        }

        if (Test-Path "venv") {
            Ok "虛擬環境存在"
        } else {
            Write-Host "  虛擬環境: 不存在" -ForegroundColor Yellow
        }

        Write-Host ""
    }

    "update" {
        if (Test-Path "scripts\update.ps1") {
            & "scripts\update.ps1" $Arg
        } else {
            Err "scripts\update.ps1 not found"
        }
    }

    "logs" {
        $lines = if ($Arg -and $Arg -match "^\d+$") { [int]$Arg } else { 50 }
        if (Test-Path "hydrabot.log") {
            Get-Content "hydrabot.log" -Tail $lines
        } else {
            Write-Host "  [INFO] No logs found. Run 'hydrabot start' first" -ForegroundColor Cyan
        }
    }

    default {
        Write-Host ""
        Write-Host "  🐍 HydraBot CLI  v$VER" -ForegroundColor Cyan
        Write-Host "  ─────────────────────────────────────────────────────" -ForegroundColor DarkGray
        Write-Host ""
        Write-Host "  用法:" -ForegroundColor White
        Write-Host ""
        Write-Host "  .\hydrabot.ps1 start       啟動 Bot" -ForegroundColor Cyan
        Write-Host "  .\hydrabot.ps1 update      更新到最新版本（保留設定）" -ForegroundColor Cyan
        Write-Host "  .\hydrabot.ps1 config      編輯 config.json" -ForegroundColor Cyan
        Write-Host "  .\hydrabot.ps1 status      查看狀態" -ForegroundColor Cyan
        Write-Host "  .\hydrabot.ps1 logs [N]    顯示最近 N 行日誌（預設 50）" -ForegroundColor Cyan
        Write-Host "  .\hydrabot.ps1 help        顯示此說明" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  安裝目錄: $SCRIPT_DIR" -ForegroundColor DarkGray
        Write-Host ""
    }
}
