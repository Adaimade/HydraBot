#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#   HydraBot Updater
#   Usage:  hydrabot update
#           bash scripts/update.sh
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

# ── Colors ────────────────────────────────────────────────────
G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'
BOLD='\033[1m'; DIM='\033[2m'; R='\033[0;31m'; NC='\033[0m'

ok()  { printf "  ${G}✅ $*${NC}\n"; }
inf() { printf "  ${C}ℹ  $*${NC}\n"; }
warn(){ printf "  ${Y}⚠  $*${NC}\n"; }
err() { printf "  ${R}❌ $*${NC}\n"; exit 1; }
hr()  { printf "${DIM}────────────────────────────────────────────────────${NC}\n"; }

REPO="https://raw.githubusercontent.com/Adaimade/HydraBot/main"

# ── Detect install directory ──────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# Verify we're in a HydraBot directory
[[ -f "main.py" && -f "agent.py" && -f "requirements.txt" ]] \
    || err "请在 HydraBot 安装目录下运行此脚本 / Run from HydraBot directory"

# ── Banner ────────────────────────────────────────────────────
printf "\n${C}${BOLD}🐍 HydraBot Updater${NC}\n"
hr

# ── Version check ─────────────────────────────────────────────
LOCAL_VER=$(cat VERSION 2>/dev/null | tr -d '[:space:]') || LOCAL_VER="unknown"
REMOTE_VER=$(curl -fsSL "$REPO/VERSION" 2>/dev/null | tr -d '[:space:]') || REMOTE_VER="unknown"

inf "当前版本: ${BOLD}$LOCAL_VER${NC}"
inf "最新版本: ${BOLD}${G}$REMOTE_VER${NC}"

if [[ "$LOCAL_VER" == "$REMOTE_VER" && "$LOCAL_VER" != "unknown" ]]; then
    printf "\n  ${G}✨ 已是最新版本！${NC}\n"
    printf "  如需强制更新，请运行: ${DIM}bash scripts/update.sh --force${NC}\n\n"
    [[ "${1:-}" != "--force" ]] && exit 0
fi

echo ""
printf "  即将更新以下核心文件（${Y}config.json / 自定义 tools / memory 不受影响${NC}）:\n"
printf "  agent.py  bot.py  main.py  tools_builtin.py  requirements.txt  scripts/update.sh  hydrabot  VERSION\n\n"

printf "  ${BOLD}继续更新？[Y/n]: ${NC}"
read -r _confirm
[[ "$_confirm" =~ ^[Nn]$ ]] && { printf "  已取消。\n\n"; exit 0; }
echo ""

# ── Backup user data ──────────────────────────────────────────
printf "\n  💾 备份用户数据...\n"

if [[ -f "config.json" ]]; then
    cp config.json "config.json.bak"
    ok "已备份 config.json"
fi

if [[ -d "tools" ]] && [[ $(ls -A tools 2>/dev/null) ]]; then
    tar czf tools.tar.gz tools/ 2>/dev/null || true
    ok "已备份自定义 tools"
fi

if [[ -f "memory.json" ]]; then
    cp memory.json "memory.json.bak"
    ok "已备份 memory.json"
fi

# ── Count existing tools (before update) ─────────────────────
OLD_TOOLS=$(grep -c "^    (" tools_builtin.py 2>/dev/null || echo "?")

# ── Download updates ──────────────────────────────────────────
printf "\n  📥 下载更新...\n"
hr

CORE_FILES=(agent.py bot.py main.py cli.py discord_bot.py learning.py tools_builtin.py scheduler.py requirements.txt scripts/update.sh hydrabot VERSION)
FAILED=()
mkdir -p scripts
for f in "${CORE_FILES[@]}"; do
    printf "  %-30s " "$f"
    if curl -fsSL "$REPO/$f" -o "$f.tmp" 2>/dev/null; then
        mv "$f.tmp" "$f"
        printf "${G}✓${NC}\n"
    else
        rm -f "$f.tmp"
        printf "${Y}⚠ (保留旧版)${NC}\n"
        FAILED+=("$f")
    fi
done

chmod +x scripts/update.sh hydrabot 2>/dev/null || true

# ── Restore user data ──────────────────────────────────────────
printf "\n  📥 恢复用户数据...\n"

if [[ -f "config.json.bak" ]]; then
    cp config.json.bak config.json
    ok "已恢复 config.json（保留您的设定）"
fi

if [[ -f "tools.tar.gz" ]]; then
    tar xzf tools.tar.gz 2>/dev/null || true
    rm -f tools.tar.gz
    ok "已恢复自定义 tools"
fi

if [[ -f "memory.json.bak" ]]; then
    cp memory.json.bak memory.json
    ok "已恢复 memory.json（保留对话历史）"
fi

# ── Update dependencies ───────────────────────────────────────
printf "\n  📦 更新 Python 依赖...\n"

PYTHON=""
for cmd in python3 python; do
    command -v "$cmd" &>/dev/null && PYTHON="$cmd" && break
done

if [[ -n "$PYTHON" ]]; then
    if [[ -f "venv/Scripts/activate" ]]; then
        source venv/Scripts/activate
    elif [[ -f "venv/bin/activate" ]]; then
        source venv/bin/activate
    fi
    pip install -r requirements.txt -q --upgrade --disable-pip-version-check
    ok "依赖已更新"
else
    warn "找不到 Python，跳过依赖更新"
fi

# ── Show new tools ────────────────────────────────────────────
NEW_TOOLS=$(grep -c "^    (" tools_builtin.py 2>/dev/null || echo "?")
NEW_VER=$(cat VERSION 2>/dev/null | tr -d '[:space:]') || NEW_VER="unknown"

echo ""
hr
printf "\n${G}${BOLD}  ✨ 更新完成！${NC}\n\n"
printf "  版本:    ${DIM}$LOCAL_VER${NC}  →  ${G}${BOLD}$NEW_VER${NC}\n"

if [[ "$OLD_TOOLS" != "?" && "$NEW_TOOLS" != "?" ]]; then
    DIFF=$((NEW_TOOLS - OLD_TOOLS))
    if [[ $DIFF -gt 0 ]]; then
        printf "  内建工具: ${DIM}$OLD_TOOLS${NC}  →  ${G}${BOLD}$NEW_TOOLS${NC}  ${G}(+${DIFF} 新工具)${NC}\n"
    else
        printf "  内建工具: ${G}$NEW_TOOLS 个${NC}\n"
    fi
fi

if [[ ${#FAILED[@]} -gt 0 ]]; then
    warn "以下文件下载失败，已保留旧版: ${FAILED[*]}"
fi

printf "\n  重启 Bot 以应用更新: ${C}hydrabot start${NC}\n\n"
