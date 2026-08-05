#!/usr/bin/env python3
"""per-agent / per-model token 消耗分解（資源監控部 owned tool）。

為什麼不是直接讀 `storage/reports/token_usage/daily_*.json`：
那些日報只有 by_model / by_provider / by_category 三個維度，**沒有 agent 維度**
（誰花的：主線程？哪個 worktree 的 K 實驗？哪個 dispatch slot？Codex？）。
本工具重用 `scripts/token_usage_report.py` 的 telemetry 讀取與計價原語（不重寫
token 會計），只多加一個 agent 歸屬維度：Claude session JSONL 所在的 project
目錄就是 agent 身分。

同時把「重算的每日真值」與「已落檔的日報」對照，偵測日報 pipeline 失真。

用法：
    uv run python storage/org/departments/resource_monitor/tools/token_breakdown.py --days 7 [--end 2026-08-04] [--top 15] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# storage/org/departments/resource_monitor/tools/<this> → parents[5] is the repo root
REPO_ROOT = Path(__file__).resolve().parents[5]
DEPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from token_usage_report import (  # noqa: E402
    DISPATCH_WORKDIR_ROOT,
    MISSION_OUTPUT_CATEGORIES,
    PRICING,
    _billable_total,
    _claude_project_slug,
    _deduplicated_turns,
    _iter_codex_session_records,
    _primary_category,
    _scan_jsonl,
    _usage_breakdown,
    compute_cost_usd,
    discover_claude_project_dirs,
)

STORED_DAILY_DIR = REPO_ROOT / "storage" / "reports" / "token_usage"


# --- agent 歸屬 -----------------------------------------------------------
# Claude Code 以 CWD 決定 project 目錄，所以目錄名唯一決定「這個 session 是誰」：
# 主 checkout = 主線程；.claude/worktrees/<slug> = 該 worktree 的實驗 agent；
# dispatch scratch = Operations Core worker。這是唯一不必猜的 agent 訊號。

def _agent_identity(project_dir_name: str, is_subagent: bool) -> tuple[str, str]:
    """回傳 (agent_class, agent_id)。"""
    main_name = _claude_project_slug(REPO_ROOT)
    worktree_prefix = _claude_project_slug(REPO_ROOT / ".claude" / "worktrees") + "-"
    dispatch_prefix = _claude_project_slug(DISPATCH_WORKDIR_ROOT) + "-"

    if project_dir_name == main_name:
        base_class, agent_id = "main_thread", "main_thread"
    elif project_dir_name.startswith(worktree_prefix):
        slug = project_dir_name[len(worktree_prefix):]
        base_class, agent_id = "worktree_agent", f"worktree:{slug}"
    elif project_dir_name.startswith(dispatch_prefix):
        slug = project_dir_name[len(dispatch_prefix):]
        base_class, agent_id = "dispatch_worker", f"dispatch:{slug}"
    else:
        # discover_claude_project_dirs 的 allowlist 是結構性的，出現第三種前綴
        # 代表 allowlist 或 runtime 佈局變了 — 記名而非靜默歸零。
        base_class, agent_id = "unclassified", f"unclassified:{project_dir_name}"

    if is_subagent:
        return f"{base_class}_subagent", agent_id + "/subagent"
    return base_class, agent_id


def iter_attributed_turns(date_start: date, date_end: date):
    """產出帶 agent 歸屬的 turn（已按 msg_id 去重，與官方日報同口徑）。"""
    seen_record_ids: set[str] = set()

    for project_dir in discover_claude_project_dirs():
        sources = [(p, False) for p in sorted(project_dir.glob("*.jsonl"))]
        sources += [(p, True) for p in sorted(project_dir.glob("*/subagents/*.jsonl"))]
        for jsonl_path, is_subagent in sources:
            session_id = jsonl_path.stem
            if is_subagent:
                session_id = jsonl_path.parent.parent.name + "/" + jsonl_path.stem
            agent_class, agent_id = _agent_identity(project_dir.name, is_subagent)

            records = []
            for record in _scan_jsonl(
                jsonl_path, session_id, is_subagent, date_start, date_end
            ):
                rid = record.get("record_id")
                if isinstance(rid, str) and rid:
                    if rid in seen_record_ids:
                        continue
                    seen_record_ids.add(rid)
                records.append(record)
            for turn in _deduplicated_turns(records):
                turn["agent_class"] = agent_class
                turn["agent_id"] = agent_id
                yield turn

    for record in _iter_codex_session_records(date_start, date_end):
        yield {
            "usage": record["usage"],
            "model": record["model"],
            "date": record["date"],
            "provider": "codex",
            "session_id": record["session_id"],
            "is_subagent": False,
            "categories": [record["category"]],
            "agent_class": "codex_worker",
            "agent_id": record["session_id"],
        }


def _blank():
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "messages": 0,
        "sessions": set(),
        "cost_usd": 0.0,
        "cost_priced_billable": 0,
        "mission_billable": 0,
    }


def _finalize(bucket: dict) -> dict:
    billable = _billable_total(bucket)
    out = {k: v for k, v in bucket.items() if k != "sessions"}
    out["sessions"] = len(bucket["sessions"])
    out["billable_total"] = billable
    out["cost_usd"] = round(bucket["cost_usd"], 4)
    # 價目表只涵蓋 Claude 模型；Codex/gpt-* 無公開對照 → 誠實標示覆蓋率，
    # 不用 0 冒充「免費」。
    out["cost_coverage_pct"] = (
        round(100 * bucket["cost_priced_billable"] / billable, 1) if billable else 0.0
    )
    out["mission_output_share_pct"] = (
        round(100 * bucket["mission_billable"] / billable, 1) if billable else 0.0
    )
    return out


def analyze(date_start: date, date_end: date, top: int) -> dict:
    dims = {
        "by_agent_class": defaultdict(_blank),
        "by_agent_id": defaultdict(_blank),
        "by_model": defaultdict(_blank),
        "by_provider": defaultdict(_blank),
        "by_category": defaultdict(_blank),
        "by_date": defaultdict(_blank),
    }
    cross = defaultdict(_blank)          # agent_class × model
    agent_models = defaultdict(lambda: defaultdict(int))
    totals = _blank()
    turns = 0

    for turn in iter_attributed_turns(date_start, date_end):
        usage = _usage_breakdown(turn["usage"])
        billable = _billable_total(usage)
        model = turn["model"]
        category = _primary_category(turn["categories"], turn.get("is_subagent", False))
        cost = compute_cost_usd(usage, model)
        mission = billable if category in MISSION_OUTPUT_CATEGORIES else 0
        turns += 1

        keys = {
            "by_agent_class": turn["agent_class"],
            "by_agent_id": turn["agent_id"],
            "by_model": model,
            "by_provider": turn["provider"],
            "by_category": category,
            "by_date": turn["date"].isoformat(),
        }
        targets = [dims[d][k] for d, k in keys.items()]
        targets.append(cross[f"{turn['agent_class']} | {model}"])
        targets.append(totals)
        for bucket in targets:
            for field, value in usage.items():
                bucket[field] += value
            bucket["messages"] += 1
            bucket["sessions"].add(turn["session_id"])
            bucket["mission_billable"] += mission
            if cost is not None:
                bucket["cost_usd"] += cost
                bucket["cost_priced_billable"] += billable
        agent_models[turn["agent_id"]][model] += billable

    def rank(mapping, limit=None):
        rows = sorted(
            ((k, _finalize(v)) for k, v in mapping.items()),
            key=lambda kv: -kv[1]["billable_total"],
        )
        if limit:
            rows = rows[:limit]
        return {k: v for k, v in rows}

    by_date = rank(dims["by_date"])
    daily_values = [v["billable_total"] for v in by_date.values()]
    mean_daily = sum(daily_values) / len(daily_values) if daily_values else 0.0

    anomalies = []
    for day, row in sorted(by_date.items()):
        if mean_daily > 0 and row["billable_total"] > 2 * mean_daily:
            anomalies.append({
                "kind": "daily_spike",
                "date": day,
                "billable_total": row["billable_total"],
                "window_mean": round(mean_daily, 1),
                "ratio_vs_mean": round(row["billable_total"] / mean_daily, 2),
            })

    # 落檔日報 vs 重算真值：日報 pipeline 是否誠實反映用量。
    stored_drift = []
    cursor = date_start
    while cursor < date_end:
        key = cursor.isoformat()
        recomputed = by_date.get(key, {}).get("billable_total", 0)
        path = STORED_DAILY_DIR / f"daily_{key}.json"
        if path.exists():
            with path.open(encoding="utf-8") as fh:
                stored = json.load(fh)["totals"]["billable_total"]
        else:
            stored = None
        stored_drift.append({
            "date": key,
            "stored_daily_billable": stored,
            "recomputed_billable": recomputed,
            "stored_report_exists": path.exists(),
            "understated_by": (recomputed - stored) if stored is not None else None,
        })
        cursor += timedelta(days=1)

    return {
        "report_type": "per_agent_per_model_token_breakdown",
        "version": 1,
        "produced_by": "resource_monitor",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start_utc_date": date_start.isoformat(),
            "end_utc_date_exclusive": date_end.isoformat(),
            "days": (date_end - date_start).days,
            "boundary": "UTC calendar day (matches token_usage_report.py)",
        },
        "source": {
            "telemetry": "claude_code_and_codex_jsonl via scripts/token_usage_report.py",
            "agent_attribution": "Claude project directory (repo root / .claude/worktrees / dispatch scratch) + subagent path",
            "dedupe": "message.id per turn (same as official daily report)",
            "priced_models": sorted(PRICING),
        },
        "totals": _finalize(totals) | {"turns": turns},
        "by_date": by_date,
        "by_agent_class": rank(dims["by_agent_class"]),
        "by_agent_id_top": rank(dims["by_agent_id"], top),
        "by_model": rank(dims["by_model"]),
        "by_provider": rank(dims["by_provider"]),
        "by_category": rank(dims["by_category"], top),
        "agent_class_x_model": rank(cross, top),
        "agent_id_model_mix_top": {
            agent: dict(sorted(models.items(), key=lambda kv: -kv[1]))
            for agent, models in sorted(
                agent_models.items(), key=lambda kv: -sum(kv[1].values())
            )[:top]
        },
        "anomalies": anomalies,
        "stored_daily_drift": stored_drift,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--end", default=None, help="last INCLUDED UTC date (default: yesterday UTC)")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.end:
        end_inclusive = date.fromisoformat(args.end)
    else:
        end_inclusive = datetime.now(timezone.utc).date() - timedelta(days=1)
    date_end = end_inclusive + timedelta(days=1)
    date_start = date_end - timedelta(days=args.days)

    report = analyze(date_start, date_end, args.top)
    out = args.out or (
        DEPT_DIR / "memory" / f"token_breakdown_{end_inclusive.isoformat()}_{args.days}d.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved: {out}")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
