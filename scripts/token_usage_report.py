#!/usr/bin/env python3
"""
Token Usage Report — 從 Claude Code 實際 JSONL session 記錄讀取真實 token 用量

主要數據源：~/.claude/projects/<project>/*.jsonl 中的 message.usage 欄位
（每個 assistant message 有真實的 input/output/cache tokens）

次要：git commits 分類（僅供參考，不作為 token 估算依據）

用法：
    python scripts/token_usage_report.py                  # 今日報告
    python scripts/token_usage_report.py --weekly         # 本週摘要
    python scripts/token_usage_report.py --date 2026-04-05
    python scripts/token_usage_report.py --week-start 2026-03-28
"""

import json
import subprocess
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

PROJECT_DIR_SLUG = "-Users-yhlai0911-Desktop-volpred-research"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects" / PROJECT_DIR_SLUG
STORAGE_DIR = Path(__file__).parent.parent / "storage" / "reports" / "token_usage"

# Anthropic pricing (Opus 4.x as of 2026-04，USD per million tokens)
PRICING = {
    "claude-opus-4-6": {
        "input": 15.00,
        "output": 75.00,
        "cache_write": 18.75,  # 1.25x input
        "cache_read": 1.50,    # 0.1x input
    },
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_write": 1.00,
        "cache_read": 0.08,
    },
}


def iter_session_usage(target_date_start=None, target_date_end=None):
    """
    遍歷所有 JSONL session files，yield (timestamp_date, session_id, model, usage_dict).

    target_date_start/end: datetime.date objects (inclusive start, exclusive end)
    """
    if not CLAUDE_PROJECTS_DIR.exists():
        return

    for jsonl_path in sorted(CLAUDE_PROJECTS_DIR.glob("*.jsonl")):
        session_id = jsonl_path.stem
        try:
            with open(jsonl_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if obj.get("type") != "assistant":
                        continue

                    msg = obj.get("message", {})
                    usage = msg.get("usage")
                    if not usage:
                        continue

                    ts_str = obj.get("timestamp")
                    if not ts_str:
                        continue

                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except ValueError:
                        continue

                    ts_date = ts.date()

                    if target_date_start and ts_date < target_date_start:
                        continue
                    if target_date_end and ts_date >= target_date_end:
                        continue

                    model = msg.get("model", "unknown")
                    yield (ts_date, session_id, model, usage)
        except IOError:
            continue


def aggregate_usage(date_start, date_end):
    """聚合指定日期區間的 token 用量"""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "assistant_messages": 0,
        "unique_sessions": set(),
    }
    by_model = defaultdict(lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "messages": 0,
    })
    by_date = defaultdict(lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "messages": 0,
    })

    for ts_date, session_id, model, usage in iter_session_usage(date_start, date_end):
        inp = usage.get("input_tokens", 0) or 0
        out = usage.get("output_tokens", 0) or 0
        cr = usage.get("cache_read_input_tokens", 0) or 0
        cc = usage.get("cache_creation_input_tokens", 0) or 0

        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["cache_read_tokens"] += cr
        totals["cache_create_tokens"] += cc
        totals["assistant_messages"] += 1
        totals["unique_sessions"].add(session_id)

        by_model[model]["input_tokens"] += inp
        by_model[model]["output_tokens"] += out
        by_model[model]["cache_read_tokens"] += cr
        by_model[model]["cache_create_tokens"] += cc
        by_model[model]["messages"] += 1

        date_key = ts_date.isoformat()
        by_date[date_key]["input_tokens"] += inp
        by_date[date_key]["output_tokens"] += out
        by_date[date_key]["cache_read_tokens"] += cr
        by_date[date_key]["cache_create_tokens"] += cc
        by_date[date_key]["messages"] += 1

    totals["unique_sessions"] = len(totals["unique_sessions"])

    return totals, dict(by_model), dict(by_date)


def compute_cost_usd(usage, model):
    """估算 USD 成本（基於 Anthropic pricing）"""
    if model not in PRICING:
        # Fallback: assume Opus pricing
        pricing = PRICING["claude-opus-4-6"]
    else:
        pricing = PRICING[model]

    return (
        usage["input_tokens"] / 1_000_000 * pricing["input"]
        + usage["output_tokens"] / 1_000_000 * pricing["output"]
        + usage["cache_create_tokens"] / 1_000_000 * pricing["cache_write"]
        + usage["cache_read_tokens"] / 1_000_000 * pricing["cache_read"]
    )


def get_friday_week_range(target_date=None):
    """計算包含 target_date 的週五-週五區間"""
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()
    weekday = target_date.weekday()  # Monday=0, Friday=4
    days_since_friday = (weekday - 4) % 7
    week_start = target_date - timedelta(days=days_since_friday)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def get_git_commits(since, until):
    """補充：取得該時段的 git commits（僅供 context，不用於估算）"""
    cmd = [
        "git", "log", "--oneline", "--format=%h %ai %s",
        f"--since={since.isoformat()}T00:00:00",
        f"--until={until.isoformat()}T00:00:00",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=Path(__file__).parent.parent,
    )
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    commits = []
    for line in lines:
        parts = line.split(" ", 3)
        if len(parts) >= 4:
            sha = parts[0]
            rest = " ".join(parts[1:])
            m = re.match(r"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} [+-]\d{4} (.+)", rest)
            if m:
                commits.append({"sha": sha, "date": m.group(1), "message": m.group(2)})
    return commits


def generate_daily_report(target_date=None, include_commits=False):
    """產出單日報告（基於真實 JSONL usage）"""
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    date_start = target_date
    date_end = target_date + timedelta(days=1)

    totals, by_model, by_date = aggregate_usage(date_start, date_end)

    # 計算各模型成本
    cost_by_model = {}
    total_cost_usd = 0.0
    for model, usage in by_model.items():
        cost = compute_cost_usd(usage, model)
        cost_by_model[model] = cost
        total_cost_usd += cost

    week_start, week_end = get_friday_week_range(target_date)

    report = {
        "report_type": "daily",
        "source": "claude_code_jsonl",
        "date": target_date.isoformat(),
        "week_range": f"{week_start.isoformat()} → {week_end.isoformat()}",
        "totals": {
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "cache_read_tokens": totals["cache_read_tokens"],
            "cache_create_tokens": totals["cache_create_tokens"],
            "billable_total": (
                totals["input_tokens"]
                + totals["output_tokens"]
                + totals["cache_create_tokens"]
            ),
            "assistant_messages": totals["assistant_messages"],
            "unique_sessions": totals["unique_sessions"],
            "estimated_cost_usd": round(total_cost_usd, 4),
        },
        "by_model": {
            model: {
                **usage,
                "estimated_cost_usd": round(cost_by_model[model], 4),
            }
            for model, usage in by_model.items()
        },
    }

    if include_commits:
        commits = get_git_commits(date_start, date_end)
        report["git_commits_context"] = [
            {"sha": c["sha"], "message": c["message"][:80]} for c in commits
        ]

    return report


def generate_weekly_report(week_start=None):
    """產出週報（週五到週五，基於真實 JSONL usage）"""
    if week_start is None:
        today = datetime.now(timezone.utc).date()
        week_start, _ = get_friday_week_range(today)

    week_end = week_start + timedelta(days=7)
    totals, by_model, by_date = aggregate_usage(week_start, week_end)

    cost_by_model = {}
    total_cost_usd = 0.0
    for model, usage in by_model.items():
        cost = compute_cost_usd(usage, model)
        cost_by_model[model] = cost
        total_cost_usd += cost

    # Per-day breakdown with cost
    daily_breakdown = {}
    for date_key, usage in sorted(by_date.items()):
        # Approximate per-day cost (can't split by model here, use aggregate)
        # More accurate: re-aggregate by date and model. For simplicity, we estimate proportionally.
        day_total = usage["input_tokens"] + usage["output_tokens"] + usage["cache_create_tokens"]
        total_billable = totals["input_tokens"] + totals["output_tokens"] + totals["cache_create_tokens"]
        day_cost = total_cost_usd * (day_total / total_billable) if total_billable else 0
        daily_breakdown[date_key] = {
            **usage,
            "billable_total": day_total,
            "estimated_cost_usd": round(day_cost, 4),
        }

    report = {
        "report_type": "weekly",
        "source": "claude_code_jsonl",
        "week_range": f"{week_start.isoformat()} → {week_end.isoformat()}",
        "totals": {
            "input_tokens": totals["input_tokens"],
            "output_tokens": totals["output_tokens"],
            "cache_read_tokens": totals["cache_read_tokens"],
            "cache_create_tokens": totals["cache_create_tokens"],
            "billable_total": (
                totals["input_tokens"]
                + totals["output_tokens"]
                + totals["cache_create_tokens"]
            ),
            "assistant_messages": totals["assistant_messages"],
            "unique_sessions": totals["unique_sessions"],
            "estimated_cost_usd": round(total_cost_usd, 4),
        },
        "by_model": {
            model: {
                **usage,
                "estimated_cost_usd": round(cost_by_model[model], 4),
            }
            for model, usage in by_model.items()
        },
        "daily_breakdown": daily_breakdown,
    }

    return report


def format_number(n):
    """Format with thousands separator"""
    return f"{n:,}"


def format_report_text(report):
    """格式化為 Markdown 文字"""
    lines = []
    t = report["totals"]

    if report["report_type"] == "daily":
        lines.append(f"# Token 用量日報 — {report['date']}（Claude Code 真實記錄）")
        lines.append(f"**週期**: {report['week_range']}")
    else:
        lines.append(f"# Token 用量週報（Claude Code 真實記錄）")
        lines.append(f"**週期**: {report['week_range']}")

    lines.append(f"**數據源**: {report['source']}")
    lines.append(f"**Assistant messages**: {t['assistant_messages']:,}")
    lines.append(f"**Sessions**: {t['unique_sessions']}")
    lines.append("")

    # Totals table
    lines.append("## Token 分布")
    lines.append("| 類型 | Tokens | 說明 |")
    lines.append("|------|--------|------|")
    lines.append(f"| Input | {t['input_tokens']:,} | 非快取輸入 |")
    lines.append(f"| Output | {t['output_tokens']:,} | Claude 產生的內容 |")
    lines.append(f"| Cache Read | {t['cache_read_tokens']:,} | 重複讀取（便宜）|")
    lines.append(f"| Cache Create | {t['cache_create_tokens']:,} | 首次寫入快取 |")
    lines.append(f"| **Billable** | **{t['billable_total']:,}** | input + output + cache_create |")
    lines.append(f"| **成本估算** | **${t['estimated_cost_usd']}** | 基於 Anthropic pricing |")
    lines.append("")

    # By model
    if report["by_model"]:
        lines.append("## 按模型分布")
        lines.append("| 模型 | Messages | Input | Output | Cache Read | Cost USD |")
        lines.append("|------|----------|-------|--------|-----------|----------|")
        for model, u in sorted(report["by_model"].items(), key=lambda x: -x[1]["messages"]):
            lines.append(
                f"| {model} | {u['messages']:,} | "
                f"{u['input_tokens']:,} | {u['output_tokens']:,} | "
                f"{u['cache_read_tokens']:,} | ${u['estimated_cost_usd']} |"
            )
        lines.append("")

    # Weekly: daily breakdown
    if report["report_type"] == "weekly" and "daily_breakdown" in report:
        lines.append("## 每日分布")
        lines.append("| 日期 | Messages | Billable Tokens | 成本 USD |")
        lines.append("|------|----------|-----------------|----------|")
        for date_key, d in report["daily_breakdown"].items():
            lines.append(
                f"| {date_key} | {d['messages']:,} | "
                f"{d['billable_total']:,} | ${d['estimated_cost_usd']} |"
            )
        lines.append("")

    # Git commits context (optional)
    if "git_commits_context" in report and report["git_commits_context"]:
        lines.append("## Git Commits（僅供參考）")
        for c in report["git_commits_context"][:20]:
            lines.append(f"- `{c['sha']}` {c['message']}")

    return "\n".join(lines)


def save_report(report, text):
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    if report["report_type"] == "daily":
        filename = f"daily_{report['date']}.json"
        text_filename = f"daily_{report['date']}.md"
    else:
        week_start = report["week_range"].split(" → ")[0]
        filename = f"weekly_{week_start}.json"
        text_filename = f"weekly_{week_start}.md"

    json_path = STORAGE_DIR / filename
    text_path = STORAGE_DIR / text_filename

    with open(json_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(text_path, "w") as f:
        f.write(text)

    return json_path, text_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Token Usage Report (Real from JSONL)")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--weekly", action="store_true", help="產出週報")
    parser.add_argument("--week-start", help="週報起始日 (YYYY-MM-DD)")
    parser.add_argument("--detailed", action="store_true", help="包含 git commits context")
    parser.add_argument("--no-save", action="store_true", help="不儲存檔案")
    parser.add_argument("--json", action="store_true", help="JSON 輸出")
    args = parser.parse_args()

    if args.weekly or args.week_start:
        week_start = None
        if args.week_start:
            week_start = datetime.strptime(args.week_start, "%Y-%m-%d").date()
        report = generate_weekly_report(week_start)
    else:
        target_date = None
        if args.date:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        report = generate_daily_report(target_date, include_commits=args.detailed)

    text = format_report_text(report)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(text)

    if not args.no_save:
        json_path, text_path = save_report(report, text)
        print(f"\n---\n📁 Saved: {json_path.name}, {text_path.name}")


if __name__ == "__main__":
    main()
