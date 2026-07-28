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
  m = pick_model("experiment")  # → ("opus", "xhigh")
"""
from __future__ import annotations

import argparse
import json
import sys

# ─── Canonical mapping ─────────────────────────────────────────────────────
# Per CLAUDE.md table + .claude/rules/agent-delegation.md
# Format: task_type → (model_short, reasoning_effort)
#   model_short: "opus" | "sonnet" | "haiku"
#   effort:       "low" | "medium" | "high" | "xhigh" | "max"  (max = ceiling)

# 2026-07-05 owner directive: ALL subagents use opus; the 2026-07-28
# generation upgrade makes every active Opus route Opus 5 (native 1M).
# 2026-07-01 sonnet<->opus two-way pick. Model is now uniformly `opus`; only
# `effort` still varies by task difficulty (orthogonal to model — a trivial
# lookup on opus/low is cheaper than opus/max, no need to burn max reasoning
# on a checklist). haiku/sonnet remain valid aliases in the roster but are OFF
# the default subagent rotation.
#
# 2026-07-05 (later, owner correction): the reasoning-effort scale is FIVE
# tiers, matching the `claude --effort` CLI flag exactly:
#     low < medium < high < xhigh < max
# Earlier this file capped at "high" — WRONG (high is only rung 3/5). CEILING is
# now opus/max. Research (experiment/paper_decision/strategy_lifecycle) starts at
# xhigh and escalates to max. NOTE: effort is applied via `--effort` on the
# spawned `claude -p` (wired 2026-07-05 into dispatch_supervisor/worker.py); the
# CLI fail-opens on unknown values (warns + uses default), so it is safe.
TASK_TYPE_TO_MODEL: dict[str, tuple[str, str]] = {
    # Research & 高風險判斷 — opus / xhigh (研究：xhigh 起，失敗升 max)
    "experiment":         ("opus", "xhigh"),   # K-experiment 設計 / 結果判讀
    "paper_decision":     ("opus", "xhigh"),   # narrative state machine / pivot
    "paper_body":         ("opus", "high"),    # .tex rewrite (主線程才能跑; 升 medium→high)
    "strategy_lifecycle": ("opus", "xhigh"),   # 策略上架 gate

    # 寫作 / 程序型 — opus / medium
    "paper_review":       ("opus", "medium"),  # latex-academic-reviewer + citation-verifier
    "code_review":        ("opus", "medium"),  # source/result review；預設走 Codex primary path
    "event_article":      ("opus", "medium"),  # 事件驅動文章 (時效但結構化)
    "daily_article":      ("opus", "medium"),  # 日常文章 (feed-publisher 流程)
    "daily_digest":       ("opus", "medium"),  # 每日精選導讀 (reader-facing article flow)
    "trending_repost":    ("opus", "medium"),  # 熱門改寫 (style enforcement)
    "member_qa":          ("opus", "medium"),  # 會員問題答覆
    "email_reply":        ("opus", "medium"),  # 用戶回信處理
    "telegram_reply":     ("opus", "medium"),  # Telegram 即時 owner-message responder

    # Ops / 驗證 / governance — opus / low (短流程 + checklist，effort 低即可)
    "platform_ops":       ("opus", "low"),     # bug fix / refactor / cron 修整
    "governance":         ("opus", "low"),     # rules/skills/docs 修整

    # Lookup / classification — opus / low (參考型，effort 低但仍用 opus)
    "lookup":             ("opus", "low"),
    "verify":             ("opus", "low"),
    "classification":     ("opus", "low"),
}

# ─────────────────────────────────────────────────────────────────────────
# Topology routing (2026-07-10 topology-audit：先選協作方式，再選模型)
# ─────────────────────────────────────────────────────────────────────────
# 拓撲此前散在 prose（task-routing.md / workflow-index.md 執行模式欄 / 各 skill 內），
# 由每班 orchestrator 臨場判斷。這裡機械化 task_type → 預設拓撲；task 自帶合法
# `topology` 欄位時以欄位為準（per-task override）。orchestrator 只在欄位/預設
# 明顯不合時 override，且必須在 work_log 記 override 原因（讓 override 成為可觀測
# 例外而非常態）。
# NOTE: compute_queue 不是 per-type 預設 — 任何類型的 heavy compute 子步驟
# （GARCH MLE / bootstrap / 全期 backtest / pooled-MLE multistart）都應 enqueue
# compute_queue（見 cron_hourly_dispatch_prompt.md step 5 分流決策），與本表並行。

TOPOLOGIES = ("inline", "subagent", "worktree", "codex_exec", "compute_queue", "agent_team")

TASK_TYPE_TO_TOPOLOGY: dict[str, str] = {
    "experiment":         "worktree",   # 隔離產出 experiments/kXXX/；merge_worktree.sh 收
    "paper_review":       "subagent",   # 並行 reviewer（serialize per paper）
    "code_review":        "codex_exec", # Codex primary-path review；重活可 override 到 compute_queue
    "paper_body":         "inline",     # 主線程 only（CLAUDE.md hard rule：禁 agent 寫 .tex）
    "paper_decision":     "inline",     # 主線程 only + narrative state machine
    "strategy_lifecycle": "inline",     # 固定 gate pipeline（evaluate → review → sensitivity → MDD）
    "daily_article":      "subagent",   # writer subagent（隔離 draft 檔，主線程串行 publish）
    "daily_digest":       "subagent",
    "event_article":      "inline",     # 即時性需主線程判斷；直接 published
    "member_qa":          "inline",
    "trending_repost":    "inline",
    "email_reply":        "inline",     # PHASE 0 orchestrator 自做（跨 tick mini-orchestrator）
    "telegram_reply":     "inline",     # dedicated Telegram responder；不進一般 subagent lane
    "platform_ops":       "subagent",   # Claude/Codex claim 制
    "governance":         "subagent",
    "lookup":             "inline",
    "verify":             "inline",
    "classification":     "inline",
}
DEFAULT_TOPOLOGY = "subagent"  # 未知型別：交給一般 bounded subagent（保守，不佔主線程）


def pick_topology(task_type: str | None, task: dict | None = None) -> dict:
    """Return {"topology": str, "source": "task_field"|"type_default"|"fallback"}.

    優先序：task 自帶合法 `topology` 欄位 > task_type 預設表 > DEFAULT_TOPOLOGY。
    非法欄位值 fail-open 落回 type default 並標 invalid_field（不 raise —
    派工路徑不可因 metadata 打錯字炸掉；invalid 值可被 report 消費者看見）。
    """
    field = (task or {}).get("topology")
    if isinstance(field, str) and field.strip().lower() in TOPOLOGIES:
        return {"topology": field.strip().lower(), "source": "task_field"}
    out: dict = {}
    if field is not None:
        out["invalid_field"] = str(field)
    if task_type in TASK_TYPE_TO_TOPOLOGY:
        out.update({"topology": TASK_TYPE_TO_TOPOLOGY[task_type], "source": "type_default"})
    else:
        out.update({"topology": DEFAULT_TOPOLOGY, "source": "fallback"})
    return out


# Map to CLI flag (`claude -p --model <X>`)
MODEL_TO_CLI_FLAG: dict[str, str] = {
    "opus":   "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku":  "claude-haiku-4-5-20251001",
}

DEFAULT = ("opus", "medium")  # fallback for unknown task_type (2026-07-05: all-opus)

# ─────────────────────────────────────────────────────────────────────────
# Effort/model escalation ladder (2026-05-29 boss directive)
# ─────────────────────────────────────────────────────────────────────────
# "問題沒辦法解決就持續調高 effort" — but with a HARD CEILING (opus/max) and
# a strategy-switch handoff once exhausted (→ 3-strike rule: decompose / add
# context / second-opinion / human-escalate, NOT infinite retry).
#
# Monotonic cost-ordered ladder. On a verifiable failure (test fail / verdict
# FAIL / exception / non-convergence / reviewer reject), the dispatcher
# re-dispatches at the NEXT rung above the task's current position.
# 2026-07-05 (all-opus + full 5-tier scale): base tiers are opus, escalation is
# opus-effort-only across the FULL `claude --effort` scale
# (low → medium → high → xhigh → max). A verifiable failure re-dispatches at the
# next rung; the previous 3-rung ladder wrongly stopped at high.
ESCALATION_LADDER: list[tuple[str, str]] = [
    ("opus", "low"),
    ("opus", "medium"),
    ("opus", "high"),
    ("opus", "xhigh"),
    ("opus", "max"),      # ← CEILING. Beyond this: switch strategy, don't retry.
]
CEILING = ("opus", "max")


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
    - at_ceiling: this dispatch IS at opus/max (highest reasoning available)
    - exhausted: caller requested escalation BEYOND ceiling → must switch
      strategy per 3-strike rule (decompose / +context / Codex 2nd-opinion /
      escalate to human), NOT keep retrying same approach.
    """
    base_model, base_effort = pick_model(task_type)
    base_idx = _ladder_index(base_model, base_effort)
    if base_idx < 0:
        # Off-ladder base (shouldn't happen) → start from opus/medium rung
        base_idx = _ladder_index("opus", "medium")

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
        help="Escalation attempt (0=base tier; N=N rungs higher on ladder, capped at opus/max). "
             "Use in dispatch retry loop: bump on each verifiable failure.",
    )
    args = ap.parse_args()

    if args.list:
        rows = sorted(TASK_TYPE_TO_MODEL.items(), key=lambda kv: (kv[1][0], kv[0]))
        print(f"{'task_type':<22} {'model':<8} {'effort':<8} {'topology':<12} {'cli_flag':<32}")
        print("─" * 84)
        for t, (m, e) in rows:
            topo = TASK_TYPE_TO_TOPOLOGY.get(t, DEFAULT_TOPOLOGY)
            print(f"{t:<22} {m:<8} {e:<8} {topo:<12} {cli_flag(m):<32}")
        print(f"\nfallback (unknown): {DEFAULT[0]} / {DEFAULT[1]} / topology={DEFAULT_TOPOLOGY}")
        print(f"\nescalation ladder: {' → '.join(f'{m}/{e}' for m, e in ESCALATION_LADDER)}")
        return 0

    if args.attempt > 0:
        out = pick_model_escalated(args.task_type, args.attempt)
        out["fallback"] = args.task_type not in TASK_TYPE_TO_MODEL
        topo = pick_topology(args.task_type)
        out["topology"] = topo["topology"]
        out["topology_source"] = topo["source"]
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0

    model, effort = pick_model(args.task_type)
    topo = pick_topology(args.task_type)
    out = {
        "task_type": args.task_type,
        "model": model,
        "effort": effort,
        "topology": topo["topology"],
        "topology_source": topo["source"],
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
