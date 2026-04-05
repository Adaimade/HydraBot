"""
SubAgentManager — manages persistent HydraBot sub-agent instances.

Each sub-agent is a fully independent HydraBot process running from its own
folder under agents/{name}/. Because all file I/O in the core code uses
relative paths, setting cwd=agents/{name}/ automatically isolates:
  - config.json  (token, models)
  - memory.json
  - timezones.json
  - schedules.json
  - tools/       (dynamic tools)

The parent bot tracks sub-agents in agents.json and restarts them on launch.
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_NAME_MAX = 32


def _valid_name(name: str) -> bool:
    """Only allow chars that are safe as a folder name."""
    return (
        bool(name)
        and len(name) <= _NAME_MAX
        and all(c.isalnum() or c in "-_" for c in name)
        and name[0].isalnum()
    )


def _valid_token(token: str) -> bool:
    """Telegram bot tokens look like  1234567890:ABCdef..."""
    parts = token.strip().split(":")
    return len(parts) == 2 and parts[0].isdigit() and len(parts[1]) >= 10


class SubAgentManager:
    """
    Lifecycle manager for HydraBot sub-agent bot instances.

    Usage (from TelegramBot):
        self.sub_agents = SubAgentManager(base_dir)
        self.sub_agents.start_all()   # on startup
        self.sub_agents.stop_all()    # on shutdown (optional)
    """

    def __init__(self, base_dir: str):
        self.base_dir = Path(base_dir).resolve()
        self.agents_dir = self.base_dir / "agents"
        self.registry_path = self.base_dir / "agents.json"
        self._agents: dict[str, dict] = {}   # name → metadata
        self._procs: dict[str, subprocess.Popen] = {}  # name → process
        self._load()

    # ── Persistence ───────────────────────────────────────────────

    def _load(self):
        if self.registry_path.exists():
            try:
                self._agents = json.loads(
                    self.registry_path.read_text(encoding="utf-8")
                )
            except Exception:
                self._agents = {}

    def _save(self):
        self.registry_path.write_text(
            json.dumps(self._agents, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ── Validation ────────────────────────────────────────────────

    @staticmethod
    def validate_name(name: str) -> str | None:
        """Return error string, or None if name is valid."""
        name = name.strip()
        if not name:
            return "名稱不能為空"
        if not _valid_name(name):
            return (
                f"名稱只能包含英文字母、數字、`-` 和 `_`，"
                f"且必須以字母或數字開頭，最多 {_NAME_MAX} 字元"
            )
        return None

    @staticmethod
    def validate_token(token: str) -> str | None:
        """Return error string, or None if token looks valid."""
        token = token.strip()
        if not _valid_token(token):
            return (
                "Token 格式不正確。\n"
                "Telegram Bot Token 格式為：`數字:英數字串`\n"
                "例如：`7654321:ABCdefGHIjklmno`"
            )
        return None

    # ── Lifecycle ─────────────────────────────────────────────────

    def create(self, name: str, token: str, parent_config: dict) -> str:
        """
        Create a new sub-agent folder + config, then start its process.
        Returns a status message string.
        """
        name = name.strip()
        token = token.strip()

        err = self.validate_name(name)
        if err:
            return f"❌ {err}"

        if name in self._agents:
            return f"❌ 子代理 **{name}** 已存在，請使用其他名稱"

        agent_dir = self.agents_dir / name
        agent_dir.mkdir(parents=True, exist_ok=True)

        # Sub-agent config: inherit models and limits, use new token.
        # is_sub_agent=True prevents the sub-bot from registering /new_agent.
        config = {
            "telegram_token": token,
            "authorized_users": parent_config.get("authorized_users", []),
            "max_tokens": parent_config.get("max_tokens", 4096),
            "max_history": parent_config.get("max_history", 50),
            "models": parent_config.get("models", []),
            "is_sub_agent": True,
        }
        (agent_dir / "config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self._agents[name] = {
            "name": name,
            "folder": f"agents/{name}",
            "token_hint": token[:12] + "…",  # never store full token
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        }
        self._save()

        err = self._start(name)
        if err:
            return (
                f"⚠️ 子代理 **{name}** 資料夾已建立，但啟動失敗：\n{err}\n\n"
                f"可手動進入 `agents/{name}/` 並執行 `python main.py`"
            )

        return f"✅ 子代理 **{name}** 已建立並啟動"

    def _start(self, name: str) -> str | None:
        """
        Launch the sub-agent process.
        Returns error string on failure, None on success.
        """
        info = self._agents.get(name)
        if not info:
            return "找不到該子代理記錄"

        agent_dir = self.base_dir / info["folder"]
        main_py = self.base_dir / "main.py"

        if not agent_dir.exists():
            return f"資料夾不存在: {agent_dir}"
        if not main_py.exists():
            return f"找不到 main.py: {main_py}"

        try:
            log_fh = open(agent_dir / "bot.log", "a", encoding="utf-8")
            try:
                proc = subprocess.Popen(
                    [sys.executable, str(main_py)],
                    cwd=str(agent_dir),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                )
            finally:
                # The subprocess has inherited the fd; close the Python wrapper.
                log_fh.close()
            self._procs[name] = proc
            return None
        except Exception as e:
            return str(e)

    def start_all(self):
        """Start all registered sub-agents. Called on parent bot startup."""
        if not self._agents:
            return
        print(f"🤖 Starting {len(self._agents)} sub-agent(s)...")
        for name in list(self._agents.keys()):
            err = self._start(name)
            if err:
                print(f"   ⚠️  {name}: {err}")
            else:
                print(f"   ✅  {name} started (PID {self._procs[name].pid})")

    def stop(self, name: str):
        """Gracefully stop a sub-agent process."""
        proc = self._procs.pop(name, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def stop_all(self):
        """Stop all running sub-agent processes."""
        for name in list(self._procs.keys()):
            self.stop(name)

    def delete(self, name: str) -> bool:
        """
        Stop and permanently delete a sub-agent (process + folder + registry).
        Returns True if the agent existed.
        """
        if name not in self._agents:
            return False

        self.stop(name)
        info = self._agents.pop(name, {})
        self._save()

        agent_dir = self.base_dir / info.get("folder", f"agents/{name}")
        if agent_dir.exists():
            shutil.rmtree(agent_dir, ignore_errors=True)

        return True

    # ── Queries ───────────────────────────────────────────────────

    def _proc_status(self, name: str) -> str:
        proc = self._procs.get(name)
        if proc and proc.poll() is None:
            return "🟢 運行中"
        return "🔴 已停止"

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def get(self, name: str) -> dict | None:
        return self._agents.get(name)

    def count(self) -> int:
        return len(self._agents)

    def status_text(self) -> str:
        if not self._agents:
            return (
                "📋 目前沒有子代理 Bot\n\n"
                "使用 `/new_agent` 建立一個獨立的子代理 Bot"
            )
        lines = [f"🤖 **子代理 Bot** ({len(self._agents)} 個)\n"]
        for name, info in self._agents.items():
            status = self._proc_status(name)
            lines.append(
                f"{status} **{name}**\n"
                f"   建立：{info.get('created_at', '?')} | "
                f"Token：`{info.get('token_hint', '?')}`"
            )
        lines.append("\n使用 `/delete_agent` 刪除子代理")
        return "\n".join(lines)
