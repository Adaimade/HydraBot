#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#   HydraBot Installer
#   Usage:  bash <(curl -fsSL https://raw.githubusercontent.com/Adaimade/HydraBot/main/install.sh)
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
R='\033[0;31m'; Y='\033[1;33m'; G='\033[0;32m'
C='\033[0;36m'; B='\033[1;34m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

hr()  { printf "${DIM}────────────────────────────────────────────────────${NC}\n"; }
ok()  { printf "  ${G}✅ $*${NC}\n"; }
err() { printf "  ${R}❌ $*${NC}\n"; exit 1; }
inf() { printf "  ${C}ℹ  $*${NC}\n"; }
ask() { printf "  ${BOLD}$*${NC} "; }

REPO="https://raw.githubusercontent.com/Adaimade/HydraBot/main"
REPO_ZIP="https://github.com/Adaimade/HydraBot/archive/refs/heads/main.zip"

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
printf "${Y}${BOLD}⚠️  安全风险提示 / Security Risk Warning${NC}\n"
hr
printf "${Y}"
printf "  本程序安装后将在你的本地机器上持续运行，拥有以下能力：\n\n"
printf "  [危险] 执行任意 Python / Shell 代码\n"
printf "  [危险] 读写本地文件系统中的任何文件\n"
printf "  [危险] 通过 pip 自动安装 Python 包\n"
printf "  [危险] 发起对外网络请求\n"
printf "  [危险] 自我扩展：在运行时创建并加载新工具\n\n"
printf "  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
printf "  [EN] After installation, this program runs on your\n"
printf "  local machine with code execution, filesystem,\n"
printf "  network access, and self-extension capabilities.\n\n"
printf "  ⚠  ONLY authorize Telegram user IDs you fully trust.\n"
printf "  ⚠  Keep your API keys and config.json private.\n"
printf "  ⚠  Treat this like giving someone shell access.\n"
printf "${NC}"
hr
printf "\n"
ask "请输入 ${Y}${BOLD}yes${NC} 确认你了解上述风险并同意继续安装: "
read -r _confirm
if [[ "$_confirm" != "yes" ]]; then
    printf "\n  ${R}安装已取消 / Installation cancelled.${NC}\n\n"
    exit 0
fi
echo ""

# ── Python check ──────────────────────────────────────────────
printf "${BOLD}[1/6] 检查系统环境${NC}\n"
hr
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(sys.version_info[:2])" 2>/dev/null)
        MAJOR=$("$cmd" -c "import sys; print(sys.version_info.major)")
        MINOR=$("$cmd" -c "import sys; print(sys.version_info.minor)")
        if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 9 ]]; then
            PYTHON="$cmd"
            ok "Python $("$cmd" --version)  ($cmd)"
            break
        fi
    fi
done
[[ -z "$PYTHON" ]] && err "需要 Python 3.9 或更高版本 / Python 3.9+ required"

command -v curl &>/dev/null && ok "curl 已安装" || err "需要 curl / curl required"
echo ""

# ── Install directory ─────────────────────────────────────────
printf "${BOLD}[2/6] 选择安装目录${NC}\n"
hr
DEFAULT_DIR="$HOME/hydrabot"
ask "安装路径 [默认: ${C}$DEFAULT_DIR${NC}]: "
read -r INSTALL_DIR
INSTALL_DIR="${INSTALL_DIR:-$DEFAULT_DIR}"
INSTALL_DIR="${INSTALL_DIR/#\~/$HOME}"   # expand ~

if [[ -d "$INSTALL_DIR" ]]; then
    printf "\n  ${Y}目录已存在，将覆盖核心文件（config.json、自定义工具不受影响）${NC}\n"
    ask "  继续？[Y/n]: "
    read -r _ow
    [[ "$_ow" =~ ^[Nn]$ ]] && { printf "  ${R}已取消。${NC}\n"; exit 0; }
fi

mkdir -p "$INSTALL_DIR"/{tools,mcp_servers}
ok "安装目录: $INSTALL_DIR"
echo ""

# ── Download core files ───────────────────────────────────────
printf "${BOLD}[3/6] 下载核心文件${NC}\n"
hr
CORE_FILES=(agent.py bot.py main.py tools_builtin.py requirements.txt update.sh hydrabot VERSION)
for f in "${CORE_FILES[@]}"; do
    printf "  下载 %-25s " "$f"
    if curl -fsSL "$REPO/$f" -o "$INSTALL_DIR/$f" 2>/dev/null; then
        printf "${G}✓${NC}\n"
    else
        printf "${R}✗ (跳过)${NC}\n"
    fi
done
# Make scripts executable
chmod +x "$INSTALL_DIR/update.sh" "$INSTALL_DIR/hydrabot" 2>/dev/null || true
echo ""

# ── Telegram setup ────────────────────────────────────────────
printf "${BOLD}[4/6] Telegram Bot 配置${NC}\n"
hr
inf "去 @BotFather 发 /newbot 获取 Token"
inf "去 @userinfobot 获取你的数字用户 ID"
echo ""

TG_TOKEN=""
while [[ -z "$TG_TOKEN" ]]; do
    ask "Telegram Bot Token: "
    read -r TG_TOKEN
    TG_TOKEN="${TG_TOKEN// /}"
    [[ -z "$TG_TOKEN" ]] && printf "  ${R}不能为空 / cannot be empty${NC}\n"
done

ask "授权用户 ID（多个用逗号分隔，留空 = 不限制）: "
read -r AUTH_USERS_RAW
AUTH_USERS_RAW="${AUTH_USERS_RAW// /}"
echo ""

# ── Model configuration ───────────────────────────────────────
printf "${BOLD}[5/6] AI 模型配置${NC}\n"
hr
inf "配置最多 3 组模型（模型 0 为必填主力模型，1/2 可跳过）"
inf "子代理默认使用模型 1（快速）；复杂任务用模型 0（主力）"
echo ""

declare -a MODEL_NAMES MODEL_PROVIDERS MODEL_KEYS MODEL_MODELS MODEL_BASE_URLS MODEL_DESCS

configure_model() {
    local IDX=$1
    local LABEL=$2
    local REQUIRED=$3

    printf "  ${BOLD}─── 模型 ${IDX}：${LABEL} ───${NC}\n"

    if [[ "$REQUIRED" == "optional" ]]; then
        ask "  跳过此模型？[Y/n]: "
        read -r _skip
        if [[ ! "$_skip" =~ ^[Nn]$ ]]; then
            MODEL_NAMES[$IDX]=""
            MODEL_PROVIDERS[$IDX]=""
            MODEL_KEYS[$IDX]=""
            MODEL_MODELS[$IDX]=""
            MODEL_BASE_URLS[$IDX]="null"
            MODEL_DESCS[$IDX]=""
            printf "  ${DIM}已跳过${NC}\n\n"
            return
        fi
    fi

    # Provider
    printf "  选择 Provider:\n"
    printf "    ${B}1${NC}) Anthropic (Claude)  — sk-ant-...\n"
    printf "    ${B}2${NC}) OpenAI (GPT)         — sk-...\n"
    printf "    ${B}3${NC}) 自定义 OpenAI 兼容 API\n"
    ask "  选择 [1/2/3]: "
    read -r _prov_choice

    local PROVIDER MODEL_DEFAULT BASE_URL="null"
    case "$_prov_choice" in
        2)  PROVIDER="openai";    MODEL_DEFAULT="gpt-4o-mini"   ;;
        3)  PROVIDER="openai"
            ask "  Base URL (如 https://api.groq.com/openai/v1): "
            read -r _bu
            BASE_URL="\"${_bu// /}\""
            MODEL_DEFAULT="your-model-name"
            ;;
        *)  PROVIDER="anthropic"; MODEL_DEFAULT="claude-sonnet-4-6" ;;
    esac

    # API Key (hidden input)
    local KEY=""
    while [[ -z "$KEY" ]]; do
        ask "  API Key: "
        read -rs KEY; echo ""
        KEY="${KEY// /}"
        [[ -z "$KEY" ]] && printf "  ${R}不能为空${NC}\n"
    done

    # Model name
    ask "  模型名称 [默认: ${C}${MODEL_DEFAULT}${NC}]: "
    read -r _model
    _model="${_model:-$MODEL_DEFAULT}"

    # Display name
    local NAME_DEFAULT="模型${IDX}-${LABEL}"
    ask "  显示名称 [默认: ${C}${NAME_DEFAULT}${NC}]: "
    read -r _name
    _name="${_name:-$NAME_DEFAULT}"

    # Description
    ask "  用途说明（可留空）: "
    read -r _desc

    MODEL_NAMES[$IDX]="$_name"
    MODEL_PROVIDERS[$IDX]="$PROVIDER"
    MODEL_KEYS[$IDX]="$KEY"
    MODEL_MODELS[$IDX]="$_model"
    MODEL_BASE_URLS[$IDX]="$BASE_URL"
    MODEL_DESCS[$IDX]="$_desc"
    ok "模型 ${IDX} 已配置: $_name ($_model)"
    echo ""
}

configure_model 0 "主力模型（必填）" "required"
configure_model 1 "快速模型（子代理推荐）" "optional"
configure_model 2 "备用/专用模型" "optional"

# ── Write config.json ─────────────────────────────────────────
printf "${BOLD}[6/6] 写入配置文件${NC}\n"
hr

# Export vars for Python to consume safely
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

"$PYTHON" << 'PYEOF'
import json, os

def env(k, d=""): return os.environ.get(k, d)

# Parse authorized users
raw = env("HB_AUTH_RAW").strip()
auth = [int(x.strip()) for x in raw.split(",") if x.strip().lstrip("-").isdigit()]

# Build models array
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
    raise SystemExit("❌ 至少需要配置一个模型！")

config = {
    "telegram_token":  env("HB_TG_TOKEN"),
    "authorized_users": auth,
    "max_tokens":  4096,
    "max_history": 50,
    "models": models,
}

dest = os.environ.get("INSTALL_DIR", ".")
path = os.path.join(dest, "config.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
print(f"  ✅ config.json → {path}")
print(f"  ✅ 模型数量: {len(models)}")
print(f"  ✅ 授权用户: {auth if auth else '（不限制）'}")
PYEOF

# Setup venv + install deps
printf "\n  📦 建立虚拟环境并安装依赖...\n"
"$PYTHON" -m venv "$INSTALL_DIR/venv"
if [[ -f "$INSTALL_DIR/venv/Scripts/activate" ]]; then
    source "$INSTALL_DIR/venv/Scripts/activate"
else
    source "$INSTALL_DIR/venv/bin/activate"
fi
pip install -r "$INSTALL_DIR/requirements.txt" -q --disable-pip-version-check
ok "依赖安装完成"

# ── Create global hydrabot command ────────────────────────────
WRAPPER=""
# Try ~/.local/bin (Linux/macOS)
LOCAL_BIN="$HOME/.local/bin"
if [[ ":$PATH:" == *":$LOCAL_BIN:"* ]] || mkdir -p "$LOCAL_BIN" 2>/dev/null; then
    WRAPPER="$LOCAL_BIN/hydrabot"
fi
# Windows Git Bash: try ~/bin
if [[ -z "$WRAPPER" ]] || [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]]; then
    mkdir -p "$HOME/bin" 2>/dev/null
    WRAPPER="$HOME/bin/hydrabot"
fi

cat > "$WRAPPER" << WEOF
#!/usr/bin/env bash
exec bash "$INSTALL_DIR/hydrabot" "\$@"
WEOF
chmod +x "$WRAPPER"
ok "全局命令: $WRAPPER"

echo ""

# ── Done ──────────────────────────────────────────────────────
printf "\n${G}${BOLD}"
cat << 'DONE'
  ╔═══════════════════════════════════════╗
  ║   🐍  HydraBot 安装完成！             ║
  ╚═══════════════════════════════════════╝
DONE
printf "${NC}\n"

printf "${BOLD}  快速开始 / Quick Start${NC}\n"
hr
printf "  启动 Bot:      ${C}hydrabot start${NC}    (或 ${DIM}cd $INSTALL_DIR && bash hydrabot start${NC})\n"
printf "  更新:          ${C}hydrabot update${NC}\n"
printf "  编辑配置:      ${C}hydrabot config${NC}\n"
printf "  查看帮助:      ${C}hydrabot help${NC}\n"
printf "\n"
printf "  安装目录:  ${DIM}$INSTALL_DIR${NC}\n"
printf "  在 Telegram 找到你的 Bot，发送 ${B}/start${NC} 开始！\n"
printf "\n"
printf "  ${Y}如果 'hydrabot' 命令未找到，请重启终端或运行:${NC}\n"
printf "  ${DIM}export PATH=\"\$HOME/.local/bin:\$HOME/bin:\$PATH\"${NC}\n\n"
