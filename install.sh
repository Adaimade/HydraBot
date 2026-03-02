#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#   HydraBot Installer  —  全自动环境安装 + 交互式配置
#   Usage:  bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
R='\033[0;31m'; Y='\033[1;33m'; G='\033[0;32m'
C='\033[0;36m'; B='\033[1;34m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

hr()   { printf "${DIM}────────────────────────────────────────────────────${NC}\n"; }
ok()   { printf "  ${G}✅  $*${NC}\n"; }
warn() { printf "  ${Y}⚠   $*${NC}\n"; }
err()  { printf "\n  ${R}❌  $*${NC}\n\n"; exit 1; }
inf()  { printf "  ${C}ℹ   $*${NC}\n"; }
ask()  { printf "  ${BOLD}$*${NC} "; }
step() { printf "\n${BOLD}$*${NC}\n"; hr; }

REPO="https://raw.githubusercontent.com/Adaimade/HydraBot/main"

# ── Banner ────────────────────────────────────────────────────
clear
printf "\n${C}${BOLD}"
cat << 'BANNER'
  _   _           _           ____        _
 | | | |_   _  __| |_ __ __ _| __ )  ___ | |_
 | |_| | | | |/ _` | '__/ _` |  _ \ / _ \| __|
 |  _  | |_| | (_| | | | (_| | |_) | (_) | |_
 |_| |_|\__, |\__,_|_|  \__,_|____/ \___/ \__|
        |___/
BANNER
printf "${NC}"
REMOTE_VER=$(curl -fsSL --max-time 10 "$REPO/VERSION" 2>/dev/null | tr -d '[:space:]') || REMOTE_VER="1.1.0"
printf "${BOLD}  Self-expanding AI Assistant via Telegram  ${G}v${REMOTE_VER}${NC}\n"
printf "${DIM}  https://github.com/Adaimade/HydraBot${NC}\n\n"

# ── Risk Warning ──────────────────────────────────────────────
printf "${Y}${BOLD}⚠️  安裝前請閱讀以下風險提示${NC}\n"
hr
printf "\n"
printf "  HydraBot 安裝後將在你的本地機器上以服務形式執行。\n"
printf "  請確認你了解並接受以下內容：\n\n"
printf "${DIM}"
printf "    · 可在你的機器上執行 Python / Shell 程式碼\n"
printf "    · 可讀取和寫入本地檔案系統中的檔案\n"
printf "    · 可透過 pip 自動下載並安裝第三方 Python 套件\n"
printf "    · 可發起對外部服務的網路請求\n"
printf "    · 可在執行時自行建立並載入新工具（自我擴展）\n\n"
printf "${NC}"
printf "  請僅在你信任來源且理解上述權限的情況下繼續。\n"
printf "${DIM}  Only proceed if you trust the source and accept these permissions.${NC}\n\n"
printf "${NC}"
hr
echo ""
ask "請輸入 ${Y}${BOLD}yes${NC} 確認你了解上述風險並同意繼續安裝: "
read -r _confirm
[[ "$_confirm" != "yes" ]] && { printf "\n  ${R}安裝已取消。${NC}\n\n"; exit 0; }
echo ""

# ══════════════════════════════════════════════════════════════
# [1/6]  自动检测并安装运行环境
# ══════════════════════════════════════════════════════════════
step "[1/6] 檢測並安裝執行環境"

# ── OS Detection ──────────────────────────────────────────────
detect_os() {
    if   [[ "$OSTYPE" == "msys"  || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then echo "windows"
    elif [[ "$OSTYPE" == "darwin"* ]];   then echo "macos"
    elif [[ -f /etc/debian_version ]];   then echo "debian"
    elif [[ -f /etc/fedora-release ]];   then echo "fedora"
    elif [[ -f /etc/redhat-release ]];   then echo "redhat"
    elif [[ -f /etc/arch-release ]];     then echo "arch"
    elif [[ -f /etc/alpine-release ]];   then echo "alpine"
    else echo "linux"
    fi
}

OS=$(detect_os)
inf "作業系統: ${BOLD}$OS${NC}"
echo ""

# ── Helper: check Python version ──────────────────────────────
python_ok() {
    local cmd="$1"
    command -v "$cmd" &>/dev/null || return 1
    local major minor
    major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null) || return 1
    minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null) || return 1
    [[ "$major" -ge 3 && "$minor" -ge 10 ]]
}

# ── Helper: run command with sudo if available ──────────────────
run_cmd() {
    if command -v sudo &>/dev/null && [[ $EUID -ne 0 ]]; then
        sudo "$@"
    else
        "$@"
    fi
}

# ── Install curl if missing ────────────────────────────────────
if ! command -v curl &>/dev/null; then
    warn "curl 未找到，嘗試安裝..."
    case "$OS" in
        windows) warn "請在 Git Bash 中執行，或手動安裝 curl" ;;
        macos)   brew install curl 2>/dev/null || warn "安裝 curl 失敗，請手動安裝" ;;
        debian)  run_cmd apt-get install -y curl -qq ;;
        fedora)  run_cmd dnf  install -y curl -q ;;
        redhat)  run_cmd yum  install -y curl -q ;;
        arch)    run_cmd pacman -S --noconfirm curl ;;
        alpine)  run_cmd apk add --quiet curl ;;
        *)       warn "無法自動安裝 curl，請手動安裝後重試" ;;
    esac
fi
command -v curl &>/dev/null && ok "curl  $(curl --version | head -1 | awk '{print $2}')" \
                             || err "curl 不可用，請手動安裝後重試"

# ── Install Python ────────────────────────────────────────────
PYTHON=""
# Check existing python
for cmd in python3 python3.13 python3.12 python3.11 python3.10 python; do
    if python_ok "$cmd"; then
        PYTHON="$cmd"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    warn "未找到 Python 3.10+，嘗試自動安裝..."
    echo ""

    case "$OS" in
        windows)
            # Try winget (Windows 10 1709+)
            if command -v winget &>/dev/null; then
                inf "使用 winget 安裝 Python 3.11..."
                winget install Python.Python.3.11 \
                    --silent \
                    --accept-source-agreements \
                    --accept-package-agreements \
                    || warn "winget 安裝失敗"
            fi
            # Try chocolatey
            if [[ -z "$PYTHON" ]] && command -v choco &>/dev/null; then
                inf "使用 Chocolatey 安裝 Python..."
                choco install python311 -y || warn "choco 安裝失敗"
            fi
            # Re-check after install
            for cmd in python3 python3.11 python; do
                python_ok "$cmd" && { PYTHON="$cmd"; break; }
            done
            if [[ -z "$PYTHON" ]]; then
                printf "\n  ${Y}無法自動安裝 Python。請手動安裝：${NC}\n"
                printf "  ${C}https://www.python.org/downloads/  (勾選 Add to PATH)${NC}\n"
                printf "  安裝完成後重新執行此腳本。\n\n"
                exit 1
            fi
            ;;

        macos)
            if command -v brew &>/dev/null; then
                inf "使用 Homebrew 安裝 Python..."
                brew install python@3.11
            else
                inf "安裝 Homebrew..."
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                brew install python@3.11
            fi
            for cmd in python3.11 python3 python; do
                python_ok "$cmd" && { PYTHON="$cmd"; break; }
            done
            ;;

        debian)
            inf "使用 apt 安裝 Python 3.11..."
            run_cmd apt-get update -qq
            run_cmd apt-get install -y python3.11 python3.11-venv python3-pip python3-venv \
                                    python3-full -qq 2>/dev/null \
            || run_cmd apt-get install -y python3 python3-venv python3-pip -qq
            for cmd in python3.11 python3 python; do
                python_ok "$cmd" && { PYTHON="$cmd"; break; }
            done
            ;;

        fedora)
            inf "使用 dnf 安裝 Python..."
            run_cmd dnf install -y python3 python3-pip -q
            for cmd in python3 python; do python_ok "$cmd" && { PYTHON="$cmd"; break; }; done
            ;;

        redhat)
            inf "使用 yum/dnf 安裝 Python..."
            run_cmd dnf install -y python3 python3-pip -q 2>/dev/null \
            || run_cmd yum install -y python3 python3-pip -q
            for cmd in python3 python; do python_ok "$cmd" && { PYTHON="$cmd"; break; }; done
            ;;

        arch)
            inf "使用 pacman 安裝 Python..."
            run_cmd pacman -S --noconfirm python python-pip
            python_ok python && PYTHON=python
            ;;

        alpine)
            inf "使用 apk 安裝 Python..."
            run_cmd apk add --quiet python3 py3-pip
            python_ok python3 && PYTHON=python3
            ;;

        *)
            printf "\n  ${R}不支援的系統，請手動安裝 Python 3.10+：${NC}\n"
            printf "  ${C}https://www.python.org/downloads/${NC}\n\n"
            exit 1
            ;;
    esac

    [[ -z "$PYTHON" ]] && err "Python 安裝失敗，請手動安裝 Python 3.10+ 後重試"
fi

ok "Python  $($PYTHON --version)  ($PYTHON)"

# ── Ensure pip is available ───────────────────────────────────
if ! "$PYTHON" -m pip --version &>/dev/null; then
    warn "pip 未找到，嘗試安裝..."
    case "$OS" in
        debian)
            run_cmd apt-get update -qq
            run_cmd apt-get install -y python3-pip -qq
            ;;
        fedora|redhat) run_cmd dnf install -y python3-pip -q 2>/dev/null \
                     || run_cmd yum install -y python3-pip -q ;;
        alpine) run_cmd apk add --quiet py3-pip ;;
        *)  curl -fsSL https://bootstrap.pypa.io/get-pip.py | "$PYTHON" ;;
    esac
fi
"$PYTHON" -m pip --version &>/dev/null && ok "pip   $("$PYTHON" -m pip --version | awk '{print $2}')" \
                                        || err "pip 安裝失敗，請手動安裝"

# ── Ensure venv module works ──────────────────────────────────
if ! "$PYTHON" -m venv --help &>/dev/null; then
    warn "venv 模組未找到，嘗試安裝..."
    case "$OS" in
        debian)
            # debian/ubuntu 需要單獨安裝 python3-venv
            run_cmd apt-get update -qq
            PYVER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            run_cmd apt-get install -y "python${PYVER}-venv" python3-venv -qq 2>/dev/null \
            || run_cmd apt-get install -y python3-full -qq
            ;;
        *)  "$PYTHON" -m pip install virtualenv -q && VENV_CMD="virtualenv" ;;
    esac
fi
"$PYTHON" -m venv --help &>/dev/null && ok "venv  已就緒" \
                                       || err "venv 不可用，請安裝 python3-venv"

# ── git (optional, for future updates) ───────────────────────
if command -v git &>/dev/null; then
    ok "git   $(git --version | awk '{print $3}')"
else
    warn "git 未安裝（可選，不影響執行）"
fi

echo ""

# ══════════════════════════════════════════════════════════════
# [2/6]  选择安装目录
# ══════════════════════════════════════════════════════════════
step "[2/6] 選擇安裝目錄"
DEFAULT_DIR="$HOME/hydrabot"
ask "安裝路徑 [預設: ${C}$DEFAULT_DIR${NC}]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

if [[ -d "$INSTALL_DIR" ]]; then
    printf "\n  ${Y}目錄已存在，將覆蓋核心檔案（config.json / 自定義 tools / memory 不受影響）${NC}\n"
    ask "  繼續？[Y/n]: "
    read -r _ow
    [[ "$_ow" =~ ^[Nn]$ ]] && { printf "  ${R}已取消。${NC}\n"; exit 0; }
fi

mkdir -p "$INSTALL_DIR"/{tools,mcp_servers,scripts}
export INSTALL_DIR
ok "安裝目錄: $INSTALL_DIR"
echo ""

# ══════════════════════════════════════════════════════════════
# [3/6]  下载核心文件
# ══════════════════════════════════════════════════════════════
step "[3/6] 下載核心檔案"
CORE_FILES=(agent.py bot.py main.py tools_builtin.py scheduler.py sub_agent_manager.py requirements.txt scripts/update.sh scripts/start.sh hydrabot VERSION)
FAILED_DL=()
for f in "${CORE_FILES[@]}"; do
    printf "  %-28s " "$f"
    if curl -fsSL --max-time 30 "$REPO/$f" -o "$INSTALL_DIR/$f" 2>/dev/null; then
        printf "${G}✓${NC}\n"
    else
        printf "${Y}⚠ (略過)${NC}\n"
        FAILED_DL+=("$f")
    fi
done
chmod +x "$INSTALL_DIR/scripts/update.sh" "$INSTALL_DIR/scripts/start.sh" "$INSTALL_DIR/hydrabot" 2>/dev/null || true
[[ ${#FAILED_DL[@]} -gt 0 ]] && warn "下載失敗: ${FAILED_DL[*]}（如已存在舊版則繼續）"
echo ""

# ══════════════════════════════════════════════════════════════
# [4/6]  Telegram Bot 配置
# ══════════════════════════════════════════════════════════════
step "[4/6] Telegram Bot 設定"
inf "前置步驟:"
inf "  1. Telegram 搜尋 ${BOLD}@BotFather${NC}${C}，發送 /newbot，取得 Bot Token"
inf "  2. Telegram 搜尋 ${BOLD}@userinfobot${NC}${C}，取得你的數字使用者 ID"
echo ""

TG_TOKEN=""
while [[ -z "$TG_TOKEN" ]]; do
    ask "Bot Token: "
    read -r TG_TOKEN
    TG_TOKEN="${TG_TOKEN// /}"
    [[ -z "$TG_TOKEN" ]] && printf "  ${R}不能為空${NC}\n"
done
ok "Token 已輸入"

echo ""
ask "授權使用者 ID（多個用逗號分隔，${Y}留空 = 允許所有人${NC}）: "
read -r AUTH_USERS_RAW
AUTH_USERS_RAW="${AUTH_USERS_RAW// /}"
[[ -z "$AUTH_USERS_RAW" ]] && warn "未設定授權使用者，所有人均可使用此 Bot！"
echo ""

# ══════════════════════════════════════════════════════════════
# [5/6]  AI 模型配置
# ══════════════════════════════════════════════════════════════
step "[5/6] AI 模型設定（最多 3 組）"
inf "模型 0 = 主力模型（必填）"
inf "模型 1 = 快速／子代理模型（選填，推薦填，讓並行任務更快）"
inf "模型 2 = 備用／專用模型（選填）"
echo ""

declare -a MODEL_NAMES MODEL_PROVIDERS MODEL_KEYS MODEL_MODELS MODEL_BASE_URLS MODEL_DESCS

configure_model() {
    local IDX="$1" LABEL="$2" REQUIRED="$3"
    printf "  ${BOLD}─── 模型 ${IDX}：${LABEL} ───${NC}\n"

    if [[ "$REQUIRED" == "optional" ]]; then
        ask "  跳過此模型？[Y/n]: "
        read -r _skip
        if [[ ! "$_skip" =~ ^[Nn]$ ]]; then
            MODEL_NAMES[$IDX]="" MODEL_PROVIDERS[$IDX]=""
            MODEL_KEYS[$IDX]=""  MODEL_MODELS[$IDX]=""
            MODEL_BASE_URLS[$IDX]="null" MODEL_DESCS[$IDX]=""
            printf "  ${DIM}已跳過${NC}\n\n"; return
        fi
    fi

    printf "  選擇 AI Provider:\n"
    printf "    ${B}1${NC}) Anthropic Claude         (sk-ant-api03-...)\n"
    printf "    ${B}2${NC}) OpenAI / GPT             (sk-...)\n"
    printf "    ${B}3${NC}) Google Gemini            (AI Studio API Key)\n"
    printf "    ${B}4${NC}) 自定義 OpenAI 相容 API  (Groq / DeepSeek / Ollama...)\n"
    ask "  選擇 [1/2/3/4，預設 1]: "
    read -r _p

    local PROVIDER MODEL_DEF BASE_URL="null"
    case "$_p" in
        2) PROVIDER="openai";  MODEL_DEF="gpt-4o" ;;
        3) PROVIDER="google";  MODEL_DEF="gemini-2.0-flash" ;;
        4) PROVIDER="openai-compatible"
           ask "  Base URL (如 https://api.groq.com/openai/v1): "
           read -r _bu; _bu="${_bu// /}"
           [[ -n "$_bu" ]] && BASE_URL="\"$_bu\""
           MODEL_DEF="llama-3.1-8b-instant" ;;
        *) PROVIDER="anthropic"; MODEL_DEF="claude-sonnet-4-6" ;;
    esac

    # API Key — hidden input
    local KEY=""
    while [[ -z "$KEY" ]]; do
        ask "  API Key: "
        read -rs KEY; echo ""
        KEY="${KEY// /}"
        [[ -z "$KEY" ]] && printf "  ${R}不能為空${NC}\n"
    done

    # Verify key format (basic sanity check)
    if [[ "$PROVIDER" == "anthropic" && ! "$KEY" =~ ^sk-ant ]]; then
        warn "Anthropic key 通常以 sk-ant- 開頭，請確認輸入正確"
    fi
    if [[ "$PROVIDER" == "openai" && ! "$KEY" =~ ^sk- ]]; then
        warn "OpenAI key 通常以 sk- 開頭，請確認輸入正確"
    fi

    ask "  模型名稱 [預設: ${C}${MODEL_DEF}${NC}]: "
    read -r _model; _model="${_model:-$MODEL_DEF}"

    local NAME_DEF="模型${IDX}-${LABEL}"
    ask "  顯示名稱 [預設: ${C}${NAME_DEF}${NC}]: "
    read -r _name; _name="${_name:-$NAME_DEF}"

    ask "  用途說明（可留空）: "
    read -r _desc

    MODEL_NAMES[$IDX]="$_name"  MODEL_PROVIDERS[$IDX]="$PROVIDER"
    MODEL_KEYS[$IDX]="$KEY"     MODEL_MODELS[$IDX]="$_model"
    MODEL_BASE_URLS[$IDX]="$BASE_URL" MODEL_DESCS[$IDX]="$_desc"
    ok "模型 ${IDX} 已設定: $_name / $_model"
    echo ""
}

configure_model 0 "主力模型" "required"
configure_model 1 "快速模型（子代理推薦）" "optional"
configure_model 2 "備用／專用模型" "optional"

# ══════════════════════════════════════════════════════════════
# [6/6]  写入配置、建立环境、安装依赖
# ══════════════════════════════════════════════════════════════
step "[6/6] 寫入設定 & 安裝依賴"

# Export for Python
export HB_TG_TOKEN="$TG_TOKEN"
export HB_AUTH_RAW="$AUTH_USERS_RAW"
for i in 0 1 2; do
    export "HB_M${i}_NAME=${MODEL_NAMES[$i]:-}"
    export "HB_M${i}_PROV=${MODEL_PROVIDERS[$i]:-}"
    export "HB_M${i}_KEY=${MODEL_KEYS[$i]:-}"
    export "HB_M${i}_MODEL=${MODEL_MODELS[$i]:-}"
    export "HB_M${i}_BASE=${MODEL_BASE_URLS[$i]:-null}"
    export "HB_M${i}_DESC=${MODEL_DESCS[$i]:-}"
done

# Write config.json via Python (safe from shell escaping)
"$PYTHON" << 'PYEOF'
import json, os, sys

def env(k, d=""): return os.environ.get(k, d)

raw = env("HB_AUTH_RAW").strip()
auth = [int(x.strip()) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]

models = []
for i in range(3):
    k = env(f"HB_M{i}_KEY")
    if not k:
        continue
    base = env(f"HB_M{i}_BASE", "null")
    base_val = None if base in ("null", "") else base.strip('"')
    models.append({
        "name":        env(f"HB_M{i}_NAME", f"模型{i}"),
        "provider":    env(f"HB_M{i}_PROV", "anthropic"),
        "api_key":     k,
        "model":       env(f"HB_M{i}_MODEL", "claude-sonnet-4-6"),
        "base_url":    base_val,
        "description": env(f"HB_M{i}_DESC", ""),
    })

if not models:
    print("❌ 至少需要設定一組模型！", file=sys.stderr); sys.exit(1)

config = {
    "telegram_token":   env("HB_TG_TOKEN"),
    "authorized_users": auth,
    "max_tokens":  4096,
    "max_history": 50,
    "models": models,
}

path = os.path.join(os.environ.get("INSTALL_DIR", "."), "config.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"  ✅  config.json → {path}")
print(f"  ✅  模型數量: {len(models)} 組")
print(f"  ✅  授權使用者: {auth if auth else '（不限制）'}")
PYEOF

# ── Virtual environment ────────────────────────────────────────
printf "\n  📦 建立 Python 虛擬環境...\n"
"$PYTHON" -m venv "$INSTALL_DIR/venv"
ok "虛擬環境: $INSTALL_DIR/venv"

# Activate
if [[ -f "$INSTALL_DIR/venv/Scripts/activate" ]]; then
    # Windows Git Bash
    source "$INSTALL_DIR/venv/Scripts/activate"
else
    source "$INSTALL_DIR/venv/bin/activate"
fi

# Upgrade pip silently first
printf "  📦 更新 pip...\n"
pip install --upgrade pip -q --disable-pip-version-check
ok "pip 已更新"

# Install all dependencies
printf "  📦 安裝 Python 依賴（python-telegram-bot / anthropic / openai / requests）...\n"
pip install -r "$INSTALL_DIR/requirements.txt" -q --disable-pip-version-check
ok "所有依賴已安裝"

# ── Global hydrabot command ────────────────────────────────────
printf "\n  🔗 建立全域指令...\n"
WRAPPER=""
if [[ "$OS" == "windows" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    mkdir -p "$HOME/bin" 2>/dev/null || true
    WRAPPER="$HOME/bin/hydrabot"
else
    mkdir -p "$HOME/.local/bin" 2>/dev/null || true
    WRAPPER="$HOME/.local/bin/hydrabot"
fi

cat > "$WRAPPER" << WEOF
#!/usr/bin/env bash
exec bash "$INSTALL_DIR/hydrabot" "\$@"
WEOF
chmod +x "$WRAPPER"
ok "全域指令: $WRAPPER"

# Add to PATH hint in .bashrc if not already there
PROFILE=""
[[ -f "$HOME/.bashrc" ]] && PROFILE="$HOME/.bashrc"
[[ -f "$HOME/.bash_profile" && -z "$PROFILE" ]] && PROFILE="$HOME/.bash_profile"
if [[ -n "$PROFILE" ]]; then
    WRAPPER_DIR="$(dirname "$WRAPPER")"
    if ! grep -q "$WRAPPER_DIR" "$PROFILE" 2>/dev/null; then
        echo "" >> "$PROFILE"
        echo "# HydraBot" >> "$PROFILE"
        echo "export PATH=\"$WRAPPER_DIR:\$PATH\"" >> "$PROFILE"
        ok "已寫入 PATH → $PROFILE"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════
# Done
# ══════════════════════════════════════════════════════════════
printf "\n${G}${BOLD}"
cat << 'DONE'
  ╔════════════════════════════════════════════╗
  ║   🐍  HydraBot 安裝完成！                  ║
  ╚════════════════════════════════════════════╝
DONE
printf "${NC}\n"

printf "${BOLD}  快速開始 / Quick Start${NC}\n"
hr
printf "  ${C}hydrabot start${NC}          啟動 Bot\n"
printf "  ${C}hydrabot update${NC}         更新到最新版本\n"
printf "  ${C}hydrabot config${NC}         編輯設定\n"
printf "  ${C}hydrabot status${NC}         查看狀態\n"
printf "  ${C}hydrabot help${NC}           完整說明\n"
printf "\n"
printf "  安裝目錄: ${DIM}$INSTALL_DIR${NC}\n"
printf "  去 Telegram 找到你的 Bot，發送 ${B}/start${NC} 開始！\n"
printf "\n"
printf "  ${Y}若 hydrabot 指令未生效，請執行:${NC}\n"
printf "  ${DIM}source ~/.bashrc  (或重啟終端機)${NC}\n\n"
