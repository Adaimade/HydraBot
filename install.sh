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
REMOTE_VER=$(curl -fsSL "$REPO/VERSION" 2>/dev/null | tr -d '[:space:]') || REMOTE_VER="1.1.0"
printf "${BOLD}  Self-expanding AI Assistant via Telegram  ${G}v${REMOTE_VER}${NC}\n"
printf "${DIM}  https://github.com/Adaimade/HydraBot${NC}\n\n"

# ── Risk Warning ──────────────────────────────────────────────
printf "${Y}${BOLD}⚠️  安装前请阅读以下风险提示${NC}\n"
hr
printf "\n"
printf "  HydraBot 安装后将在你的本地机器上以服务形式运行。\n"
printf "  请确认你了解并接受以下内容：\n\n"
printf "${DIM}"
printf "    · 可在你的机器上执行 Python / Shell 代码\n"
printf "    · 可读取和写入本地文件系统中的文件\n"
printf "    · 可通过 pip 自动下载并安装第三方 Python 包\n"
printf "    · 可发起对外部服务的网络请求\n"
printf "    · 可在运行时自行创建并加载新工具（自我扩展）\n\n"
printf "${NC}"
printf "  请仅在你信任来源且理解上述权限的情况下继续。\n"
printf "${DIM}  Only proceed if you trust the source and accept these permissions.${NC}\n\n"
printf "${NC}"
hr
echo ""
ask "请输入 ${Y}${BOLD}yes${NC} 确认你了解上述风险并同意继续安装: "
read -r _confirm
[[ "$_confirm" != "yes" ]] && { printf "\n  ${R}安装已取消。${NC}\n\n"; exit 0; }
echo ""

# ══════════════════════════════════════════════════════════════
# [1/6]  自动检测并安装运行环境
# ══════════════════════════════════════════════════════════════
step "[1/6] 检测并安装运行环境"

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
inf "操作系统: ${BOLD}$OS${NC}"
echo ""

# ── Helper: check Python version ──────────────────────────────
python_ok() {
    local cmd="$1"
    command -v "$cmd" &>/dev/null || return 1
    local major minor
    major=$("$cmd" -c "import sys; print(sys.version_info.major)" 2>/dev/null) || return 1
    minor=$("$cmd" -c "import sys; print(sys.version_info.minor)" 2>/dev/null) || return 1
    [[ "$major" -ge 3 && "$minor" -ge 9 ]]
}

# ── Install curl if missing ────────────────────────────────────
if ! command -v curl &>/dev/null; then
    warn "curl 未找到，尝试安装..."
    case "$OS" in
        windows) warn "请在 Git Bash 中运行，或手动安装 curl" ;;
        macos)   brew install curl 2>/dev/null || warn "安装 curl 失败，请手动安装" ;;
        debian)  sudo apt-get install -y curl -qq ;;
        fedora)  sudo dnf  install -y curl -q ;;
        redhat)  sudo yum  install -y curl -q ;;
        arch)    sudo pacman -S --noconfirm curl ;;
        alpine)  sudo apk add --quiet curl ;;
        *)       warn "无法自动安装 curl，请手动安装后重试" ;;
    esac
fi
command -v curl &>/dev/null && ok "curl  $(curl --version | head -1 | awk '{print $2}')" \
                             || err "curl 不可用，请手动安装后重试"

# ── Install Python ────────────────────────────────────────────
PYTHON=""
# Check existing python
for cmd in python3 python3.12 python3.11 python3.10 python3.9 python; do
    if python_ok "$cmd"; then
        PYTHON="$cmd"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    warn "未找到 Python 3.9+，尝试自动安装..."
    echo ""

    case "$OS" in
        windows)
            # Try winget (Windows 10 1709+)
            if command -v winget &>/dev/null; then
                inf "使用 winget 安装 Python 3.11..."
                winget install Python.Python.3.11 \
                    --silent \
                    --accept-source-agreements \
                    --accept-package-agreements \
                    || warn "winget 安装失败"
            fi
            # Try chocolatey
            if [[ -z "$PYTHON" ]] && command -v choco &>/dev/null; then
                inf "使用 Chocolatey 安装 Python..."
                choco install python311 -y || warn "choco 安装失败"
            fi
            # Re-check after install
            for cmd in python3 python3.11 python; do
                python_ok "$cmd" && { PYTHON="$cmd"; break; }
            done
            if [[ -z "$PYTHON" ]]; then
                printf "\n  ${Y}无法自动安装 Python。请手动安装：${NC}\n"
                printf "  ${C}https://www.python.org/downloads/  (勾选 Add to PATH)${NC}\n"
                printf "  安装完成后重新运行此脚本。\n\n"
                exit 1
            fi
            ;;

        macos)
            if command -v brew &>/dev/null; then
                inf "使用 Homebrew 安装 Python..."
                brew install python@3.11
            else
                inf "安装 Homebrew..."
                /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
                brew install python@3.11
            fi
            for cmd in python3.11 python3 python; do
                python_ok "$cmd" && { PYTHON="$cmd"; break; }
            done
            ;;

        debian)
            inf "使用 apt 安装 Python 3.11..."
            sudo apt-get update -qq
            sudo apt-get install -y python3.11 python3.11-venv python3-pip python3-venv \
                                    python3-full -qq 2>/dev/null \
            || sudo apt-get install -y python3 python3-venv python3-pip -qq
            for cmd in python3.11 python3 python; do
                python_ok "$cmd" && { PYTHON="$cmd"; break; }
            done
            ;;

        fedora)
            inf "使用 dnf 安装 Python..."
            sudo dnf install -y python3 python3-pip -q
            for cmd in python3 python; do python_ok "$cmd" && { PYTHON="$cmd"; break; }; done
            ;;

        redhat)
            inf "使用 yum/dnf 安装 Python..."
            sudo dnf install -y python3 python3-pip -q 2>/dev/null \
            || sudo yum install -y python3 python3-pip -q
            for cmd in python3 python; do python_ok "$cmd" && { PYTHON="$cmd"; break; }; done
            ;;

        arch)
            inf "使用 pacman 安装 Python..."
            sudo pacman -S --noconfirm python python-pip
            python_ok python && PYTHON=python
            ;;

        alpine)
            inf "使用 apk 安装 Python..."
            sudo apk add --quiet python3 py3-pip
            python_ok python3 && PYTHON=python3
            ;;

        *)
            printf "\n  ${R}不支持的系统，请手动安装 Python 3.9+：${NC}\n"
            printf "  ${C}https://www.python.org/downloads/${NC}\n\n"
            exit 1
            ;;
    esac

    [[ -z "$PYTHON" ]] && err "Python 安装失败，请手动安装 Python 3.9+ 后重试"
fi

ok "Python  $($PYTHON --version)  ($PYTHON)"

# ── Ensure pip is available ───────────────────────────────────
if ! "$PYTHON" -m pip --version &>/dev/null; then
    warn "pip 未找到，尝试安装..."
    case "$OS" in
        debian) sudo apt-get install -y python3-pip -qq ;;
        fedora|redhat) sudo dnf install -y python3-pip -q 2>/dev/null \
                     || sudo yum install -y python3-pip -q ;;
        alpine) sudo apk add --quiet py3-pip ;;
        *)  curl -fsSL https://bootstrap.pypa.io/get-pip.py | "$PYTHON" ;;
    esac
fi
"$PYTHON" -m pip --version &>/dev/null && ok "pip   $("$PYTHON" -m pip --version | awk '{print $2}')" \
                                        || err "pip 安装失败，请手动安装"

# ── Ensure venv module works ──────────────────────────────────
if ! "$PYTHON" -m venv --help &>/dev/null; then
    warn "venv 模块未找到，尝试安装..."
    case "$OS" in
        debian)
            # debian/ubuntu 需要单独安装 python3-venv
            PYVER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
            sudo apt-get install -y "python${PYVER}-venv" python3-venv -qq 2>/dev/null \
            || sudo apt-get install -y python3-full -qq
            ;;
        *)  "$PYTHON" -m pip install virtualenv -q && VENV_CMD="virtualenv" ;;
    esac
fi
"$PYTHON" -m venv --help &>/dev/null && ok "venv  已就绪" \
                                       || err "venv 不可用，请安装 python3-venv"

# ── git (optional, for future updates) ───────────────────────
if command -v git &>/dev/null; then
    ok "git   $(git --version | awk '{print $3}')"
else
    warn "git 未安装（可选，不影响运行）"
fi

echo ""

# ══════════════════════════════════════════════════════════════
# [2/6]  选择安装目录
# ══════════════════════════════════════════════════════════════
step "[2/6] 选择安装目录"
DEFAULT_DIR="$HOME/hydrabot"
ask "安装路径 [默认: ${C}$DEFAULT_DIR${NC}]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"

if [[ -d "$INSTALL_DIR" ]]; then
    printf "\n  ${Y}目录已存在，将覆盖核心文件（config.json / 自定义 tools / memory 不受影响）${NC}\n"
    ask "  继续？[Y/n]: "
    read -r _ow
    [[ "$_ow" =~ ^[Nn]$ ]] && { printf "  ${R}已取消。${NC}\n"; exit 0; }
fi

mkdir -p "$INSTALL_DIR"/{tools,mcp_servers,scripts}
export INSTALL_DIR
ok "安装目录: $INSTALL_DIR"
echo ""

# ══════════════════════════════════════════════════════════════
# [3/6]  下载核心文件
# ══════════════════════════════════════════════════════════════
step "[3/6] 下载核心文件"
CORE_FILES=(agent.py bot.py main.py tools_builtin.py requirements.txt scripts/update.sh hydrabot VERSION)
FAILED_DL=()
for f in "${CORE_FILES[@]}"; do
    printf "  %-28s " "$f"
    if curl -fsSL "$REPO/$f" -o "$INSTALL_DIR/$f" 2>/dev/null; then
        printf "${G}✓${NC}\n"
    else
        printf "${Y}⚠ (跳过)${NC}\n"
        FAILED_DL+=("$f")
    fi
done
chmod +x "$INSTALL_DIR/scripts/update.sh" "$INSTALL_DIR/hydrabot" 2>/dev/null || true
[[ ${#FAILED_DL[@]} -gt 0 ]] && warn "下载失败: ${FAILED_DL[*]}（如已存在旧版则继续）"
echo ""

# ══════════════════════════════════════════════════════════════
# [4/6]  Telegram Bot 配置
# ══════════════════════════════════════════════════════════════
step "[4/6] Telegram Bot 配置"
inf "前置步骤:"
inf "  1. Telegram 搜索 ${BOLD}@BotFather${NC}${C}，发送 /newbot，取得 Bot Token"
inf "  2. Telegram 搜索 ${BOLD}@userinfobot${NC}${C}，取得你的数字用户 ID"
echo ""

TG_TOKEN=""
while [[ -z "$TG_TOKEN" ]]; do
    ask "Bot Token: "
    read -r TG_TOKEN
    TG_TOKEN="${TG_TOKEN// /}"
    [[ -z "$TG_TOKEN" ]] && printf "  ${R}不能为空${NC}\n"
done
ok "Token 已输入"

echo ""
ask "授权用户 ID（多个用逗号分隔，${Y}留空 = 允许所有人${NC}）: "
read -r AUTH_USERS_RAW
AUTH_USERS_RAW="${AUTH_USERS_RAW// /}"
[[ -z "$AUTH_USERS_RAW" ]] && warn "未设置授权用户，所有人均可使用此 Bot！"
echo ""

# ══════════════════════════════════════════════════════════════
# [5/6]  AI 模型配置
# ══════════════════════════════════════════════════════════════
step "[5/6] AI 模型配置（最多 3 组）"
inf "模型 0 = 主力模型（必填）"
inf "模型 1 = 快速/子代理模型（选填，推荐填，让并行任务更快）"
inf "模型 2 = 备用/专用模型（选填）"
echo ""

declare -a MODEL_NAMES MODEL_PROVIDERS MODEL_KEYS MODEL_MODELS MODEL_BASE_URLS MODEL_DESCS

configure_model() {
    local IDX="$1" LABEL="$2" REQUIRED="$3"
    printf "  ${BOLD}─── 模型 ${IDX}：${LABEL} ───${NC}\n"

    if [[ "$REQUIRED" == "optional" ]]; then
        ask "  跳过此模型？[Y/n]: "
        read -r _skip
        if [[ ! "$_skip" =~ ^[Nn]$ ]]; then
            MODEL_NAMES[$IDX]="" MODEL_PROVIDERS[$IDX]=""
            MODEL_KEYS[$IDX]=""  MODEL_MODELS[$IDX]=""
            MODEL_BASE_URLS[$IDX]="null" MODEL_DESCS[$IDX]=""
            printf "  ${DIM}已跳过${NC}\n\n"; return
        fi
    fi

    printf "  选择 AI Provider:\n"
    printf "    ${B}1${NC}) Anthropic Claude         (sk-ant-api03-...)\n"
    printf "    ${B}2${NC}) OpenAI / GPT             (sk-...)\n"
    printf "    ${B}3${NC}) Google Gemini            (AI Studio API Key)\n"
    printf "    ${B}4${NC}) 自定义 OpenAI 兼容 API  (Groq / DeepSeek / Ollama...)\n"
    ask "  选择 [1/2/3/4，默认 1]: "
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
        [[ -z "$KEY" ]] && printf "  ${R}不能为空${NC}\n"
    done

    # Verify key format (basic sanity check)
    if [[ "$PROVIDER" == "anthropic" && ! "$KEY" =~ ^sk-ant ]]; then
        warn "Anthropic key 通常以 sk-ant- 开头，请确认输入正确"
    fi
    if [[ "$PROVIDER" == "openai" && ! "$KEY" =~ ^sk- ]]; then
        warn "OpenAI key 通常以 sk- 开头，请确认输入正确"
    fi

    ask "  模型名称 [默认: ${C}${MODEL_DEF}${NC}]: "
    read -r _model; _model="${_model:-$MODEL_DEF}"

    local NAME_DEF="模型${IDX}-${LABEL}"
    ask "  显示名称 [默认: ${C}${NAME_DEF}${NC}]: "
    read -r _name; _name="${_name:-$NAME_DEF}"

    ask "  用途说明（可留空）: "
    read -r _desc

    MODEL_NAMES[$IDX]="$_name"  MODEL_PROVIDERS[$IDX]="$PROVIDER"
    MODEL_KEYS[$IDX]="$KEY"     MODEL_MODELS[$IDX]="$_model"
    MODEL_BASE_URLS[$IDX]="$BASE_URL" MODEL_DESCS[$IDX]="$_desc"
    ok "模型 ${IDX} 已配置: $_name / $_model"
    echo ""
}

configure_model 0 "主力模型" "required"
configure_model 1 "快速模型 (子代理推荐)" "optional"
configure_model 2 "备用/专用模型" "optional"

# ══════════════════════════════════════════════════════════════
# [6/6]  写入配置、建立环境、安装依赖
# ══════════════════════════════════════════════════════════════
step "[6/6] 写入配置 & 安装依赖"

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
    print("❌ 至少需要配置一个模型！", file=sys.stderr); sys.exit(1)

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
print(f"  ✅  模型数量: {len(models)} 组")
print(f"  ✅  授权用户: {auth if auth else '（不限制）'}")
PYEOF

# ── Virtual environment ────────────────────────────────────────
printf "\n  📦 建立 Python 虚拟环境...\n"
"$PYTHON" -m venv "$INSTALL_DIR/venv"
ok "虚拟环境: $INSTALL_DIR/venv"

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
printf "  📦 安装 Python 依赖（python-telegram-bot / anthropic / openai / requests）...\n"
pip install -r "$INSTALL_DIR/requirements.txt" -q --disable-pip-version-check
ok "所有依赖已安装"

# ── Global hydrabot command ────────────────────────────────────
printf "\n  🔗 创建全局命令...\n"
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
ok "全局命令: $WRAPPER"

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
        ok "已写入 PATH → $PROFILE"
    fi
fi

echo ""

# ══════════════════════════════════════════════════════════════
# Done
# ══════════════════════════════════════════════════════════════
printf "\n${G}${BOLD}"
cat << 'DONE'
  ╔════════════════════════════════════════════╗
  ║   🐍  HydraBot 安装完成！                  ║
  ╚════════════════════════════════════════════╝
DONE
printf "${NC}\n"

printf "${BOLD}  快速开始 / Quick Start${NC}\n"
hr
printf "  ${C}hydrabot start${NC}          启动 Bot\n"
printf "  ${C}hydrabot update${NC}         更新到最新版本\n"
printf "  ${C}hydrabot config${NC}         编辑配置\n"
printf "  ${C}hydrabot status${NC}         查看状态\n"
printf "  ${C}hydrabot help${NC}           完整帮助\n"
printf "\n"
printf "  安装目录: ${DIM}$INSTALL_DIR${NC}\n"
printf "  去 Telegram 找到你的 Bot，发送 ${B}/start${NC} 开始！\n"
printf "\n"
printf "  ${Y}若 hydrabot 命令未生效，请执行:${NC}\n"
printf "  ${DIM}source ~/.bashrc  (或重启终端)${NC}\n\n"
