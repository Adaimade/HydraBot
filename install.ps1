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
Write-Host "  ⚠️  安装前请阅读以下风险提示" -ForegroundColor Yellow
Hr
Write-Host ""
Write-Host "  HydraBot 安装后将在你的本地机器上以后台服务形式运行。" -ForegroundColor White
Write-Host "  请确认你了解并接受以下内容：" -ForegroundColor White
Write-Host ""
Write-Host "    · 可在你的机器上执行 Python / Shell 代码" -ForegroundColor Gray
Write-Host "    · 可读取和写入本地文件系统中的文件" -ForegroundColor Gray
Write-Host "    · 可通过 pip 自动下载并安装第三方 Python 包" -ForegroundColor Gray
Write-Host "    · 可发起对外部服务的网络请求" -ForegroundColor Gray
Write-Host "    · 可在运行时自行创建并加载新工具（自我扩展）" -ForegroundColor Gray
Write-Host ""
Write-Host "  请仅在你信任来源且理解上述权限的情况下继续。" -ForegroundColor DarkGray
Write-Host "  Only proceed if you trust the source and accept these permissions." -ForegroundColor DarkGray
Write-Host ""
Hr
Write-Host ""
$confirm = Ask "输入 yes 继续，其他任意键取消："
if ($confirm -ne "yes") {
    Write-Host "  已取消。" -ForegroundColor DarkGray
    exit 0
}

# ── Install directory ──────────────────────────────────────────
Write-Host ""
Write-Host "  [1/6] 选择安装目录" -ForegroundColor White
Hr
$defaultDir = "$env:USERPROFILE\hydrabot"
$inputDir = Ask "安装到 [$defaultDir]（直接回车使用默认）："
if ([string]::IsNullOrWhiteSpace($inputDir)) {
    $INSTALL_DIR = $defaultDir
} else {
    $INSTALL_DIR = $inputDir.Trim()
}
Inf "安装目录: $INSTALL_DIR"
New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null
Ok "目录已就绪"

# ── Check / Install Python ─────────────────────────────────────
Write-Host ""
Write-Host "  [2/6] 检查 Python 环境" -ForegroundColor White
Hr

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $v = & $cmd --version 2>&1
            if ($v -match "Python 3\.(\d+)") {
                if ([int]$Matches[1] -ge 9) { return $cmd }
            }
        } catch {}
    }
    return $null
}

$PYTHON = Find-Python
if (-not $PYTHON) {
    Warn "未找到 Python 3.9+，尝试用 winget 自动安装..."
    try {
        winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
        $PYTHON = Find-Python
    } catch {}
    if (-not $PYTHON) {
        Err "无法自动安装 Python。请手动安装: https://www.python.org/downloads/ (勾选 Add to PATH)"
    }
    Ok "Python 安装完成"
}

$pyver = & $PYTHON --version 2>&1
Ok "找到 $pyver ($PYTHON)"

# ── Download core files ────────────────────────────────────────
Write-Host ""
Write-Host "  [3/6] 下载核心文件" -ForegroundColor White
Hr

$coreFiles = @("agent.py","bot.py","main.py","tools_builtin.py","requirements.txt","update.sh","hydrabot","VERSION")
$failed = @()
foreach ($f in $coreFiles) {
    Write-Host "  $($f.PadRight(30))" -NoNewline
    try {
        Invoke-WebRequest -Uri "$REPO/$f" -OutFile "$INSTALL_DIR\$f" -UseBasicParsing
        Write-Host "OK" -ForegroundColor Green
    } catch {
        Write-Host "SKIP (keep old)" -ForegroundColor Yellow
        $failed += $f
    }
}

# Create directories
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\tools"      | Out-Null
New-Item -ItemType Directory -Force -Path "$INSTALL_DIR\mcp_servers" | Out-Null

if ($failed.Count -gt 0) {
    Warn "以下文件下载失败: $($failed -join ', ')"
}
Ok "核心文件下载完成"

# ── Create venv ────────────────────────────────────────────────
Write-Host ""
Write-Host "  [4/6] 创建 Python 虚拟环境" -ForegroundColor White
Hr
$VENV = "$INSTALL_DIR\venv"
if (-not (Test-Path $VENV)) {
    Inf "创建虚拟环境..."
    & $PYTHON -m venv $VENV
}
$PY = "$VENV\Scripts\python.exe"
if (-not (Test-Path $PY)) { $PY = "$VENV\bin\python" }

Inf "升级 pip..."
& $PY -m pip install --upgrade pip -q --disable-pip-version-check
Inf "安装依赖..."
& $PY -m pip install -r "$INSTALL_DIR\requirements.txt" -q --disable-pip-version-check
Ok "依赖安装完成"

# ── Config wizard ──────────────────────────────────────────────
Write-Host ""
Write-Host "  [5/6] 配置 HydraBot" -ForegroundColor White
Hr

# Telegram token
Write-Host ""
Write-Host "  Telegram Bot Token" -ForegroundColor White
Write-Host "  （从 @BotFather 获取，格式: 1234567890:ABCdef...）" -ForegroundColor DarkGray
$TG_TOKEN = Ask "Token："
if ([string]::IsNullOrWhiteSpace($TG_TOKEN)) { $TG_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN" }

# Authorized users
Write-Host ""
Write-Host "  授权用户 Telegram ID（多个用逗号分隔，留空=不限制）" -ForegroundColor White
Write-Host "  （从 @userinfobot 获取你的 ID）" -ForegroundColor DarkGray
$authInput = Ask "用户 ID："

$authJson = "[]"
if (-not [string]::IsNullOrWhiteSpace($authInput)) {
    $ids = $authInput -split "[,\s]+" | Where-Object { $_ -match "^\d+$" } | ForEach-Object { $_.Trim() }
    if ($ids.Count -gt 0) {
        $authJson = "[" + ($ids -join ",") + "]"
    }
}

# Models
$modelsJson = "["
$PROVIDERS  = @("anthropic","openai","openai-compatible")
$DEF_MODELS = @("claude-sonnet-4-5","gpt-4o","gpt-4o-mini")

for ($i = 0; $i -lt 3; $i++) {
    Write-Host ""
    $label = if ($i -eq 0) {"主力模型"} elseif ($i -eq 1) {"快速/子代理"} else {"备用模型"}
    Write-Host "  --- 模型 #$i ($label) ---" -ForegroundColor Cyan
    Write-Host "  Provider [0=anthropic / 1=openai / 2=openai-compatible]:" -ForegroundColor White
    $pIdx = Ask "选择 (默认 0)："
    if ($pIdx -notmatch "^[012]$") { $pIdx = "0" }
    $provider = $PROVIDERS[$pIdx]

    Write-Host "  API Key:" -ForegroundColor White
    $apiKey = Ask "Key："
    if ([string]::IsNullOrWhiteSpace($apiKey)) { $apiKey = "YOUR_MODEL_API_KEY" }

    $defModel = $DEF_MODELS[$pIdx]
    Write-Host "  模型名称 [默认: $defModel]:" -ForegroundColor White
    $modelName = Ask "Model："
    if ([string]::IsNullOrWhiteSpace($modelName)) { $modelName = $defModel }

    $labelNames = @("主力 Claude","快速 Haiku","备用 GPT")
    $displayName = $labelNames[$i]

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
    Ok "模型 #$i 已设置 ($provider / $modelName)"
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
$configContent | Set-Content -Path "$INSTALL_DIR\config.json" -Encoding UTF8
Ok "config.json 已写入"

# ── Create hydrabot.bat launcher ──────────────────────────────
Write-Host ""
Write-Host "  [6/6] 创建启动脚本" -ForegroundColor White
Hr

$batContent = @"
@echo off
cd /d "$INSTALL_DIR"
"$PY" main.py %*
"@
$batContent | Set-Content -Path "$INSTALL_DIR\hydrabot.bat" -Encoding ASCII

# Add to PATH (user scope)
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$INSTALL_DIR*") {
    [System.Environment]::SetEnvironmentVariable(
        "Path",
        "$userPath;$INSTALL_DIR",
        "User"
    )
    Ok "已将 $INSTALL_DIR 加入用户 PATH"
} else {
    Ok "PATH 已包含安装目录"
}

# ── Done ───────────────────────────────────────────────────────
Write-Host ""
Hr
Write-Host ""
Write-Host "  ✅  HydraBot 安装完成！" -ForegroundColor Green
Write-Host ""
Write-Host "  启动命令:" -ForegroundColor White
Write-Host "    cd $INSTALL_DIR" -ForegroundColor Cyan
Write-Host "    $PY main.py" -ForegroundColor Cyan
Write-Host ""
Write-Host "  或（重开终端后生效）:" -ForegroundColor White
Write-Host "    hydrabot.bat" -ForegroundColor Cyan
Write-Host ""
Write-Host "  更新命令:" -ForegroundColor White
Write-Host "    bash $INSTALL_DIR\update.sh" -ForegroundColor Cyan
Write-Host ""
