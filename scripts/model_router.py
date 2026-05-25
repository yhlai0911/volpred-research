#!/usr/bin/env python3
"""Model selection router by task_type.

Canonical mapping per CLAUDE.md / .claude/rules/agent-delegation.md model
selection table. Use BEFORE spawning a sub-agent or invoking `claude -p`
so the right tier handles the right task.

CLI:
  uv run python scripts/model_router.py --task-type experiment
  uv run python scripts/model_router.py --task-type lookup
  uv run python scripts/model_router.py --list

Output (--task-type): JSON with {model, effort, cli_flag, agent_short}.
Library import:
  from model_router import pick_model
  m = pick_model("experiment")  # → ("opus", "high")
"""
from __future__ import annotations

import argparse
import json
import sys

# ─── Canonical mapping ─────────────────────────────────────────────────────
# Per CLAUDE.md table + .claude/rules/agent-delegation.md
# Format: task_type → (model_short, reasoning_effort)
#   model_short: "opus" | "sonnet" | "haiku"
#   effort:       "low" | "medium" | "high"

TASK_TYPE_TO_MODEL: dict[str, tuple[str, str]] = {
    # Research & 高風險判斷 — opus
    "experiment":         ("opus",   "high"),    # K-experiment 設計 / 結果判讀
    "paper_decision":     ("opus",   "high"),    # narrative state machine / pivot
    "paper_body":         ("opus",   "medium"),  # .tex rewrite (主線程才能跑)
    "strategy_lifecycle": ("opus",   "high"),    # 策略上架 gate

    # 寫作 / 程序型 — sonnet medium
    "paper_review":       ("sonnet", "medium"),  # latex-academic-reviewer + citation-verifier
    "event_article":      ("sonnet", "medium"),  # 事件驅動文章 (時效但結構化)
    "daily_article":      ("sonnet", "medium"),  # 日常文章 (feed-publisher 流程)
    "trending_repost":    ("sonnet", "medium"),  # 熱門改寫 (style enforcement)
    "member_qa":          ("sonnet", "medium"),  # 會員問題答覆
    "email_reply":        ("sonnet", "medium"),  # 用戶回信處理

    # Ops / 驗證 / governance — sonnet low (短流程 + checklist 為主)
    "platform_ops":       ("sonnet", "low"),     # bug fix / refactor / cron 修整
    "governance":         ("sonnet", "low"),     # rules/skills/docs 修整

    # Lookup / classification — haiku low (參考型，便宜快速)
    "lookup":             ("haiku",  "low"),
    "verify":             ("haiku",  "low"),
    "classification":     ("haiku",  "low"),
}

# Map to CLI flag (`claude -p --model <X>`)
MODEL_TO_CLI_FLAG: dict[str, str] = {
    "opus":   "claude-opus-4-7",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
}

DEFAULT = ("sonnet", "medium")  # fallback for unknown task_type


def pick_model(task_type: str | None) -> tuple[str, str]:
    """Library entry — return (model_short, effort) for given task_type."""
    if not task_type:
        return DEFAULT
    return TASK_TYPE_TO_MODEL.get(task_type, DEFAULT)


def cli_flag(model_short: str) -> str:
    """Map short name → exact --model flag for `claude -p`."""
    return MODEL_TO_CLI_FLAG.get(model_short, MODEL_TO_CLI_FLAG["sonnet"])


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task-type", help="Task type to route")
    g.add_argument("--list", action="store_true", help="Show full mapping table")
    args = ap.parse_args()

    if args.list:
        rows = sorted(TASK_TYPE_TO_MODEL.items(), key=lambda kv: (kv[1][0], kv[0]))
        print(f"{'task_type':<22} {'model':<8} {'effort':<8} {'cli_flag':<32}")
        print("─" * 72)
        for t, (m, e) in rows:
            print(f"{t:<22} {m:<8} {e:<8} {cli_flag(m):<32}")
        print(f"\nfallback (unknown): {DEFAULT[0]} / {DEFAULT[1]}")
        return 0

    model, effort = pick_model(args.task_type)
    out = {
        "task_type": args.task_type,
        "model": model,
        "effort": effort,
        "cli_flag": cli_flag(model),
        "agent_short": model,
        "fallback": args.task_type not in TASK_TYPE_TO_MODEL,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
