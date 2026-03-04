# ═══════════════════════════════════════════════════════════════
#   HydraBot Windows Installer (PowerShell)
#   Usage:  powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.ps1 | iex"
# ═══════════════════════════════════════════════════════════════
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"   # faster downloads

# ── Colors ─────────────────────────────────────────────────────
function Green ($t)  { Write-Host "  $t" -ForegroundColor Green }
function Yellow($t)  { Write-Host "  $t" -ForegroundColor Yellow }
function Red   ($t)  { Write-Host "  $t" -ForegroundColor Red }
function Cyan  ($t)  { Write-Host "  $t" -ForegroundColor Cyan }
function Hr    ()    { Write-Host ("  " + "-"*50) -ForegroundColor DarkGray }
function Ok    ($t)  { Green  "OK  $t" }
function Warn  ($t)  { Yellow "WRN $t" }
function Err   ($t)  { Red    "ERR $t"; exit 1 }
function Inf   ($t)  { Cyan   "... $t" }

# Read-Host 在 irm|iex 管道模式下会读到空值，改用 Console 直接读键盘
function Ask ($prompt) {
    Write-Host "  $prompt" -NoNewline -ForegroundColor White
    return [Console]::ReadLine()
}
function AskSecret ($prompt) {
    Write-Host "  $prompt" -NoNewline -ForegroundColor White
    $ss = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR(
            $( $input = New-Object System.Security.SecureString
               while ($true) {
                   $k = [Console]::ReadKey($true)
                   if ($k.Key -eq 'Enter') { break }
                   elseif ($k.Key -eq 'Backspace') {
                       if ($input.Length -gt 0) { $input.RemoveAt($input.Length-1) }
                   } else { $input.AppendChar($k.KeyChar) }
               }
               Write-Host ""
               $input )
        ))
    return $ss
}

$REPO = "https://raw.githubusercontent.com/Adaimade/HydraBot/main"

# ── Banner ─────────────────────────────────────────────────────
Clear-Host
$banner = @"

  _   _           _           ____        _
 | | | |_   _  __| |_ __ __ _| __ )  ___ | |_
 | |_| | | | |/ _` | '__/ _` |  _ \ / _ \| __|
 |  _  | |_| | (_| | | | (_| | |_) | (_) | |_
 |_| |_|\__, |\__,_|_|  \__,_|____/ \___/ \__|
        |___/

"@
Write-Host $banner -ForegroundColor Cyan
try {
    $ver = (Invoke-RestMethod "$REPO/VERSION").Trim()
} catch {
    $ver = "1.1.0"
}
Write-Host "  Self-expanding AI Assistant via Telegram  " -NoNewline -ForegroundColor White
Write-Host "v$ver" -ForegroundColor Green
Write-Host "  https://github.com/Adaimade/HydraBot" -ForegroundColor DarkGray
Write-Host ""

# ── Risk Warning ───────────────────────────────────────────────
Write-Host "  ⚠️  安裝前請閱讀以下風險提示" -ForegroundColor Yellow
Hr
Write-Host ""
Write-Host "  HydraBot 安裝後將在你的本地機器上以背景服務形式執行。" -ForegroundColor White
Write-Host "  請確認你了解並接受以下內容：" -ForegroundColor White
Write-Host ""
Write-Host "    · 可在你的機器上執行 Python / Shell 程式碼" -ForegroundColor Gray
Write-Host "    · 可讀取和寫入本地檔案系統中的檔案" -ForegroundColor Gray
Write-Host "    · 可透過 pip 自動下載並安裝第三方 Python 套件" -ForegroundColor Gray
Write-Host "    · 可發起對外部服務的網路請求" -ForegroundColor Gray
Write-Host "    · 可在執行時自行建立並載入新工具（自我擴展）" -ForegroundColor Gray
Write-Host ""
Write-Host "  請僅在你信任來源且理解上述權限的情況下繼續。" -ForegroundColor DarkGray
Write-Host "  Only proceed if you trust the source and accept these permissions." -ForegroundColor DarkGray
Write-Host ""
Hr
Write-Host ""
$confirm = Ask "輸入 yes 繼續，其他任意鍵取消："
if ($confirm -ne "yes") {
    Write-Host "  已取消。" -ForegroundColor DarkGray
    exit 0
}

# ── Install directory ──────────────────────────────────────────
Write-Host ""
Write-Host "  [1/6] 選擇安裝目錄" -ForegroundColor White
Hr
$defaultDir = "$env:USERPROFILE\hydrabot"
$inputDir = Ask "安裝到 [$defaultDir]（直接按 Enter 使用預設）："
if ([string]::IsNullOrWhiteSpace($inputDir)) {
    $INSTALL_DIR = $defaultDir
} else {
    $INSTALL_DIR = $inputDir.Trim()
}
Inf "安裝目錄: $INSTALL_DIR"
New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
Ok "目錄已就緒"

# ── Check / Install Python ─────────────────────────────────────
Write-Host ""
Write-Host "  [2/6] 檢查 Python 環境" -ForegroundColor White
Hr

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $v = & $cmd --version 2>&1
            if ($v -match "Python 3\.(\d+)") {
                if ([int]$Matches[1] -ge 10) { return $cmd }
            }
        } catch {}
    }
    return $null
}

$PYTHON = Find-Python
if (-not $PYTHON) {
    Warn "未找到 Python 3.10+，嘗試用 winget 自動安裝..."
    try {
        winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $PYTHON = Find-Python
    } catch {}
    if (-not $PYTHON) {
        Err "無法自動安裝 Python。請手動安裝: https://www.python.org/downloads/ (勾選 Add to PATH)"
    }
    Ok "Python 安裝完成"
}

$pyver = & $PYTHON --version 2>&1
Ok "找到 $pyver ($PYTHON)"

# ── Download core files ────────────────────────────────────────
Write-Host ""
Write-Host "  [3/6] 下載核心檔案" -ForegroundColor White
Hr

$coreFiles = @("agent.py","bot.py","main.py","tools_builtin.py","scheduler.py","sub_agent_manager.py","requirements.txt","hydrabot","hydrabot.bat","VERSION")
$scriptFiles = @("scripts/update.sh","scripts/update.ps1","scripts/start.sh")
$failed = @()

# Create directories first
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\tools"      | Out-Null
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\mcp_servers" | Out-Null
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\scripts"     | Out-Null

foreach ($f in ($coreFiles + $scriptFiles)) {
    Write-Host "  $($f.PadRight(30))" -NoNewline
    $dest = "$INSTALL_DIR\$($f -replace '/','\\')"
    try {
        Invoke-WebRequest -Uri "$REPO/$f" -OutFile $dest -UseBasicParsing
        Write-Host "OK" -ForegroundColor Green
    } catch {
        Write-Host "SKIP (keep old)" -ForegroundColor Yellow
        $failed += $f
    }
}

if ($failed.Count -gt 0) {
    Warn "以下檔案下載失敗: $($failed -join ', ')"
}
Ok "核心檔案下載完成"

# ── Create venv ────────────────────────────────────────────────
Write-Host ""
Write-Host "  [4/6] 建立 Python 虛擬環境" -ForegroundColor White
Hr
$VENV = "$INSTALL_DIR\venv"
if (-not (Test-Path $VENV)) {
    Inf "建立虛擬環境..."
    & $PYTHON -m venv $VENV
}
$PY = "$VENV\Scripts\python.exe"
if (-not (Test-Path $PY)) { $PY = "$VENV\bin\python" }

Inf "升級 pip..."
& $PY -m pip install --upgrade pip -q --disable-pip-version-check
Inf "安裝依賴..."
& $PY -m pip install -r "$INSTALL_DIR\requirements.txt" -q --disable-pip-version-check
Ok "依賴安裝完成"

# ── Config wizard ──────────────────────────────────────────────
Write-Host ""
Write-Host "  [5/6] 設定 HydraBot" -ForegroundColor White
Hr

# Telegram token
Write-Host ""
Write-Host "  Telegram Bot Token" -ForegroundColor White
Write-Host "  （從 @BotFather 取得，格式: 1234567890:ABCdef...）" -ForegroundColor DarkGray
$TG_TOKEN = Ask "Token："
if ([string]::IsNullOrWhiteSpace($TG_TOKEN)) { $TG_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN" }

# Authorized users
Write-Host ""
Write-Host "  授權使用者 Telegram ID（多個用逗號分隔，留空=不限制）" -ForegroundColor White
Write-Host "  （從 @userinfobot 取得你的 ID）" -ForegroundColor DarkGray
$authInput = Ask "使用者 ID："

$authJson = "[]"
if (-not [string]::IsNullOrWhiteSpace($authInput)) {
    $ids = $authInput -split "[,\s]+" | Where-Object { $_ -match "^\d+$" } | ForEach-Object { $_.Trim() }
    if ($ids.Count -gt 0) {
        $authJson = "[" + ($ids -join ",") + "]"
    }
}

# Models
$modelsJson = "["
$PROVIDERS  = @("anthropic","openai","google","openai-compatible")
$DEF_MODELS = @("claude-sonnet-4-5","gpt-4o","gemini-2.0-flash","your-model")
$DEF_NAMES  = @("主力 Claude","快速 GPT","Gemini Flash","自定義模型")

for ($i = 0; $i -lt 3; $i++) {
    Write-Host ""
    $label = if ($i -eq 0) {"主力模型"} elseif ($i -eq 1) {"快速／子代理"} else {"備用模型"}
    Write-Host "  --- 模型 #$i ($label) ---" -ForegroundColor Cyan
    Write-Host "  Provider:" -ForegroundColor White
    Write-Host "    0 = Anthropic (Claude)" -ForegroundColor DarkGray
    Write-Host "    1 = OpenAI (GPT)" -ForegroundColor DarkGray
    Write-Host "    2 = Google (Gemini)" -ForegroundColor DarkGray
    Write-Host "    3 = OpenAI-compatible（自定義端點）" -ForegroundColor DarkGray
    $pIdx = Ask "選擇（預設 0）："
    if ($pIdx -notmatch "^[0123]$") { $pIdx = "0" }
    $provider = $PROVIDERS[$pIdx]

    Write-Host "  API Key:" -ForegroundColor White
    $apiKey = Ask "Key："
    if ([string]::IsNullOrWhiteSpace($apiKey)) { $apiKey = "YOUR_MODEL_API_KEY" }

    $defModel = $DEF_MODELS[$pIdx]
    Write-Host "  模型名稱 [預設: $defModel]:" -ForegroundColor White
    $modelName = Ask "Model："
    if ([string]::IsNullOrWhiteSpace($modelName)) { $modelName = $defModel }

    $displayName = $DEF_NAMES[$pIdx]

    $baseUrl = "null"
    if ($provider -eq "openai-compatible") {
        Write-Host "  Base URL (e.g. https://api.example.com/v1):" -ForegroundColor White
        $bu = Ask "URL："
        if (-not [string]::IsNullOrWhiteSpace($bu)) { $baseUrl = """$bu""" }
    }

    if ($i -gt 0) { $modelsJson += "," }
    $modelsJson += @"

    {
      "name": "$displayName",
      "provider": "$provider",
      "api_key": "$apiKey",
      "model": "$modelName",
      "base_url": $baseUrl
    }
"@
    Ok "模型 #$i 已設定（$provider / $modelName）"
}
$modelsJson += "`n  ]"

# Write config.json
$configContent = @"
{
  "telegram_token": "$TG_TOKEN",
  "authorized_users": $authJson,
  "models": $modelsJson,
  "max_tokens": 4096,
  "max_history": 50
}
"@
# Write WITHOUT BOM — PowerShell 5.x Set-Content UTF8 adds BOM which breaks Python json parser
[System.IO.File]::WriteAllText(
    "$INSTALL_DIR\config.json",
    $configContent,
    [System.Text.UTF8Encoding]::new($false)   # $false = no BOM
)
Ok "config.json 已写入"

# ── Setup launcher ────────────────────────────────────────────
Write-Host ""
Write-Host "  [6/6] 設定啟動腳本" -ForegroundColor White
Hr

# hydrabot launcher
if (Test-Path "$INSTALL_DIR\hydrabot.cmd") {
    Ok "hydrabot.cmd 已就緒"
} else {
    Warn "hydrabot launcher 未找到，請手動檢查下載"
}

# Add to PATH (user scope)
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$INSTALL_DIR*") {
    [System.Environment]::SetEnvironmentVariable(
        "Path",
        "$userPath;$INSTALL_DIR",
        "User"
    )
    Ok "已將 $INSTALL_DIR 加入使用者 PATH"
} else {
    Ok "PATH 已包含安裝目錄"
}

# ── Done ───────────────────────────────────────────────────────
Write-Host ""
Hr
Write-Host ""
Write-Host "  ✅  HydraBot 安裝完成！" -ForegroundColor Green
Write-Host ""
Write-Host "  🎯 快速開始（選擇適合您的方式）：" -ForegroundColor White
Write-Host ""

# 檢查 PATH 是否設置成功
if ($env:Path -like "*$INSTALL_DIR*") {
    Write-Host "  ✅ PATH 已設置 - 您可以從任何地方執行：" -ForegroundColor Green
    Write-Host "    hydrabot start      # 啟動 Bot" -ForegroundColor Cyan
    Write-Host "    hydrabot update     # 更新版本" -ForegroundColor Cyan
    Write-Host "    hydrabot config     # 編輯設定" -ForegroundColor Cyan
    Write-Host "    hydrabot status     # 查看狀態" -ForegroundColor Cyan
    Write-Host "    hydrabot logs       # 查看日誌" -ForegroundColor Cyan
    Write-Host "    hydrabot help       # 顯示幫助" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  💡 提示：您需要重啟 PowerShell 以生效新的 PATH 設置" -ForegroundColor Yellow
} else {
    Write-Host "  ⚠️  PATH 未設置 - 請使用以下方式執行：" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  📂 在安裝目錄中執行：" -ForegroundColor White
Write-Host "    cd $INSTALL_DIR" -ForegroundColor Cyan
Write-Host "    .\hydrabot.cmd start        # 啟動 Bot" -ForegroundColor Cyan
Write-Host "    .\hydrabot.cmd update       # 更新版本" -ForegroundColor Cyan
Write-Host ""

Write-Host "  🐍 或直接用 Python：" -ForegroundColor White
Write-Host "    cd $INSTALL_DIR" -ForegroundColor Cyan
Write-Host "    $PY main.py" -ForegroundColor Cyan
Write-Host ""

Write-Host "  📖 完整說明：請查看 $INSTALL_DIR\QUICKSTART.md" -ForegroundColor Cyan
Write-Host ""
