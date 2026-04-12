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

def _detect_claude_projects_dir() -> Path:
    """動態偵測正確的 Claude Code projects 目錄（跨 Mac/Linux 環境）"""
    base = Path.home() / ".claude" / "projects"
    if not base.exists():
        return base / "-Users-yhlai0911-Desktop-volpred-research"
    # 先試舊的 Mac slug
    mac_slug = base / "-Users-yhlai0911-Desktop-volpred-research"
    if mac_slug.exists():
        return mac_slug
    # 動態搜尋含有 volpred 的 slug
    for candidate in sorted(base.iterdir()):
        if "volpred" in candidate.name.lower() or "user" in candidate.name.lower():
            return candidate
    # fallback: 取最近修改的目錄（最可能是當前 project）
    dirs = [d for d in base.iterdir() if d.is_dir()]
    if dirs:
        return max(dirs, key=lambda d: d.stat().st_mtime)
    return mac_slug

PROJECT_DIR_SLUG = "-Users-yhlai0911-Desktop-volpred-research"
CLAUDE_PROJECTS_DIR = _detect_claude_projects_dir()
STORAGE_DIR = Path(__file__).parent.parent / "storage" / "reports" / "token_usage"

# Task categories with emoji + description
CATEGORY_META = {
    "experiment": ("🔬", "研究實驗（Agent 派送 K\\d+ / experiments/ 編輯）"),
    "paper_work": ("📝", "論文撰寫/審查（paper/ *.tex 編輯）"),
    "article_writing": ("✍️", "文章撰寫/發佈（publish-milestone / mile_*）"),
    "knowledge_recording": ("📚", "知識記錄（knowledge.json / thinking_journal）"),
    "research_planning": ("📋", "研究計劃（research_program.md / CLAUDE.md）"),
    "chart_generation": ("📊", "圖表生成（matplotlib / upload_chart）"),
    "script_dev": ("💻", "腳本開發（scripts/ *.py）"),
    "worktree_merge": ("🔀", "Worktree 合併與分支管理"),
    "member_qa": ("❓", "會員問答研究"),
    "platform_ops": ("🛡️", "平台運維（Supabase sync / daily_update）"),
    "skill_invoke": ("⚡", "Skill 呼叫"),
    "skill_edit": ("🔧", "Skill 編輯"),
    "git_sync": ("🔄", "Git commit / pull / push"),
    "knowledge_index": ("📇", "知識索引更新"),
    "token_report": ("📈", "Token 用量報告"),
    "web_research": ("🌐", "WebSearch / WebFetch"),
    "investigation": ("🔍", "閱讀 / 搜尋檔案"),
    "task_management": ("📌", "任務管理（TaskCreate/Update）"),
    "scheduling": ("⏰", "Cron / Monitor 排程"),
    "tool_setup": ("🛠️", "ToolSearch 載入工具"),
    "bash_other": ("💭", "其他 Bash 操作"),
    "file_edit": ("📄", "其他檔案編輯"),
    "agent_delegation": ("🤖", "Agent 派送（非實驗）"),
    "text_only": ("💬", "純文字回覆（無工具）"),
    "other": ("❔", "其他"),
}


def classify_message(content):
    """從 assistant message 的 content 分類此 message 在做的任務"""
    if not isinstance(content, list):
        return "text_only"

    categories = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "tool_use":
            continue
        name = item.get("name", "")
        inp = item.get("input", {}) if isinstance(item.get("input"), dict) else {}

        if name == "Agent":
            prompt = str(inp.get("prompt", ""))
            if re.search(r"\bK\d{3,4}\b", prompt):
                categories.append("experiment")
            else:
                categories.append("agent_delegation")

        elif name in ("Edit", "Write"):
            path = str(inp.get("file_path", ""))
            if "paper/" in path and path.endswith((".tex", ".bib")):
                categories.append("paper_work")
            elif "experiments/" in path:
                categories.append("experiment")
            elif "knowledge.json" in path or "thinking_journal" in path or "experiment_experiences" in path:
                categories.append("knowledge_recording")
            elif "research_program.md" in path or "CLAUDE.md" in path:
                categories.append("research_planning")
            elif ".claude/skills" in path:
                categories.append("skill_edit")
            elif "scripts/" in path:
                categories.append("script_dev")
            elif "next_tasks.json" in path:
                categories.append("task_management")
            elif "/memory/" in path and path.endswith(".md"):
                categories.append("knowledge_recording")
            elif "storage/reports/mile_" in path or "feed.json" in path:
                categories.append("article_writing")
            else:
                categories.append("file_edit")

        elif name == "Bash":
            cmd = str(inp.get("command", ""))
            if "publish-milestone" in cmd or "release-pool" in cmd and "release-pool" not in cmd:
                categories.append("article_writing")
            elif "publish-milestone" in cmd:
                categories.append("article_writing")
            elif "git commit" in cmd or "git push" in cmd or "git pull" in cmd:
                categories.append("git_sync")
            elif "git add" in cmd:
                categories.append("git_sync")
            elif "merge_worktree" in cmd or "git worktree" in cmd or "git branch" in cmd or "git merge" in cmd:
                categories.append("worktree_merge")
            elif "supabase_sync" in cmd or "daily_update" in cmd:
                categories.append("platform_ops")
            elif "release-pool" in cmd:
                categories.append("platform_ops")
            elif "build_knowledge_index" in cmd:
                categories.append("knowledge_index")
            elif "question-" in cmd:
                categories.append("member_qa")
            elif "token_usage_report" in cmd:
                categories.append("token_report")
            elif "matplotlib" in cmd or "upload_chart" in cmd or "generate_bar_chart" in cmd or "savefig" in cmd:
                categories.append("chart_generation")
            elif cmd.startswith("grep") or cmd.startswith("rg ") or cmd.startswith("ls ") or cmd.startswith("wc ") or "find " in cmd[:20]:
                categories.append("investigation")
            else:
                categories.append("bash_other")

        elif name in ("Read", "Grep", "Glob"):
            categories.append("investigation")

        elif name in ("CronCreate", "CronDelete", "CronList", "Monitor", "ScheduleWakeup"):
            categories.append("scheduling")

        elif name in ("TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "TaskStop"):
            categories.append("task_management")

        elif name == "Skill":
            categories.append("skill_invoke")

        elif name in ("WebSearch", "WebFetch"):
            categories.append("web_research")

        elif name == "RemoteTrigger":
            categories.append("scheduling")

        elif name == "ToolSearch":
            categories.append("tool_setup")

    if not categories:
        return "text_only"

    # Priority: heaviest work first
    priority = [
        "experiment", "paper_work", "article_writing", "knowledge_recording",
        "research_planning", "script_dev", "chart_generation", "worktree_merge",
        "skill_edit", "member_qa", "platform_ops", "skill_invoke", "git_sync",
        "knowledge_index", "token_report", "web_research",
        "investigation", "task_management", "scheduling", "tool_setup",
        "bash_other", "file_edit", "agent_delegation",
    ]
    for p in priority:
        if p in categories:
            return p
    return categories[0]


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


def _scan_jsonl(jsonl_path, session_id, is_subagent, target_date_start, target_date_end):
    """Scan a single JSONL file and yield usage entries"""
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
                category = classify_message(msg.get("content", []))
                # Subagents: mark as delegated work but keep category for what they do
                if is_subagent and category == "text_only":
                    category = "agent_delegation"
                yield (ts_date, session_id, model, usage, category, is_subagent)
    except IOError:
        return


def iter_session_usage(target_date_start=None, target_date_end=None):
    """
    遍歷所有 JSONL session files（主 session + subagents），
    yield (timestamp_date, session_id, model, usage_dict, category, is_subagent).
    """
    if not CLAUDE_PROJECTS_DIR.exists():
        return

    # Main session files
    for jsonl_path in sorted(CLAUDE_PROJECTS_DIR.glob("*.jsonl")):
        yield from _scan_jsonl(
            jsonl_path, jsonl_path.stem, False,
            target_date_start, target_date_end,
        )

    # Subagent JSONL files (in <session>/subagents/*.jsonl)
    for sub_path in sorted(CLAUDE_PROJECTS_DIR.glob("*/subagents/*.jsonl")):
        # session_id is the parent dir of subagents/
        session_id = sub_path.parent.parent.name + "/" + sub_path.stem
        yield from _scan_jsonl(
            sub_path, session_id, True,
            target_date_start, target_date_end,
        )


def aggregate_usage(date_start, date_end):
    """聚合指定日期區間的 token 用量"""
    def empty_bucket():
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cache_create_tokens": 0,
            "messages": 0,
        }

    totals = {**empty_bucket(), "unique_sessions": set(), "subagent_messages": 0, "main_messages": 0}
    by_model = defaultdict(empty_bucket)
    by_date = defaultdict(empty_bucket)
    by_category = defaultdict(empty_bucket)

    for ts_date, session_id, model, usage, category, is_subagent in iter_session_usage(date_start, date_end):
        inp = usage.get("input_tokens", 0) or 0
        out = usage.get("output_tokens", 0) or 0
        cr = usage.get("cache_read_input_tokens", 0) or 0
        cc = usage.get("cache_creation_input_tokens", 0) or 0

        for bucket in (totals, by_model[model], by_date[ts_date.isoformat()], by_category[category]):
            bucket["input_tokens"] += inp
            bucket["output_tokens"] += out
            bucket["cache_read_tokens"] += cr
            bucket["cache_create_tokens"] += cc
            bucket["messages"] += 1

        totals["unique_sessions"].add(session_id)
        if is_subagent:
            totals["subagent_messages"] += 1
        else:
            totals["main_messages"] += 1

    totals["unique_sessions"] = len(totals["unique_sessions"])

    return totals, dict(by_model), dict(by_date), dict(by_category)


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

    totals, by_model, by_date, by_category = aggregate_usage(date_start, date_end)

    # 計算各模型成本
    cost_by_model = {}
    total_cost_usd = 0.0
    for model, usage in by_model.items():
        cost = compute_cost_usd(usage, model)
        cost_by_model[model] = cost
        total_cost_usd += cost

    # 各類別成本（按消息比例分配到 Opus，因為幾乎全是 Opus）
    cost_by_category = {}
    for cat, usage in by_category.items():
        # Use the dominant model's pricing
        dominant_model = max(by_model.keys(), key=lambda m: by_model[m]["messages"]) if by_model else "claude-opus-4-6"
        cost_by_category[cat] = compute_cost_usd(usage, dominant_model)

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
            "assistant_messages": totals["messages"],
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
        "by_category": {
            cat: {
                **usage,
                "billable_total": usage["input_tokens"] + usage["output_tokens"] + usage["cache_create_tokens"],
                "estimated_cost_usd": round(cost_by_category[cat], 4),
                "emoji": CATEGORY_META.get(cat, ("❔", cat))[0],
                "description": CATEGORY_META.get(cat, ("❔", cat))[1],
            }
            for cat, usage in sorted(by_category.items(), key=lambda x: -cost_by_category.get(x[0], 0))
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
    totals, by_model, by_date, by_category = aggregate_usage(week_start, week_end)

    cost_by_model = {}
    total_cost_usd = 0.0
    for model, usage in by_model.items():
        cost = compute_cost_usd(usage, model)
        cost_by_model[model] = cost
        total_cost_usd += cost

    # 各類別成本
    cost_by_category = {}
    for cat, usage in by_category.items():
        dominant_model = max(by_model.keys(), key=lambda m: by_model[m]["messages"]) if by_model else "claude-opus-4-6"
        cost_by_category[cat] = compute_cost_usd(usage, dominant_model)

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
            "assistant_messages": totals["messages"],
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
        "by_category": {
            cat: {
                **usage,
                "billable_total": usage["input_tokens"] + usage["output_tokens"] + usage["cache_create_tokens"],
                "estimated_cost_usd": round(cost_by_category[cat], 4),
                "emoji": CATEGORY_META.get(cat, ("❔", cat))[0],
                "description": CATEGORY_META.get(cat, ("❔", cat))[1],
            }
            for cat, usage in sorted(by_category.items(), key=lambda x: -cost_by_category.get(x[0], 0))
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
    lines.append(f"**Assistant messages**: {t.get('assistant_messages', t.get('messages', 0)):,}")
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

    # By task category
    if report.get("by_category"):
        lines.append("## 按任務類別分布（依成本排序）")
        lines.append("| 類別 | Messages | Billable | Cost USD | 佔比 |")
        lines.append("|------|----------|----------|----------|------|")
        total_cost = t.get("estimated_cost_usd", 0) or 0.0001
        for cat, u in report["by_category"].items():
            pct = u["estimated_cost_usd"] / total_cost * 100 if total_cost else 0
            bar = "█" * max(1, int(pct / 5))
            lines.append(
                f"| {u['emoji']} {u['description']} | {u['messages']:,} | "
                f"{u['billable_total']:,} | ${u['estimated_cost_usd']} | {pct:.1f}% {bar} |"
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
