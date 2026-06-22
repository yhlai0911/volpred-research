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
    "daily_digest":       ("sonnet", "medium"),  # 每日精選導讀 (reader-facing article flow)
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
    "opus":   "claude-opus-4-8",
    "sonnet": "claude-sonnet-4-6",
    "haiku":  "claude-haiku-4-5-20251001",
}

DEFAULT = ("sonnet", "medium")  # fallback for unknown task_type

# ─────────────────────────────────────────────────────────────────────────
# Effort/model escalation ladder (2026-05-29 boss directive)
# ─────────────────────────────────────────────────────────────────────────
# "問題沒辦法解決就持續調高 effort" — but with a HARD CEILING (opus/high) and
# a strategy-switch handoff once exhausted (→ 3-strike rule: decompose / add
# context / second-opinion / human-escalate, NOT infinite retry).
#
# Monotonic cost-ordered ladder. On a verifiable failure (test fail / verdict
# FAIL / exception / non-convergence / reviewer reject), the dispatcher
# re-dispatches at the NEXT rung above the task's current position.
ESCALATION_LADDER: list[tuple[str, str]] = [
    ("haiku",  "low"),
    ("haiku",  "medium"),
    ("sonnet", "low"),
    ("sonnet", "medium"),
    ("sonnet", "high"),
    ("opus",   "medium"),
    ("opus",   "high"),     # ← CEILING. Beyond this: switch strategy, don't retry.
]
CEILING = ("opus", "high")


def pick_model(task_type: str | None) -> tuple[str, str]:
    """Library entry — return (model_short, effort) for given task_type."""
    if not task_type:
        return DEFAULT
    return TASK_TYPE_TO_MODEL.get(task_type, DEFAULT)


def _ladder_index(model: str, effort: str) -> int:
    """Position of (model, effort) on the ladder; -1 if off-ladder."""
    try:
        return ESCALATION_LADDER.index((model, effort))
    except ValueError:
        return -1


def pick_model_escalated(task_type: str | None, attempt: int = 0) -> dict:
    """Return model+effort escalated `attempt` rungs above the task's base tier.

    attempt=0 → task's normal (model, effort) from TASK_TYPE_TO_MODEL.
    attempt=N → N rungs higher on ESCALATION_LADDER, capped at CEILING.

    Used by the dispatch retry loop: on a verifiable failure, re-dispatch with
    attempt+1 so a harder problem gets a stronger model/effort. Returns:
      {model, effort, attempt, at_ceiling, exhausted}
    - at_ceiling: this dispatch IS at opus/high (max reasoning available)
    - exhausted: caller requested escalation BEYOND ceiling → must switch
      strategy per 3-strike rule (decompose / +context / Codex 2nd-opinion /
      escalate to human), NOT keep retrying same approach.
    """
    base_model, base_effort = pick_model(task_type)
    base_idx = _ladder_index(base_model, base_effort)
    if base_idx < 0:
        # Off-ladder base (shouldn't happen) → start from sonnet/medium rung
        base_idx = _ladder_index("sonnet", "medium")

    target_idx = base_idx + max(0, attempt)
    exhausted = target_idx > (len(ESCALATION_LADDER) - 1)
    target_idx = min(target_idx, len(ESCALATION_LADDER) - 1)
    model, effort = ESCALATION_LADDER[target_idx]
    return {
        "task_type": task_type,
        "model": model,
        "effort": effort,
        "cli_flag": cli_flag(model),
        "agent_short": model,
        "attempt": attempt,
        "at_ceiling": (model, effort) == CEILING,
        "exhausted": exhausted,
    }


def cli_flag(model_short: str) -> str:
    """Map short name → exact --model flag for `claude -p`."""
    return MODEL_TO_CLI_FLAG.get(model_short, MODEL_TO_CLI_FLAG["sonnet"])


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task-type", help="Task type to route")
    g.add_argument("--list", action="store_true", help="Show full mapping table")
    ap.add_argument(
        "--attempt", type=int, default=0,
        help="Escalation attempt (0=base tier; N=N rungs higher on ladder, capped at opus/high). "
             "Use in dispatch retry loop: bump on each verifiable failure.",
    )
    args = ap.parse_args()

    if args.list:
        rows = sorted(TASK_TYPE_TO_MODEL.items(), key=lambda kv: (kv[1][0], kv[0]))
        print(f"{'task_type':<22} {'model':<8} {'effort':<8} {'cli_flag':<32}")
        print("─" * 72)
        for t, (m, e) in rows:
            print(f"{t:<22} {m:<8} {e:<8} {cli_flag(m):<32}")
        print(f"\nfallback (unknown): {DEFAULT[0]} / {DEFAULT[1]}")
        print(f"\nescalation ladder: {' → '.join(f'{m}/{e}' for m, e in ESCALATION_LADDER)}")
        return 0

    if args.attempt > 0:
        out = pick_model_escalated(args.task_type, args.attempt)
        out["fallback"] = args.task_type not in TASK_TYPE_TO_MODEL
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    model, effort = pick_model(args.task_type)
    out = {
        "task_type": args.task_type,
        "model": model,
        "effort": effort,
        "cli_flag": cli_flag(model),
        "agent_short": model,
        "attempt": 0,
        "at_ceiling": (model, effort) == CEILING,
        "exhausted": False,
        "fallback": args.task_type not in TASK_TYPE_TO_MODEL,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
