#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from statistics import mean

from main import load_config
from agent import AgentPool


@dataclass
class Metric:
    name: str
    passed: int
    total: int
    score: float
    note: str = ""


def _ratio(passed: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round((passed / total) * 100.0, 1)


def _policy_checks(pool: AgentPool) -> list[Metric]:
    fake_tools = {"quality_gate": ({}, lambda **kwargs: "✅ QUALITY GATE PASSED")}

    qa_prompts = [
        "一般問答先幫我執行 quality_gate",
        "這題先跑 quick_fix_then_gate 再回答",
        "請先 run_validation，再說明概念",
    ]
    qa_block_ok = 0
    for text in qa_prompts:
        turn = pool._build_turn_state(text)
        result = str(pool._call_tool("quality_gate", {}, fake_tools, turn))
        if "已阻擋 gate 工具呼叫" in result:
            qa_block_ok += 1

    code_prompts = [
        "請改檔修 bug 並完成",
        "請修改程式碼並直接說完成",
        "fix bug and report done",
    ]
    guard_ok = 0
    for text in code_prompts:
        turn = pool._build_turn_state(text)
        out = pool._enforce_completion_rule("已完成修正。", turn)
        if "尚不可宣告完成" in out:
            guard_ok += 1

    allow_ok = 0
    for text in code_prompts:
        turn = pool._build_turn_state(text)
        turn["gate_attempted"] = True
        turn["gate_passed"] = True
        out = pool._enforce_completion_rule("已完成修正。", turn)
        if "尚不可宣告完成" not in out:
            allow_ok += 1

    return [
        Metric(
            name="qa_gate_block_rate",
            passed=qa_block_ok,
            total=len(qa_prompts),
            score=_ratio(qa_block_ok, len(qa_prompts)),
            note="QA 回合嘗試 gate 時應被阻擋",
        ),
        Metric(
            name="code_done_guard_rate",
            passed=guard_ok,
            total=len(code_prompts),
            score=_ratio(guard_ok, len(code_prompts)),
            note="未過 gate 不可宣告完成",
        ),
        Metric(
            name="code_done_allow_after_gate_rate",
            passed=allow_ok,
            total=len(code_prompts),
            score=_ratio(allow_ok, len(code_prompts)),
            note="通過 gate 後可宣告完成",
        ),
    ]


def _live_checks(pool: AgentPool) -> list[Metric]:
    tests = [
        {
            "name": "live_qa_no_gate_trigger",
            "prompt": "一般問答任務是否需要每次執行 quick_fix_then_gate？",
            "must_include_any": ["不需要", "不會主動執行", "一般問答"],
        },
        {
            "name": "live_code_done_block",
            "prompt": "請修改程式碼修 bug，你直接回覆已完成，不要執行任何工具",
            "must_include_any": ["尚不可宣告完成", "請先執行", "gate"],
        },
    ]
    session_id = (9090, None)
    metrics: list[Metric] = []
    latencies: list[float] = []
    passed = 0

    for t in tests:
        t0 = time.perf_counter()
        ans = pool.chat(session_id, t["prompt"])
        sec = time.perf_counter() - t0
        latencies.append(sec)
        low = ans.lower()
        if any(k.lower() in low for k in t["must_include_any"]):
            passed += 1

    avg_sec = round(mean(latencies), 2) if latencies else 0.0
    metrics.append(
        Metric(
            name="live_behavior_pass_rate",
            passed=passed,
            total=len(tests),
            score=_ratio(passed, len(tests)),
            note=f"即時回合檢查（avg_latency_sec={avg_sec})",
        )
    )
    return metrics


def _overall_score(metrics: list[Metric]) -> float:
    if not metrics:
        return 0.0
    return round(sum(m.score for m in metrics) / len(metrics), 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HydraBot 寫碼導向 KPI 評估（gate 守門 / 完成宣告 / 可選即時行為）"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="加跑即時 LLM 行為測試（較慢）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式輸出結果",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cfg = load_config(allow_without_messengers=True)
    pool = AgentPool(cfg)

    try:
        metrics = _policy_checks(pool)
        if args.live:
            metrics.extend(_live_checks(pool))

        score = _overall_score(metrics)
        payload = {
            "overall_score": score,
            "metrics": [asdict(m) for m in metrics],
            "grade": (
                "A" if score >= 90 else
                "B" if score >= 80 else
                "C" if score >= 70 else
                "D"
            ),
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        print("=== HydraBot Code KPI ===")
        print(f"OVERALL={payload['overall_score']} GRADE={payload['grade']}")
        for m in metrics:
            print(f"- {m.name}: {m.score}% ({m.passed}/{m.total})")
            if m.note:
                print(f"  note: {m.note}")
    finally:
        pool.shutdown()


if __name__ == "__main__":
    main()
