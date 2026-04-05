#!/usr/bin/env python3
"""
HydraBot 核心邏輯單元測試。
不需要真實 API key — 用 mock 替代 LLM 呼叫。
"""

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest import mock

import pytest

# 確保專案根目錄在 path 中
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── helpers ──────────────────────────────────────────────────

def _make_config(**overrides) -> dict:
    """產生最小可用 config（不需要真實 API key）。"""
    base = {
        "models": [{
            "name": "mock",
            "provider": "openai",
            "api_key": "sk-test-fake-key",
            "model": "mock-model",
            "base_url": "http://127.0.0.1:1/v1",
        }],
        "max_tokens": 100,
        "max_history": 20,
        "permission_mode": "auto",
        "denied_commands": ["rm -rf /"],
        "denied_paths": [],
        "tool_trace_stdout": False,
        "tool_trace_to_chat": False,
    }
    base.update(overrides)
    return base


def _make_pool(tmp_path: Path, **config_overrides):
    """建立 AgentPool，install_dir / workspace_dir 指向 tmp。"""
    config = _make_config(**config_overrides)
    config["_hydrabot_install_dir"] = str(tmp_path)
    config["_hydrabot_workspace_dir"] = str(tmp_path)
    from agent import AgentPool
    pool = AgentPool(config)
    return pool


# ══════════════════════════════════════════════════════════════
# 1. 權限系統
# ══════════════════════════════════════════════════════════════

class TestPermission:
    def test_readonly_blocks_write_tools(self, tmp_path):
        pool = _make_pool(tmp_path, permission_mode="readonly")
        session_id = (1, None)
        result = pool._check_permission("execute_shell", {"command": "ls"}, session_id)
        assert result is not None
        assert "唯讀" in result

    def test_readonly_allows_read_tools(self, tmp_path):
        pool = _make_pool(tmp_path, permission_mode="readonly")
        session_id = (1, None)
        result = pool._check_permission("read_file", {"path": "test.py"}, session_id)
        assert result is None

    def test_auto_allows_everything(self, tmp_path):
        pool = _make_pool(tmp_path, permission_mode="auto")
        session_id = (1, None)
        result = pool._check_permission("execute_shell", {"command": "ls"}, session_id)
        assert result is None

    def test_denied_commands_blocks(self, tmp_path):
        pool = _make_pool(tmp_path, denied_commands=["rm -rf /", "mkfs"])
        session_id = (1, None)
        result = pool._check_permission("execute_shell", {"command": "rm -rf /"}, session_id)
        assert result is not None
        assert "黑名單" in result

    def test_denied_commands_allows_safe(self, tmp_path):
        pool = _make_pool(tmp_path, denied_commands=["rm -rf /"])
        session_id = (1, None)
        result = pool._check_permission("execute_shell", {"command": "ls -la"}, session_id)
        assert result is None

    def test_denied_paths_blocks(self, tmp_path):
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        pool = _make_pool(tmp_path, denied_paths=[str(ssh_dir)])
        session_id = (1, None)
        result = pool._check_permission("read_file", {"path": str(ssh_dir / "id_rsa")}, session_id)
        assert result is not None
        assert "黑名單" in result

    def test_default_mode_cli_approval(self, tmp_path):
        pool = _make_pool(tmp_path, permission_mode="default")
        cli_session = (0, None)
        approved = []
        pool._cli_approval_callback = lambda name, inputs: (approved.append(True), False)[1]
        result = pool._check_permission("execute_shell", {"command": "echo hi"}, cli_session)
        assert result is not None
        assert len(approved) == 1

    def test_dry_run_blocks_all(self, tmp_path):
        pool = _make_pool(tmp_path, dry_run=True)
        session_id = (1, None)
        result = pool._call_tool("read_file", {"path": "x"}, pool.tools, session_id=session_id)
        assert "dry-run" in result


# ══════════════════════════════════════════════════════════════
# 2. Conversation 鎖安全
# ══════════════════════════════════════════════════════════════

class TestConversationLock:
    def test_concurrent_append(self, tmp_path):
        pool = _make_pool(tmp_path)
        sid = (99, None)
        pool.conversations[sid] = []
        errors = []

        def _append(n):
            try:
                with pool._conv_lock:
                    pool.conversations[sid].append({"role": "user", "content": str(n)})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_append, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(pool.conversations[sid]) == 50

    def test_reset_conversation(self, tmp_path):
        pool = _make_pool(tmp_path)
        sid = (100, None)
        pool.conversations[sid] = [{"role": "user", "content": "hi"}]
        pool.reset_conversation(sid)
        assert sid not in pool.conversations


# ══════════════════════════════════════════════════════════════
# 3. Session 持久化
# ══════════════════════════════════════════════════════════════

class TestSessionPersistence:
    def test_save_and_load(self, tmp_path):
        pool = _make_pool(tmp_path)
        sid = (42, None)
        pool.conversations[sid] = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        pool.user_model[sid] = 0
        pool.save_session(sid)

        pool2 = _make_pool(tmp_path)
        ok = pool2.load_session(sid)
        assert ok
        assert len(pool2.conversations[sid]) == 2
        assert pool2.conversations[sid][0]["content"] == "hello"

    def test_load_nonexistent(self, tmp_path):
        pool = _make_pool(tmp_path)
        ok = pool.load_session((999, None))
        assert not ok

    def test_reset_deletes_file(self, tmp_path):
        pool = _make_pool(tmp_path)
        sid = (43, None)
        pool.conversations[sid] = [{"role": "user", "content": "x"}]
        pool.save_session(sid)
        assert pool._session_file(sid).exists()
        pool.reset_conversation(sid)
        assert not pool._session_file(sid).exists()


# ══════════════════════════════════════════════════════════════
# 4. Token 追蹤
# ══════════════════════════════════════════════════════════════

class TestTokenTracking:
    def test_record_and_get(self, tmp_path):
        pool = _make_pool(tmp_path)
        sid = (10, None)
        pool._record_usage(sid, 100, 50)
        pool._record_usage(sid, 200, 80)

        su = pool.get_token_usage(sid)
        assert su["prompt_tokens"] == 300
        assert su["completion_tokens"] == 130
        assert su["api_calls"] == 2

        gl = pool.get_token_usage()
        assert gl["prompt_tokens"] == 300

    def test_separate_sessions(self, tmp_path):
        pool = _make_pool(tmp_path)
        pool._record_usage((1, None), 100, 50)
        pool._record_usage((2, None), 200, 80)

        s1 = pool.get_token_usage((1, None))
        s2 = pool.get_token_usage((2, None))
        assert s1["prompt_tokens"] == 100
        assert s2["prompt_tokens"] == 200


# ══════════════════════════════════════════════════════════════
# 5. Context 壓縮
# ══════════════════════════════════════════════════════════════

class TestContextCompaction:
    def test_no_compact_below_threshold(self, tmp_path):
        pool = _make_pool(tmp_path, max_history=20)
        sid = (50, None)
        pool.conversations[sid] = [
            {"role": "user", "content": f"msg {i}"} for i in range(10)
        ]
        pool._maybe_compact_context(sid)
        assert len(pool.conversations[sid]) == 10

    def test_compact_triggers_at_threshold(self, tmp_path):
        pool = _make_pool(tmp_path, max_history=20)
        sid = (51, None)
        pool.conversations[sid] = [
            {"role": "user", "content": f"msg {i}"} for i in range(18)
        ]
        with mock.patch.object(pool, "_summarize_messages", return_value="摘要內容"):
            pool._maybe_compact_context(sid)

        history = pool.conversations[sid]
        assert len(history) < 18
        assert "[系統摘要]" in history[0]["content"]

    def test_compact_skips_when_summary_fails(self, tmp_path):
        pool = _make_pool(tmp_path, max_history=20)
        sid = (52, None)
        msgs = [{"role": "user", "content": f"msg {i}"} for i in range(18)]
        pool.conversations[sid] = msgs[:]
        with mock.patch.object(pool, "_summarize_messages", return_value=None):
            pool._maybe_compact_context(sid)
        assert len(pool.conversations[sid]) == 18


# ══════════════════════════════════════════════════════════════
# 6. 工具系統
# ══════════════════════════════════════════════════════════════

class TestTools:
    def test_builtin_tools_loaded(self, tmp_path):
        pool = _make_pool(tmp_path)
        assert "read_file" in pool.tools
        assert "execute_shell" in pool.tools
        assert "grep_search" in pool.tools
        assert "find_files" in pool.tools
        assert "write_file" in pool.tools

    def test_grep_search(self, tmp_path):
        pool = _make_pool(tmp_path)
        (tmp_path / "hello.py").write_text("def hello():\n    pass\n", encoding="utf-8")
        _, fn = pool.tools["grep_search"]
        result = fn(pattern="def hello", path=".")
        assert "hello" in result

    def test_find_files(self, tmp_path):
        pool = _make_pool(tmp_path)
        (tmp_path / "test.md").write_text("# Test", encoding="utf-8")
        _, fn = pool.tools["find_files"]
        result = fn(name="*.md")
        assert "test.md" in result

    def test_read_file(self, tmp_path):
        pool = _make_pool(tmp_path)
        (tmp_path / "data.txt").write_text("line1\nline2\n", encoding="utf-8")
        _, fn = pool.tools["read_file"]
        result = fn(path="data.txt")
        assert "line1" in result
        assert "line2" in result

    def test_write_file(self, tmp_path):
        pool = _make_pool(tmp_path)
        _, fn = pool.tools["write_file"]
        result = fn(path="out.txt", content="hello world")
        assert "✅" in result
        assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "hello world"

    def test_call_tool_missing(self, tmp_path):
        pool = _make_pool(tmp_path)
        result = pool._call_tool("nonexistent_tool", {}, pool.tools)
        assert "找不到" in result


# ══════════════════════════════════════════════════════════════
# 7. 並行安全分類
# ══════════════════════════════════════════════════════════════

class TestParallelSafety:
    def test_read_tools_parallelizable(self, tmp_path):
        pool = _make_pool(tmp_path)
        assert pool._can_parallelize(["read_file", "list_files"])
        assert pool._can_parallelize(["grep_search", "find_files", "read_file"])

    def test_write_tools_not_parallelizable(self, tmp_path):
        pool = _make_pool(tmp_path)
        assert not pool._can_parallelize(["read_file", "execute_shell"])
        assert not pool._can_parallelize(["write_file", "read_file"])

    def test_remember_not_parallelizable(self, tmp_path):
        pool = _make_pool(tmp_path)
        assert not pool._can_parallelize(["remember", "read_file"])

    def test_single_tool_not_parallel(self, tmp_path):
        pool = _make_pool(tmp_path)
        assert not pool._can_parallelize(["read_file"])


# ══════════════════════════════════════════════════════════════
# 8. 原子寫入
# ══════════════════════════════════════════════════════════════

class TestAtomicWrite:
    def test_atomic_write_json(self, tmp_path):
        from agent import _atomic_write_json
        target = tmp_path / "test.json"
        data = {"key": "value", "中文": "測試"}
        _atomic_write_json(target, data)
        assert target.exists()
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded["key"] == "value"
        assert loaded["中文"] == "測試"

    def test_atomic_write_no_partial(self, tmp_path):
        from agent import _atomic_write_json
        target = tmp_path / "existing.json"
        target.write_text('{"old": true}', encoding="utf-8")
        _atomic_write_json(target, {"new": True})
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert "new" in loaded
        assert "old" not in loaded


# ══════════════════════════════════════════════════════════════
# 9. Skills 載入
# ══════════════════════════════════════════════════════════════

class TestSkills:
    def test_skills_loaded_when_dir_exists(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "python_style.md").write_text(
            "keywords: python, style, coding\n\n使用 Black 格式化。",
            encoding="utf-8",
        )
        pool = _make_pool(tmp_path)
        sid = (60, None)
        pool.conversations[sid] = [{"role": "user", "content": "python coding style"}]
        section = pool._load_skills_section(sid)
        assert "python_style" in section
        assert "Black" in section

    def test_no_skills_dir(self, tmp_path):
        pool = _make_pool(tmp_path)
        sid = (61, None)
        section = pool._load_skills_section(sid)
        assert section == ""
