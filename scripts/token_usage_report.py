#!/usr/bin/env python3
"""
Token Usage Report — 基於 git 活動的 Claude token 用量分析

分析 git commits 按類別估算 token 消耗，產出每日/每週報告。
週期：週五到週五（對齊帳單週期）。

用法：
    python scripts/token_usage_report.py                  # 今日報告
    python scripts/token_usage_report.py --weekly          # 本週摘要
    python scripts/token_usage_report.py --date 2026-04-05 # 指定日期
    python scripts/token_usage_report.py --week-start 2026-03-28  # 指定週起點
"""

import subprocess
import re
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict, Counter

STORAGE_DIR = Path(__file__).parent.parent / "storage" / "reports" / "token_usage"

# ── 分類規則 ────────────────────────────────────────────────
# 每個 category: (patterns, estimated_token_weight, description)
# weight 是相對值，1.0 = 普通 commit，越高表示越吃 token
CATEGORIES = {
    "paper_review": {
        "patterns": [
            r"Paper \d.*R\d",
            r"Paper \d.*SEVERE",
            r"Paper \d.*HIGH",
            r"Paper \d.*CRITICAL",
            r"Paper \d.*complete",
            r"Paper \d.*fix",
            r"Paper \d.*audit",
            r"Paper \d.*citation",
            r"AUDIT_PLAN",
            r"paper.*review",
            r"paper.*R\d",
            r"reproduce\.py",
            r"Recompile.*paper",
        ],
        "weight": 8.0,
        "emoji": "📝",
        "description": "論文審查/修訂（讀寫完整 LaTeX，多輪 review）",
    },
    "experiment": {
        "patterns": [
            r"^[a-f0-9]+ K\d{3,4}[a-z]?:",
            r"^[a-f0-9]+ K\d{3,4}[a-z]? ",
            r"experiment",
            r"E\d{1,3}.*experience",
        ],
        "weight": 5.0,
        "emoji": "🔬",
        "description": "研究實驗（agent + Codex 審查 + 知識記錄）",
    },
    "article_writing": {
        "patterns": [
            r"article.*mile_",
            r"mile_[a-f0-9]+",
            r"general article",
            r"research article",
            r"publish.*article",
            r"write.*article",
            r"\d+ articles:",
            r"Article[s]?:",
        ],
        "weight": 4.0,
        "emoji": "✍️",
        "description": "文章撰寫與發佈",
    },
    "latex_content_fix": {
        "patterns": [
            r"LaTeX",
            r"KaTeX",
            r"Unicode.*minus",
            r"bare inline",
            r"math block",
            r"equation fix",
            r"JSON escaping",
            r"Restore.*article",
            r"Fix.*rendering",
            r"artifact",
            r"80789---",
        ],
        "weight": 7.0,
        "emoji": "🔧",
        "description": "LaTeX/內容批量修復（讀寫大型 JSON）",
    },
    "feed_ops": {
        "patterns": [
            r"release.*pool",
            r"feed.*sync",
            r"supabase.*sync",
            r"Supabase",
            r"content sync",
        ],
        "weight": 2.0,
        "emoji": "📡",
        "description": "Feed 發佈/同步操作",
    },
    "frontend_deploy": {
        "patterns": [
            r"frontend",
            r"deploy",
            r"Zeabur",
            r"Next\.js",
            r"component",
            r"admin",
        ],
        "weight": 4.0,
        "emoji": "🌐",
        "description": "前端開發/部署",
    },
    "ops_patrol": {
        "patterns": [
            r"Ops patrol",
            r"platform.*patrol",
            r"health check",
            r"ops.*report",
        ],
        "weight": 3.0,
        "emoji": "🛡️",
        "description": "平台巡檢",
    },
    "knowledge_index": {
        "patterns": [
            r"knowledge index",
            r"知識索引",
            r"build_knowledge_index",
        ],
        "weight": 2.0,
        "emoji": "📚",
        "description": "知識索引建立/更新",
    },
    "daily_update": {
        "patterns": [
            r"daily.update",
            r"daily.*策略",
            r"recalc.*metric",
            r"strategy.*weight",
        ],
        "weight": 1.5,
        "emoji": "📊",
        "description": "每日策略更新/績效重算",
    },
    "periodic_sync": {
        "patterns": [
            r"Periodic commit",
            r"storage state sync",
            r"session.*state",
        ],
        "weight": 0.5,
        "emoji": "🔄",
        "description": "定期狀態同步（低 token）",
    },
    "research_program": {
        "patterns": [
            r"research_program",
            r"CLAUDE\.md",
            r"skill.*update",
            r"error.log",
        ],
        "weight": 1.0,
        "emoji": "📋",
        "description": "研究計畫/規範更新",
    },
    "member_qa": {
        "patterns": [
            r"member.*Q&A",
            r"會員.*問",
            r"question.*rank",
            r"question.*answer",
        ],
        "weight": 3.0,
        "emoji": "❓",
        "description": "會員問答研究",
    },
    "codex_review": {
        "patterns": [
            r"[Cc]odex.*review",
            r"[Cc]odex.*flag",
            r"[Cc]odex.*audit",
            r"[Cc]odex.*FATAL",
            r"[Cc]odex.*bug",
            r"CODEX CRITICAL",
            r"REVERT.*Codex",
        ],
        "weight": 2.0,
        "emoji": "🤖",
        "description": "Codex 審查",
    },
    "paper_writing": {
        "patterns": [
            r"Paper.*writing",
            r"Paper.*audit.*plan",
            r"paper.*dirs",
            r"paper.*README",
            r"paper.*upload",
            r"PRG.*paper",
            r"FRL.*paper",
            r"citation.*verif",
            r"Add README.*paper",
            r"Organize paper",
            r"papers.*uploaded",
        ],
        "weight": 6.0,
        "emoji": "📄",
        "description": "論文撰寫/組織",
    },
    "skill_process": {
        "patterns": [
            r"[Ss]kill:",
            r"[Pp]reamble",
            r"process.*fix",
            r"PROCESS FIX",
            r"Ban agents",
            r"standard.*protocol",
            r"dispatch protocol",
            r"Academic prose",
        ],
        "weight": 1.5,
        "emoji": "⚙️",
        "description": "流程/技能規範更新",
    },
    "bugfix": {
        "patterns": [
            r"^[a-f0-9]+ Fix:",
            r"^[a-f0-9]+ Fix ",
            r"^[a-f0-9]+ REVERT",
            r"except:pass",
            r"silent.*error",
            r"Eliminate.*except",
            r"install.*pymupdf",
            r"broken images",
        ],
        "weight": 3.0,
        "emoji": "🐛",
        "description": "Bug 修復/程式碼改善",
    },
    "experience_log": {
        "patterns": [
            r"^[a-f0-9]+ E\d{1,3}:",
            r"experience.*lesson",
            r"session final",
        ],
        "weight": 1.0,
        "emoji": "📝",
        "description": "經驗記錄/Session 總結",
    },
}


def get_friday_week_range(target_date=None):
    """計算包含 target_date 的週五-週五區間"""
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()
    weekday = target_date.weekday()  # Monday=0, Friday=4
    # 找到本週或上一個週五
    days_since_friday = (weekday - 4) % 7
    week_start = target_date - timedelta(days=days_since_friday)
    week_end = week_start + timedelta(days=7)
    return week_start, week_end


def get_git_log(since, until, repo_dir=None):
    """取得 git log（one-line + date）"""
    cmd = [
        "git", "log", "--oneline", "--format=%h %ai %s",
        f"--since={since.isoformat()}",
        f"--until={until.isoformat()}",
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=repo_dir or Path(__file__).parent.parent,
    )
    lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
    commits = []
    for line in lines:
        parts = line.split(" ", 3)
        if len(parts) >= 4:
            sha = parts[0]
            date_str = parts[1]
            # parts[2] is time, parts[3] is tz + message
            rest = " ".join(parts[1:])
            # parse: 2026-04-06 12:34:56 +0800 commit message
            m = re.match(r"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} [+-]\d{4} (.+)", rest)
            if m:
                commits.append({
                    "sha": sha,
                    "date": m.group(1),
                    "message": m.group(2),
                })
    return commits


def classify_commit(message):
    """將 commit message 分類到最佳匹配的 category"""
    best_cat = None
    best_priority = -1

    # priority 越高越優先匹配
    priority_order = [
        "paper_review", "paper_writing", "latex_content_fix", "experiment",
        "article_writing", "codex_review", "member_qa", "bugfix",
        "frontend_deploy", "ops_patrol", "feed_ops", "skill_process",
        "daily_update", "knowledge_index", "research_program",
        "experience_log", "periodic_sync",
    ]

    for cat in priority_order:
        info = CATEGORIES[cat]
        for pattern in info["patterns"]:
            if re.search(pattern, message, re.IGNORECASE):
                return cat

    return "other"


def get_commit_file_stats(sha, repo_dir=None):
    """取得單一 commit 的檔案變更統計（用於更精確估算）"""
    cmd = ["git", "diff", "--shortstat", f"{sha}~1", sha]
    result = subprocess.run(
        cmd, capture_output=True, text=True,
        cwd=repo_dir or Path(__file__).parent.parent,
    )
    text = result.stdout.strip()
    insertions = 0
    deletions = 0
    m_ins = re.search(r"(\d+) insertion", text)
    m_del = re.search(r"(\d+) deletion", text)
    if m_ins:
        insertions = int(m_ins.group(1))
    if m_del:
        deletions = int(m_del.group(1))
    return insertions + deletions


def estimate_tokens(category, lines_changed, num_commits=1):
    """估算 token 消耗（相對單位，不是絕對值）

    邏輯：每個 commit = 一次 Claude 互動（prompt + response）
    - 基礎開銷：每個 commit 的 prompt/context 讀取（weight × 2000 per commit）
    - 變更行數：讀+寫+surrounding context（weight × lines × 4）
    - Weight 反映該類型工作的 context 密度（論文讀整篇 vs 改一行 status）
    """
    info = CATEGORIES.get(category, {"weight": 1.0})
    weight = info["weight"]
    base = weight * 2000 * num_commits  # per-commit overhead
    line_factor = int(weight * lines_changed * 4)  # context multiplier
    line_factor = min(line_factor, 500000)  # cap
    return int(base + line_factor)


def generate_daily_report(target_date=None, detailed=False):
    """產出單日報告"""
    if target_date is None:
        target_date = datetime.now(timezone.utc).date()

    since = target_date
    until = target_date + timedelta(days=1)
    commits = get_git_log(since, until)

    # 分類
    categorized = defaultdict(list)
    for c in commits:
        cat = classify_commit(c["message"])
        categorized[cat].append(c)

    # 計算 token 估算
    category_stats = {}
    total_estimated = 0

    for cat, cat_commits in categorized.items():
        total_lines = 0
        for c in cat_commits:
            lines = get_commit_file_stats(c["sha"])
            total_lines += lines

        tokens = estimate_tokens(cat, total_lines, num_commits=len(cat_commits))
        category_stats[cat] = {
            "commits": len(cat_commits),
            "lines_changed": total_lines,
            "estimated_tokens": tokens,
        }
        total_estimated += tokens

    # 排序
    sorted_cats = sorted(
        category_stats.items(),
        key=lambda x: x[1]["estimated_tokens"],
        reverse=True,
    )

    # 週區間
    week_start, week_end = get_friday_week_range(target_date)

    report = {
        "report_type": "daily",
        "date": target_date.isoformat(),
        "week_range": f"{week_start.isoformat()} → {week_end.isoformat()}",
        "total_commits": len(commits),
        "total_estimated_tokens": total_estimated,
        "categories": {},
    }

    for cat, stats in sorted_cats:
        info = CATEGORIES.get(cat, {"emoji": "❔", "description": "其他"})
        pct = stats["estimated_tokens"] / total_estimated * 100 if total_estimated > 0 else 0
        report["categories"][cat] = {
            "emoji": info.get("emoji", "❔"),
            "description": info.get("description", "其他"),
            "commits": stats["commits"],
            "lines_changed": stats["lines_changed"],
            "estimated_tokens": stats["estimated_tokens"],
            "percentage": round(pct, 1),
        }
        if detailed:
            report["categories"][cat]["commit_messages"] = [
                c["message"][:80] for c in categorized[cat]
            ]

    return report


def generate_weekly_report(week_start=None):
    """產出週報（週五到週五）"""
    if week_start is None:
        today = datetime.now(timezone.utc).date()
        week_start, _ = get_friday_week_range(today)

    week_end = week_start + timedelta(days=7)
    commits = get_git_log(week_start, week_end)

    # 按日分組
    daily_counts = Counter()
    for c in commits:
        daily_counts[c["date"]] += 1

    # 按類別分組 + 估算
    categorized = defaultdict(list)
    for c in commits:
        cat = classify_commit(c["message"])
        categorized[cat].append(c)

    category_stats = {}
    total_estimated = 0
    for cat, cat_commits in categorized.items():
        total_lines = 0
        for c in cat_commits:
            lines = get_commit_file_stats(c["sha"])
            total_lines += lines
        tokens = estimate_tokens(cat, total_lines, num_commits=len(cat_commits))
        category_stats[cat] = {
            "commits": len(cat_commits),
            "lines_changed": total_lines,
            "estimated_tokens": tokens,
        }
        total_estimated += tokens

    sorted_cats = sorted(
        category_stats.items(),
        key=lambda x: x[1]["estimated_tokens"],
        reverse=True,
    )

    # 每日 token 分布
    daily_data = {}
    for date_str in sorted(daily_counts.keys()):
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        day_commits = [c for c in commits if c["date"] == date_str]
        day_tokens = 0
        for c in day_commits:
            cat = classify_commit(c["message"])
            lines = get_commit_file_stats(c["sha"])
            day_tokens += estimate_tokens(cat, lines)
        daily_data[date_str] = {
            "commits": daily_counts[date_str],
            "estimated_tokens": day_tokens,
            "weekday": d.strftime("%A"),
        }

    report = {
        "report_type": "weekly",
        "week_range": f"{week_start.isoformat()} → {week_end.isoformat()}",
        "total_commits": len(commits),
        "total_estimated_tokens": total_estimated,
        "daily_breakdown": daily_data,
        "categories": {},
    }

    for cat, stats in sorted_cats:
        info = CATEGORIES.get(cat, {"emoji": "❔", "description": "其他"})
        pct = stats["estimated_tokens"] / total_estimated * 100 if total_estimated > 0 else 0
        report["categories"][cat] = {
            "emoji": info.get("emoji", "❔"),
            "description": info.get("description", "其他"),
            "commits": stats["commits"],
            "lines_changed": stats["lines_changed"],
            "estimated_tokens": stats["estimated_tokens"],
            "percentage": round(pct, 1),
        }

    return report


def format_report_text(report):
    """格式化報告為 Markdown 文字"""
    lines = []

    if report["report_type"] == "daily":
        lines.append(f"# Token 用量日報 — {report['date']}")
        lines.append(f"**週期**: {report['week_range']}")
    else:
        lines.append(f"# Token 用量週報")
        lines.append(f"**週期**: {report['week_range']}")

    lines.append(f"**總 commits**: {report['total_commits']}")
    lines.append(f"**估算總 token**: {report['total_estimated_tokens']:,}")
    lines.append("")

    # 週報的每日分布
    if report["report_type"] == "weekly" and "daily_breakdown" in report:
        lines.append("## 每日分布")
        lines.append("| 日期 | 星期 | Commits | 估算 Token | 佔比 |")
        lines.append("|------|------|---------|-----------|------|")
        total = report["total_estimated_tokens"] or 1
        for date_str, data in report["daily_breakdown"].items():
            pct = data["estimated_tokens"] / total * 100
            bar = "█" * max(1, int(pct / 5))
            lines.append(
                f"| {date_str} | {data['weekday'][:3]} | {data['commits']} | "
                f"{data['estimated_tokens']:,} | {pct:.1f}% {bar} |"
            )
        lines.append("")

    # 類別分布
    lines.append("## 類別分布")
    lines.append("| 類別 | Commits | 行數變更 | 估算 Token | 佔比 |")
    lines.append("|------|---------|---------|-----------|------|")

    for cat, data in report["categories"].items():
        emoji = data["emoji"]
        desc = data["description"]
        bar = "█" * max(1, int(data["percentage"] / 5))
        lines.append(
            f"| {emoji} {desc} | {data['commits']} | "
            f"{data['lines_changed']:,} | {data['estimated_tokens']:,} | "
            f"{data['percentage']:.1f}% {bar} |"
        )

    lines.append("")

    # Top 3 token 消耗者
    cats = list(report["categories"].items())
    if cats:
        lines.append("## Top 3 Token 消耗")
        for i, (cat, data) in enumerate(cats[:3], 1):
            lines.append(f"{i}. **{data['emoji']} {data['description']}** — "
                         f"{data['percentage']:.1f}%（{data['commits']} commits, "
                         f"{data['lines_changed']:,} 行變更）")

    # 詳細 commit 列表（daily only）
    if report["report_type"] == "daily":
        lines.append("")
        lines.append("## 詳細 Commits")
        for cat, data in report["categories"].items():
            if "commit_messages" in data:
                lines.append(f"\n### {data['emoji']} {data['description']}")
                for msg in data["commit_messages"]:
                    lines.append(f"- {msg}")

    return "\n".join(lines)


def save_report(report, text):
    """儲存報告到 storage"""
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
    parser = argparse.ArgumentParser(description="Token Usage Report")
    parser.add_argument("--date", help="指定日期 (YYYY-MM-DD)")
    parser.add_argument("--weekly", action="store_true", help="產出週報")
    parser.add_argument("--week-start", help="週報起始日 (YYYY-MM-DD)")
    parser.add_argument("--detailed", action="store_true", help="包含 commit 列表")
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
        report = generate_daily_report(target_date, detailed=args.detailed)

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
