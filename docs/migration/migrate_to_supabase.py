"""
VolPred v2 — 資料遷移腳本
將 storage/ 的 JSON 資料匯入 Supabase PostgreSQL

用法：
  python docs/migration/migrate_to_supabase.py [--dry-run] [--step articles|questions|memory|all]

需要環境變數：
  SUPABASE_URL=https://qxhfgdfzazwpkdgesavm.supabase.co
  SUPABASE_SERVICE_ROLE_KEY=sb_secret_xxx
"""

import json
import os
import sys
import argparse
import re
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ─── Config ───

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://qxhfgdfzazwpkdgesavm.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
STORAGE_DIR = Path(__file__).resolve().parent.parent.parent / "storage"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates",  # upsert
}

# ─── Helpers ───

def supabase_upsert(table: str, rows: list[dict], dry_run: bool = False) -> int:
    """Upsert rows to Supabase table. Returns count of rows sent."""
    if not rows:
        return 0
    if dry_run:
        print(f"  [DRY RUN] Would upsert {len(rows)} rows to {table}")
        return len(rows)

    # Batch in chunks of 100
    total = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i+100]
        url = f"{SUPABASE_URL}/rest/v1/{table}"
        data = json.dumps(batch, ensure_ascii=False).encode("utf-8")
        req = Request(url, data=data, headers=HEADERS, method="POST")
        try:
            resp = urlopen(req)
            total += len(batch)
            print(f"  ✓ {table}: upserted batch {i//100+1} ({len(batch)} rows)")
        except HTTPError as e:
            body = e.read().decode()
            print(f"  ✗ {table} batch {i//100+1} failed: {e.code} {body}")
            # Continue with remaining batches
    return total


def classify_audience(item: dict) -> str:
    """根據 phase/tags 分類 audience"""
    phase = (item.get("phase") or "").lower()
    tags = item.get("tags") or []
    tags_lower = [t.lower() for t in tags]

    if phase == "general_content" or "一般讀者" in tags_lower:
        return "general"
    if "daily" in phase or "daily_update" in tags_lower or "每日更新" in tags_lower:
        return "daily"
    if "diary" in phase or "研究日記" in tags_lower:
        return "diary"
    if "qa" in phase or "q&a" in tags_lower:
        return "qa"
    return "research"


def extract_proposer(item: dict) -> str | None:
    """從 content/description 提取 [提出: XXX]"""
    for field in ["content", "description"]:
        text = item.get(field) or ""
        match = re.search(r'\[提出:\s*(\w+)', text)
        if match:
            return match.group(1)
    return None


def make_excerpt(content: str, max_len: int = 200) -> str:
    """截取前 max_len 字作為摘要"""
    if not content:
        return ""
    # 移除 markdown 標記和歸屬標注
    clean = re.sub(r'\[提出:.*?\]', '', content)
    clean = re.sub(r'---+', '', clean)
    clean = re.sub(r'[#*`>]', '', clean)
    clean = clean.strip()
    if len(clean) > max_len:
        return clean[:max_len] + "..."
    return clean


# ─── Step 1: Articles ───

def migrate_articles(dry_run: bool = False):
    """匯入 feed.json + individual reports → articles + tags + article_tags"""
    print("\n═══ Step 1: Articles ═══")

    feed_path = STORAGE_DIR / "reports" / "feed.json"
    reports_dir = STORAGE_DIR / "reports"

    with open(feed_path) as f:
        feed = json.load(f)
    print(f"  Feed entries: {len(feed)}")

    # Collect all unique tags
    all_tags = set()
    for item in feed:
        for tag in (item.get("tags") or []):
            all_tags.add(tag)

    # 1a. Upsert tags
    tag_rows = [{"name": t} for t in sorted(all_tags)]
    print(f"  Unique tags: {len(tag_rows)}")
    supabase_upsert("tags", tag_rows, dry_run)

    # 1b. Upsert articles
    article_rows = []
    for item in feed:
        # Try to get full content from individual report
        report_path = reports_dir / f"{item['id']}.json"
        content = ""
        if report_path.exists():
            with open(report_path) as rf:
                report = json.load(rf)
                content = report.get("content") or ""

        # Fallback to feed content or description
        if not content:
            content = item.get("content") or item.get("description") or ""

        article_rows.append({
            "slug": item["id"],
            "title": item["title"],
            "content": content,
            "excerpt": make_excerpt(content),
            "audience": classify_audience(item),
            "phase": item.get("phase"),
            "status": item.get("status", "published"),
            "category": item.get("category", "milestone"),
            "proposer": extract_proposer(item),
            "author_id": "claude",
            "details": item.get("details") if item.get("details") else None,
            "published_at": item.get("published_at"),
            "created_at": item.get("created_at") or item.get("published_at"),
        })

    print(f"  Articles to upsert: {len(article_rows)}")
    supabase_upsert("articles", article_rows, dry_run)

    # 1c. Link article_tags (need to query back IDs)
    if not dry_run:
        print("  Linking article_tags (requires querying article/tag IDs)...")
        # Get article id mapping (slug → uuid)
        url = f"{SUPABASE_URL}/rest/v1/articles?select=id,slug"
        req = Request(url, headers={**HEADERS, "Prefer": ""})
        resp = urlopen(req)
        articles_map = {a["slug"]: a["id"] for a in json.loads(resp.read())}

        # Get tag id mapping (name → id)
        url = f"{SUPABASE_URL}/rest/v1/tags?select=id,name"
        req = Request(url, headers={**HEADERS, "Prefer": ""})
        resp = urlopen(req)
        tags_map = {t["name"]: t["id"] for t in json.loads(resp.read())}

        # Build join table rows
        at_rows = []
        for item in feed:
            article_uuid = articles_map.get(item["id"])
            if not article_uuid:
                continue
            for tag_name in (item.get("tags") or []):
                tag_id = tags_map.get(tag_name)
                if tag_id:
                    at_rows.append({
                        "article_id": article_uuid,
                        "tag_id": tag_id,
                    })

        print(f"  Article-tag links: {len(at_rows)}")
        supabase_upsert("article_tags", at_rows)
    else:
        print(f"  [DRY RUN] Would link article_tags after querying IDs")

    print("  ✓ Articles migration complete")


# ─── Step 2: Questions ───

def migrate_questions(dry_run: bool = False):
    """匯入 open_questions.json → questions + question_articles"""
    print("\n═══ Step 2: Questions ═══")

    q_path = STORAGE_DIR / "memory" / "open_questions.json"
    with open(q_path) as f:
        questions = json.load(f)
    print(f"  Questions: {len(questions)}")

    q_rows = []
    for q in questions:
        q_rows.append({
            "source": "internal",
            "question": q.get("question", ""),
            "status": q.get("status", "open"),
            "priority": q.get("priority", "medium"),
            "proposer": q.get("proposer"),
            "answer": q.get("answer"),
            "score": q.get("score"),
            "score_breakdown": q.get("score_breakdown"),
        })

    supabase_upsert("questions", q_rows, dry_run)

    # question_articles linking (skip if dry_run)
    if not dry_run and any(q.get("feed_articles") for q in questions):
        print("  Linking question_articles...")
        # Get question mapping
        url = f"{SUPABASE_URL}/rest/v1/questions?select=id,question&source=eq.internal"
        req = Request(url, headers={**HEADERS, "Prefer": ""})
        resp = urlopen(req)
        q_map = {q["question"][:50]: q["id"] for q in json.loads(resp.read())}

        # Get article mapping
        url = f"{SUPABASE_URL}/rest/v1/articles?select=id,slug"
        req = Request(url, headers={**HEADERS, "Prefer": ""})
        resp = urlopen(req)
        a_map = {a["slug"]: a["id"] for a in json.loads(resp.read())}

        qa_rows = []
        for q in questions:
            q_id = q_map.get(q.get("question", "")[:50])
            if not q_id:
                continue
            for slug in (q.get("feed_articles") or []):
                a_id = a_map.get(slug)
                if a_id:
                    qa_rows.append({"question_id": q_id, "article_id": a_id})

        if qa_rows:
            print(f"  Question-article links: {len(qa_rows)}")
            supabase_upsert("question_articles", qa_rows)

    print("  ✓ Questions migration complete")


# ─── Step 3: Memory ───

def migrate_memory(dry_run: bool = False):
    """匯入 thinking/knowledge/experiments/research_log → memory_entries"""
    print("\n═══ Step 3: Memory ═══")

    memory_dir = STORAGE_DIR / "memory"
    sources = {
        "thinking": "thinking_journal.json",
        "knowledge": "knowledge.json",
        "experiment": "experiments.json",
        "log": "research_log.json",
    }

    for mem_type, filename in sources.items():
        path = memory_dir / filename
        if not path.exists():
            print(f"  {filename}: NOT FOUND, skipping")
            continue

        with open(path) as f:
            entries = json.load(f)

        rows = []
        for i, entry in enumerate(entries):
            entry_id = entry.get("id") or entry.get("item_id") or f"{mem_type}_{i:04d}"
            rows.append({
                "id": str(entry_id),
                "type": mem_type,
                "content": entry,
                "created_at": entry.get("created_at") or entry.get("timestamp"),
            })

        print(f"  {filename}: {len(rows)} entries")
        supabase_upsert("memory_entries", rows, dry_run)

    print("  ✓ Memory migration complete")


# ─── Step 4: Risk Forecast + Paper Trading ───

def migrate_misc(dry_run: bool = False):
    """匯入 risk_forecast + paper_trading"""
    print("\n═══ Step 4: Risk Forecast + Paper Trading ═══")

    # Risk forecast
    rf_path = STORAGE_DIR / "risk_forecast.json"
    if rf_path.exists():
        with open(rf_path) as f:
            rf_data = json.load(f)
        supabase_upsert("risk_forecasts", [{"data": rf_data}], dry_run)
        print(f"  ✓ risk_forecast uploaded")
    else:
        print(f"  risk_forecast.json: NOT FOUND")

    # Paper trading
    pt_path = STORAGE_DIR / "paper_trading.json"
    if pt_path.exists():
        with open(pt_path) as f:
            pt_data = json.load(f)
        rows = []
        if isinstance(pt_data, list):
            for entry in pt_data:
                rows.append({
                    "strategy": entry.get("strategy", "unknown"),
                    "entry": entry,
                    "trade_date": entry.get("date") or entry.get("trade_date"),
                })
        elif isinstance(pt_data, dict):
            for strategy, trades in pt_data.items():
                if isinstance(trades, list):
                    for entry in trades:
                        rows.append({
                            "strategy": strategy,
                            "entry": entry,
                            "trade_date": entry.get("date") or entry.get("trade_date"),
                        })
        print(f"  Paper trades: {len(rows)} entries")
        if rows:
            supabase_upsert("paper_trades", rows, dry_run)
    else:
        print(f"  paper_trading.json: NOT FOUND")

    print("  ✓ Misc migration complete")


# ─── Main ───

def main():
    parser = argparse.ArgumentParser(description="Migrate VolPred data to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without writing")
    parser.add_argument("--step", choices=["articles", "questions", "memory", "misc", "all"], default="all")
    args = parser.parse_args()

    if not SUPABASE_KEY:
        print("ERROR: Set SUPABASE_SERVICE_ROLE_KEY environment variable")
        sys.exit(1)

    print(f"Supabase URL: {SUPABASE_URL}")
    print(f"Storage dir: {STORAGE_DIR}")
    print(f"Dry run: {args.dry_run}")

    steps = {
        "articles": migrate_articles,
        "questions": migrate_questions,
        "memory": migrate_memory,
        "misc": migrate_misc,
    }

    if args.step == "all":
        for fn in steps.values():
            fn(args.dry_run)
    else:
        steps[args.step](args.dry_run)

    print("\n═══ Migration complete ═══")


if __name__ == "__main__":
    main()
