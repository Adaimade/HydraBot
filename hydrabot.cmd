@echo off
REM ═════════════════════════════════════════════════════════════
REM   HydraBot CLI (Universal CMD wrapper)
REM   Allows: hydrabot start (from any directory)
REM ═════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion

REM Get installation directory (where this script is located)
set "INSTALL_DIR=%~dp0"
set "INVOCATION_PWD=%CD%"
cd /d "%INSTALL_DIR%"

REM Find Python in venv first
set "PYTHON="
if exist "%INSTALL_DIR%venv\Scripts\python.exe" (
    set "PYTHON=%INSTALL_DIR%venv\Scripts\python.exe"
) else (
    REM Fall back to system Python
    for /f "delims=" %%A in ('where python 2^>nul') do (
        set "PYTHON=%%A"
        goto :found_python
    )
    for /f "delims=" %%A in ('where python3 2^>nul') do (
        set "PYTHON=%%A"
        goto :found_python
    )
)

:found_python

REM Get command（無參數時依 config 選 start / cli / help）
set "CMD=%~1"
if "!CMD!"=="" (
  set "CMD=help"
  if exist "config.json" (
    for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "try { $raw = Get-Content -LiteralPath '%INSTALL_DIR%config.json' -Raw -Encoding UTF8; $j = $raw ^| ConvertFrom-Json; $tg = [string]$j.telegram_token; $dc = [string]$j.discord_token; if ((($tg) -and ($tg -notmatch 'YOUR_')) -or (($dc) -and ($dc -notmatch 'YOUR_'))) { 'start' } else { 'cli' } } catch { 'help' }"`) do set "CMD=%%D"
  )
)

if "!CMD!"=="start" (
    if not defined PYTHON (
        echo [ERROR] Python not found
        exit /b 1
    )
    if not exist "config.json" (
        echo [ERROR] config.json not found. Please run install.ps1 first.
        exit /b 1
    )
    cd /d "!INVOCATION_PWD!" 2>nul
    if errorlevel 1 cd /d "!INSTALL_DIR!"
    shift
    "%PYTHON%" "%INSTALL_DIR%main.py" %*
    exit /b !ERRORLEVEL!
) else if "!CMD!"=="cli" (
    if not defined PYTHON (
        echo [ERROR] Python not found
        exit /b 1
    )
    if not exist "config.json" (
        echo [ERROR] config.json not found. Please run install.ps1 first.
        exit /b 1
    )
    findstr /L "YOUR_MODEL_API_KEY" "config.json" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [ERROR] config.json still has placeholder YOUR_MODEL_API_KEY
        exit /b 1
    )
    findstr /L "YOUR_GOOGLE_AI_KEY" "config.json" >nul 2>&1
    if !errorlevel! equ 0 (
        echo [ERROR] config.json still has placeholder YOUR_GOOGLE_AI_KEY
        exit /b 1
    )
    "%PYTHON%" -c "import openai, anthropic" >nul 2>&1
    if errorlevel 1 (
        "%PYTHON%" -m pip install -r "%INSTALL_DIR%requirements.txt" -q --disable-pip-version-check
    )
    cd /d "!INVOCATION_PWD!" 2>nul
    if errorlevel 1 cd /d "!INSTALL_DIR!"
    "%PYTHON%" "%INSTALL_DIR%main.py" --cli
    exit /b !ERRORLEVEL!
) else if "!CMD!"=="config" (
    if exist "config.json" (
        start notepad "config.json"
    ) else (
        echo [ERROR] config.json not found
        exit /b 1
    )
) else if "!CMD!"=="status" (
    if defined PYTHON (
        "%PYTHON%" -c "import json; c=json.load(open('config.json')); print(f'Models: {len(c.get(\"models\",[]))}'); print(f'Auth: {c.get(\"authorized_users\",[])}'); print(f'Token: {c.get(\"telegram_token\",\"?\")[:6]}...')" 2>nul
    )
) else if "!CMD!"=="update" (
    REM Delegate to PowerShell update script for better encoding handling
    if exist "scripts\update.ps1" (
        powershell -ExecutionPolicy Bypass -File "scripts\update.ps1" %2
        exit /b !ERRORLEVEL!
    ) else (
        echo [ERROR] scripts\update.ps1 not found
        exit /b 1
    )
) else if "!CMD!"=="logs" (
    REM Show logs from hydrabot.log file
    set "LINES=%2"
    if "!LINES!"=="" set "LINES=50"
    if exist "hydrabot.log" (
        powershell -Command "Get-Content 'hydrabot.log' -Tail !LINES!"
    ) else (
        echo [INFO] No logs found. Run 'hydrabot start' first or check hydrabot.log
    )
) else (
    echo.
    echo   HydraBot CLI (Windows)
    echo   ─────────────────────────────────────────
    echo.
    echo   Usage:
    echo     hydrabot             - Auto: Bot if TG/DC set, else terminal CLI
    echo     hydrabot start       - Start Bot
    echo     hydrabot cli         - Terminal CLI (no TG/DC required)
    echo     hydrabot update      - Update to latest version (preserves config)
    echo     hydrabot config      - Edit config.json
    echo     hydrabot status      - Show installation status and config
    echo     hydrabot logs [N]    - Show last N lines of logs (default: 50)
    echo     hydrabot help        - Show this help
    echo.
)

endlocal
