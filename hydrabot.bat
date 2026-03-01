@echo off
REM ═════════════════════════════════════════════════════════════
REM   HydraBot CLI (Windows)
REM   Commands: start | update | config | status | help
REM ═════════════════════════════════════════════════════════════
setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM ── Find Python ───────────────────────────────────────────────
set "PYTHON="
for %%A in (python python3) do (
    where %%A >nul 2>&1
    if !errorlevel! equ 0 (
        set "PYTHON=%%A"
        goto :found_python
    )
)

:found_python
if defined PYTHON (
    REM Try to activate venv
    if exist "venv\Scripts\activate.bat" (
        call venv\Scripts\activate.bat
    )
)

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
    echo   请先运行安装: bash install.sh 或 powershell -ExecutionPolicy Bypass -c "irm ... | iex"
    echo.
    pause
    exit /b 1
)

for /f %%A in ('findstr "YOUR_TELEGRAM_BOT_TOKEN\|YOUR_MODEL_API_KEY" config.json 2^>nul') do (
    color 4c
    echo   ⚠ config.json 中仍有未填写的占位符！
    echo   请编辑 config.json 填入必要的值。
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

echo   启动中...
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
    echo   ✗ config.json 不存在，请先运行安装。
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
    echo   配置文件:   ✓ 存在

    if defined PYTHON (
        %PYTHON% - <<PYEOF
import json, sys, os
try:
    c = json.loads(open('config.json').read())
    models = c.get('models', [])
    auth = c.get('authorized_users', [])
    print(f'  模型组数:   {len(models)} 组')
    for i, m in enumerate(models):
        print(f'    [{i}] {m.get("name","?")}  ({m.get("provider","?")} / {m.get("model","?")})')
    print(f'  授权用户:   {auth if auth else "（不限制）"}')
    tg = c.get('telegram_token', '')
    masked = tg[:6]+'...'+tg[-4:] if len(tg)>10 else '???'
    print(f'  TG Token:   {masked}')
except Exception as e:
    print(f'  ⚠ 读取失败: {e}')
PYEOF
    )
) else (
    echo   配置文件:   ✗ 不存在 (运行 bash install.sh)
)

if exist "tools" (
    for /r "tools" %%A in (*.py) do (
        set /a TOOL_COUNT+=1
    )
    echo   自定义工具: !TOOL_COUNT! 个  (tools/)
) else (
    echo   自定义工具: 0 个  (tools/)
)

if exist "memory.json" (
    echo   记忆条目:   [存在]  (memory.json)
)

if exist "venv" (
    echo   虚拟环境:   ✓ 存在
) else (
    echo   虚拟环境:   ⚠ 不存在 (运行 bash install.sh)
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
echo   hydrabot start          启动 Bot
echo   hydrabot update         更新到最新版本
echo   hydrabot config         编辑 config.json
echo   hydrabot status         查看安装状态与配置摘要
echo   hydrabot help           显示此帮助
echo.
echo   安装目录: !SCRIPT_DIR!
echo.
goto :end

:end
endlocal
