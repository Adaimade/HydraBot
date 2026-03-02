@echo off
REM ═════════════════════════════════════════════════════════════
REM   HydraBot CLI (Windows)
REM   Commands: start | update | config | status | help
REM ═════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM ── Find Python (prefer venv) ─────────────────────────────────
set "PYTHON="
REM Use venv Python directly if available (avoids missing-package issues)
if exist "%SCRIPT_DIR%venv\Scripts\python.exe" (
    set "PYTHON=%SCRIPT_DIR%venv\Scripts\python.exe"
    goto :found_python
)
REM Fall back to system Python
for %%A in (python python3) do (
    where %%A >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=%%A"
        goto :found_python
    )
)

:found_python

REM ── Read version ──────────────────────────────────────────────
set "VER=?"
if exist "VERSION" (
    for /f "delims=" %%A in (VERSION) do (
        set "VER=%%A"
        goto :got_version
    )
)
:got_version

REM ── Command routing ───────────────────────────────────────────
set "CMD=%1"
if "!CMD!"=="" set "CMD=help"

if "!CMD!"=="start" (
    goto :cmd_start
) else if "!CMD!"=="update" (
    goto :cmd_update
) else if "!CMD!"=="config" (
    goto :cmd_config
) else if "!CMD!"=="status" (
    goto :cmd_status
) else (
    goto :cmd_help
)

REM ═════════════════════════════════════════════════════════════
REM ── start
REM ═════════════════════════════════════════════════════════════
:cmd_start
echo.
echo   🐍 HydraBot v!VER!
echo   ─────────────────────────────────────────────────────
echo.

if not exist "config.json" (
    color 4c
    echo   ✗ 找不到 config.json！
    echo   請先執行安裝: bash install.sh 或 powershell -ExecutionPolicy Bypass -c "irm ... | iex"
    echo.
    pause
    exit /b 1
)

for /f %%A in ('findstr "YOUR_TELEGRAM_BOT_TOKEN\|YOUR_MODEL_API_KEY" config.json 2^>nul') do (
    color 4c
    echo   ⚠ config.json 中仍有未填寫的預留符！
    echo   請編輯 config.json 填入必要的值。
    echo.
    pause
    exit /b 1
)

if not defined PYTHON (
    color 4c
    echo   ✗ 找不到 Python！
    echo.
    pause
    exit /b 1
)

if not exist "tools" mkdir "tools"
if not exist "mcp_servers" mkdir "mcp_servers"

REM ── Auto-install dependencies if missing ─────────────────────
%PYTHON% -c "import openai, anthropic, telegram" >nul 2>&1
if errorlevel 1 (
    echo   正在安裝依賴，請稍候...
    %PYTHON% -m pip install -r "%SCRIPT_DIR%requirements.txt" -q --disable-pip-version-check
    if errorlevel 1 (
        color 4c
        echo   ✗ 依賴安裝失敗！請手動執行:
        echo     %PYTHON% -m pip install -r requirements.txt
        echo.
        pause
        exit /b 1
    )
    echo   依賴已就緒
    echo.
)

echo   啟動中...
echo.
%PYTHON% "%SCRIPT_DIR%main.py"
goto :end

REM ═════════════════════════════════════════════════════════════
REM ── update
REM ═════════════════════════════════════════════════════════════
:cmd_update
if not exist "scripts\update.ps1" (
    color 4c
    echo   ✗ 找不到 scripts\update.ps1！
    pause
    exit /b 1
)
powershell -ExecutionPolicy Bypass -File "scripts\update.ps1" %2
goto :end

REM ═════════════════════════════════════════════════════════════
REM ── config
REM ═════════════════════════════════════════════════════════════
:cmd_config
if not exist "config.json" (
    color 4c
    echo   ✗ config.json 不存在，請先執行安裝。
    echo.
    pause
    exit /b 1
)
start notepad "config.json"
goto :end

REM ═════════════════════════════════════════════════════════════
REM ── status
REM ═════════════════════════════════════════════════════════════
:cmd_status
echo.
echo   🐍 HydraBot Status  v!VER!
echo   ─────────────────────────────────────────────────────
echo.

if exist "config.json" (
    echo   設定檔:     ✓ 存在

    if defined PYTHON (
        set "_py=%TEMP%\_hb_status.py"
        (
            echo import json
            echo try:
            echo     c = json.load(open("config.json"))
            echo     m = c.get("models", [])
            echo     a = c.get("authorized_users", [])
            echo     print("  Models: " + str(len(m)) + " set")
            echo     for i, x in enumerate(m):
            echo         print("    [" + str(i) + "] " + x.get("name","?") + "  (" + x.get("provider","?") + " / " + x.get("model","?") + ")")
            echo     print("  Auth:   " + str(a if a else "(unlimited)"))
            echo     t = c.get("telegram_token", "")
            echo     mk = t[:6]+"..."+t[-4:] if len(t)>10 else "???"
            echo     print("  Token:  " + mk)
            echo except Exception as e:
            echo     print("  Warning: " + str(e))
        ) > "!_py!"
        %PYTHON% "!_py!"
        del "!_py!" >nul 2>&1
    )
) else (
    echo   設定檔:     ✗ 不存在（執行 bash install.sh）
)

if exist "tools" (
    for /r "tools" %%A in (*.py) do (
        set /a TOOL_COUNT+=1
    )
    echo   自定義工具: !TOOL_COUNT! 個  (tools/)
) else (
    echo   自定義工具: 0 個  (tools/)
)

if exist "memory.json" (
    echo   記憶條目:   [存在]  (memory.json)
)

if exist "venv" (
    echo   虛擬環境:   ✓ 存在
) else (
    echo   虛擬環境:   ⚠ 不存在（執行 bash install.sh）
)

echo.
goto :end

REM ═════════════════════════════════════════════════════════════
REM ── help
REM ═════════════════════════════════════════════════════════════
:cmd_help
echo.
echo   🐍 HydraBot CLI  v!VER!
echo   ─────────────────────────────────────────────────────
echo.
echo   用法:
echo.
echo   hydrabot start          啟動 Bot
echo   hydrabot update         更新到最新版本
echo   hydrabot config         編輯 config.json
echo   hydrabot status         查看安裝狀態與設定摘要
echo   hydrabot help           顯示此說明
echo.
echo   安裝目錄: !SCRIPT_DIR!
echo.
goto :end

:end
endlocal
