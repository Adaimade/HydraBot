#!/usr/bin/env python3
"""
HydraBot — 學習回路模組

提供三項能力：
  1. 結構化長期記憶（experience_log.json）
  2. 失敗回放機制（失敗自動記錄 + 下次注入 prompt）
  3. TF-IDF 相似度檢索（純 stdlib，可選 numpy 加速）

資料檔：
  {data_prefix}experience_log.json  — 所有經驗條目
"""

from __future__ import annotations

import json
import math
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ─────────────────────────────────────────────────────────────
# 常數
# ─────────────────────────────────────────────────────────────

ENTRY_TYPES = ("success", "failure", "insight")

# 在回應中偵測失敗的關鍵字（用於自動記錄）
_FAILURE_PATTERNS = re.compile(
    r"(❌|執行錯誤|找不到|失敗|無法|error|traceback|exception)",
    re.IGNORECASE,
)

# system prompt 中最多注入幾條相關經驗
TOP_K = 3

# 每條注入摘要的最大字元數
SUMMARY_MAX = 200


# ─────────────────────────────────────────────────────────────
# TF-IDF 向量化（無外部依賴，可選 numpy 加速）
# ─────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """斷詞：中文字符切單字，其餘以空白/標點分隔。"""
    tokens: list[str] = []
    buf = ""
    for ch in text.lower():
        if "\u4e00" <= ch <= "\u9fff":
            if buf.strip():
                tokens.extend(buf.split())
            buf = ""
            tokens.append(ch)
        elif ch.isalnum() or ch in "_-":
            buf += ch
        else:
            if buf.strip():
                tokens.extend(buf.split())
            buf = ""
    if buf.strip():
        tokens.extend(buf.split())
    return [t for t in tokens if t]


def _tf(tokens: list[str]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    total = max(len(tokens), 1)
    return {t: c / total for t, c in counts.items()}


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.0
    dot = sum(a[k] * b[k] for k in keys)
    mag_a = math.sqrt(sum(v * v for v in a.values()))
    mag_b = math.sqrt(sum(v * v for v in b.values()))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ─────────────────────────────────────────────────────────────
# ExperienceEntry
# ─────────────────────────────────────────────────────────────

class ExperienceEntry:
    """單一經驗條目。"""

    __slots__ = (
        "entry_id", "timestamp", "entry_type",
        "context", "task", "outcome", "correction",
        "tags", "rating",
    )

    def __init__(
        self,
        entry_type: str,
        context: str,
        task: str,
        outcome: str,
        correction: str = "",
        tags: list[str] | None = None,
        rating: int = 0,
        entry_id: str | None = None,
        timestamp: str | None = None,
    ):
        self.entry_id   = entry_id or f"exp_{uuid.uuid4().hex[:8]}"
        self.timestamp  = timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.entry_type = entry_type if entry_type in ENTRY_TYPES else "insight"
        self.context    = context[:1000]
        self.task       = task[:500]
        self.outcome    = outcome[:800]
        self.correction = correction[:500]
        self.tags       = tags or []
        self.rating     = max(-1, min(1, int(rating)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id":   self.entry_id,
            "timestamp":  self.timestamp,
            "type":       self.entry_type,
            "context":    self.context,
            "task":       self.task,
            "outcome":    self.outcome,
            "correction": self.correction,
            "tags":       self.tags,
            "rating":     self.rating,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExperienceEntry":
        return cls(
            entry_type = d.get("type", "insight"),
            context    = d.get("context", ""),
            task       = d.get("task", ""),
            outcome    = d.get("outcome", ""),
            correction = d.get("correction", ""),
            tags       = d.get("tags", []),
            rating     = d.get("rating", 0),
            entry_id   = d.get("entry_id"),
            timestamp  = d.get("timestamp"),
        )

    @property
    def search_text(self) -> str:
        """供 TF-IDF 索引的合併文字。"""
        return " ".join([self.context, self.task, self.outcome, " ".join(self.tags)])

    def short_summary(self) -> str:
        parts = [f"[{self.entry_type}] {self.task}"]
        if self.outcome:
            parts.append(f"→ {self.outcome}")
        if self.correction:
            parts.append(f"修正: {self.correction}")
        return " | ".join(parts)[:SUMMARY_MAX]


# ─────────────────────────────────────────────────────────────
# ExperienceLog
# ─────────────────────────────────────────────────────────────

class ExperienceLog:
    """
    結構化長期記憶庫。

    儲存格式：{data_prefix}experience_log.json
    每條記錄：ExperienceEntry
    檢索方式：TF-IDF 餘弦相似度（無需外部套件）
    """

    def __init__(self, log_path: Path | str | None = None):
        self._path    = Path(log_path) if log_path else Path("experience_log.json")
        self._lock    = threading.Lock()
        self._entries: list[ExperienceEntry] = []
        self._load()

    # ─────────────────────────────────────────────
    # 持久化
    # ─────────────────────────────────────────────

    def _load(self):
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            with self._lock:
                self._entries = [ExperienceEntry.from_dict(d) for d in data]
        except Exception as exc:
            print(f"⚠️  ExperienceLog 載入失敗: {exc}")

    def _save(self):
        try:
            import tempfile as _tf
            import os as _os
            with self._lock:
                data = [e.to_dict() for e in self._entries]
            text = json.dumps(data, indent=2, ensure_ascii=False)
            fd, tmp = _tf.mkstemp(
                dir=str(self._path.parent), suffix=".tmp"
            )
            try:
                with _os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
                Path(tmp).replace(self._path)
            except Exception:
                try:
                    Path(tmp).unlink(missing_ok=True)
                except Exception:
                    pass
                raise
        except Exception as exc:
            print(f"⚠️  ExperienceLog 儲存失敗: {exc}")

    # ─────────────────────────────────────────────
    # 寫入
    # ─────────────────────────────────────────────

    def add(
        self,
        entry_type: str,
        context: str,
        task: str,
        outcome: str,
        correction: str = "",
        tags: list[str] | None = None,
        rating: int = 0,
    ) -> str:
        """新增一筆經驗，回傳 entry_id。"""
        entry = ExperienceEntry(
            entry_type = entry_type,
            context    = context,
            task       = task,
            outcome    = outcome,
            correction = correction,
            tags       = tags or [],
            rating     = rating,
        )
        with self._lock:
            self._entries.append(entry)
        self._save()
        return entry.entry_id

    def record_failure(
        self,
        user_message: str,
        bot_response: str,
        correction: str = "",
    ) -> str:
        """快捷方式：記錄一筆失敗。"""
        return self.add(
            entry_type = "failure",
            context    = user_message[:500],
            task       = user_message[:200],
            outcome    = bot_response[:500],
            correction = correction or "（待補充修正策略）",
            tags       = ["auto-detected"],
            rating     = -1,
        )

    def update_rating(self, entry_id: str, rating: int) -> bool:
        """更新某條記錄的評分（-1 差、0 普通、1 好）。"""
        with self._lock:
            for e in self._entries:
                if e.entry_id == entry_id:
                    e.rating = max(-1, min(1, int(rating)))
                    self._save()
                    return True
        return False

    # ─────────────────────────────────────────────
    # TF-IDF 檢索
    # ─────────────────────────────────────────────

    def recall(self, query: str, top_k: int = TOP_K) -> list[ExperienceEntry]:
        """
        回傳與 query 最相關的 top_k 筆記錄。
        評分差（rating == -1）的失敗記錄也納入（有助於「避免重犯」）。
        """
        with self._lock:
            entries = list(self._entries)

        if not entries:
            return []

        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        q_tf = _tf(q_tokens)

        scored: list[tuple[float, ExperienceEntry]] = []
        for entry in entries:
            e_tf  = _tf(_tokenize(entry.search_text))
            score = _cosine(q_tf, e_tf)
            # 給「好的解法」輕微加分，給「負評差解」也留著但不加分
            score += entry.rating * 0.05
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k] if _ > 0.01]

    def format_for_prompt(self, query: str, top_k: int = TOP_K) -> str:
        """
        回傳可直接插入 system prompt 的相關經驗摘要字串。
        若無相關記錄則回傳空字串。
        """
        hits = self.recall(query, top_k=top_k)
        if not hits:
            return ""

        lines = ["## 相關過往經驗（請參考，避免重複錯誤）"]
        for i, entry in enumerate(hits, 1):
            icon = {"success": "✅", "failure": "⚠️", "insight": "💡"}.get(
                entry.entry_type, "📝"
            )
            lines.append(f"{i}. {icon} {entry.short_summary()}")

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # 查詢
    # ─────────────────────────────────────────────

    def list_recent(self, n: int = 10) -> list[ExperienceEntry]:
        with self._lock:
            return list(reversed(self._entries[-n:]))

    def count(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {"total": len(self._entries)}
            for e in self._entries:
                counts[e.entry_type] = counts.get(e.entry_type, 0) + 1
        return counts

    def format_list(self, n: int = 10) -> str:
        entries = self.list_recent(n)
        if not entries:
            return "📚 經驗庫為空"
        stats = self.count()
        lines = [
            f"📚 **經驗庫** — 共 {stats['total']} 條"
            f"（成功 {stats.get('success', 0)} / "
            f"失敗 {stats.get('failure', 0)} / "
            f"洞見 {stats.get('insight', 0)}）\n"
        ]
        for entry in entries:
            icon = {"success": "✅", "failure": "⚠️", "insight": "💡"}.get(
                entry.entry_type, "📝"
            )
            lines.append(
                f"{icon} `{entry.entry_id}`  {entry.timestamp[:10]}\n"
                f"   任務: {entry.task[:80]}\n"
                f"   結果: {entry.outcome[:80]}"
                + (f"\n   修正: {entry.correction[:80]}" if entry.correction and entry.correction != "（待補充修正策略）" else "")
            )
        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# 失敗自動偵測
# ─────────────────────────────────────────────────────────────

def is_likely_failure(response: str) -> bool:
    """粗略判斷回應是否包含錯誤/失敗訊號。"""
    return bool(_FAILURE_PATTERNS.search(response))
