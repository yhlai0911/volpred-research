"""One-stop recording: think + knowledge + publish via Publisher.

Usage:
    uv run python scripts/record_and_publish.py \
        --title "發現標題" \
        --thinking "推理過程" \
        --knowledge "知識內容" \
        --category "model_behavior" \
        --phase "Phase_M"

This ensures every finding is simultaneously recorded to:
1. thinking_journal.json  (via MemorySystem)
2. knowledge.json         (via MemorySystem)
3. feed.json + report     (via Publisher — correct format guaranteed)
4. frontend               (via daily_update sync)
"""
import argparse
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from volpred.config.runtime import get_default_remote_url, get_local_data_sync_dirs
from volpred.memory.system import MemorySystem
from volpred.publisher.publisher import Publisher


def record_and_publish(
    title: str,
    thinking: str,
    knowledge: str = "",
    category: str = "model_behavior",
    phase: str = "",
    confidence: float = 0.85,
    evidence: list = None,
    tags: list[str] | None = None,
):
    m = MemorySystem()
    pub = Publisher()

    # 1. Research log — 記錄發佈事件（不寫 thinking_journal）
    # thinking_journal 只用於研究決策邏輯，發佈事件記在 research_log
    m.add_log_entry(
        phase=phase or "publish",
        action=f"Published: {title}",
        observation=f"Content length: {len(thinking)} chars",
        decision="Feed article published",
    )
    print(f"✓ research_log updated (publish event, NOT thinking)")

    # 2. Knowledge (if provided)
    if knowledge:
        m.add_knowledge(
            category=category,
            content=knowledge,
            evidence=evidence or [],
            confidence=confidence,
        )
        print(f"✓ knowledge updated")

    # 3. Publish via Publisher (correct format: category, status, published_at)
    # content = full thinking text, description = short summary for feed card
    pub.publish_milestone(
        title=title,
        description=thinking,  # Full content (will also be stored as content)
        phase=phase,
        tags=tags,
    )
    # Ensure content and tags fields are set
    import json
    feed_path = Path("storage/reports/feed.json")
    report_id = ""
    if feed_path.exists():
        feed = json.loads(feed_path.read_text())
        if feed and feed[0].get("title") == title:
            feed[0]["content"] = thinking  # Store full text in content field
            feed[0]["description"] = thinking[:300] + "..." if len(thinking) > 300 else thinking
            if tags:
                feed[0]["tags"] = tags  # Ensure tags are set
            feed_path.write_text(json.dumps(feed, indent=2, ensure_ascii=False, default=str))
            # Also update individual report
            report_id = feed[0].get("id", "")
            report_path = Path(f"storage/reports/{report_id}.json")
            if report_path.exists():
                report = json.loads(report_path.read_text())
                report["content"] = thinking
                report["description"] = feed[0]["description"]
                if tags:
                    report["tags"] = tags
                report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    print(f"✓ feed published (via Publisher — correct format)")

    # 4. Sync to configured local data mirrors
    storage = Path("storage")
    feed_path = storage / "reports" / "feed.json"
    data_sync_dirs = get_local_data_sync_dirs(active_only=True)
    synced_local_dirs = 0
    for data_dir in data_sync_dirs:
        data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(feed_path, data_dir / "feed.json")
        report_dir = data_dir / "reports"
        report_dir.mkdir(exist_ok=True)
        shutil.copy2(feed_path, report_dir / "feed.json")
        synced_local_dirs += 1

    # Sync individual report file to all locations
    if report_id:
        src_report = Path(f"storage/reports/{report_id}.json")
        if src_report.exists():
            for data_dir in data_sync_dirs:
                report_dir = data_dir / "reports"
                report_dir.mkdir(exist_ok=True)
                shutil.copy2(src_report, report_dir / f"{report_id}.json")

    if synced_local_dirs:
        print(f"✓ local data mirrors synced ({synced_local_dirs})")
    else:
        print("✓ local data mirrors skipped (no configured targets)")

    # 5. Sync to Zeabur via API (no redeploy needed)
    import json as json_mod
    zeabur_url = os.environ.get("VOLPRED_REMOTE_URL", get_default_remote_url())
    try:
        import urllib.request

        from volpred.mirror_auth import ops_admin_headers

        _sync_headers = {"Content-Type": "application/json", **ops_admin_headers()}
        feed_data = json_mod.loads(feed_path.read_text())
        req = urllib.request.Request(
            f"{zeabur_url}/api/sync/feed.json",
            data=json_mod.dumps(feed_data).encode(),
            headers=_sync_headers,
            method="POST",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        print(f"✓ Zeabur synced (feed: {resp.status})")
        # Also sync individual report
        if report_id:
            report_data = json_mod.loads(Path(f"storage/reports/{report_id}.json").read_text())
            req2 = urllib.request.Request(
                f"{zeabur_url}/api/sync/reports/{report_id}.json",
                data=json_mod.dumps(report_data).encode(),
                headers=_sync_headers,
                method="POST",
            )
            resp2 = urllib.request.urlopen(req2, timeout=10)
            print(f"✓ Zeabur synced (report: {resp2.status})")
    except Exception as e:
        # 2026-06-11: remote gated /api/sync (C1) — surface auth failures
        # loudly instead of a quiet "skipped" so 401s can't hide for weeks.
        print(f"  ⚠ Zeabur mirror sync FAILED (replica path, Supabase unaffected): {e}")

    # 6. Sync to Supabase (v2 website)
    try:
        from supabase_sync import sync_article, sync_memory_entry
        item = json.loads(feed_path.read_text())[0] if feed_path.exists() else {}
        if item:
            if sync_article(item):
                print(f"✓ Supabase synced (article)")
            else:
                print(f"  Supabase article sync failed")
        if knowledge:
            # Sync latest knowledge entry
            k_path = Path("storage/memory/knowledge.json")
            if k_path.exists():
                k_entries = json.loads(k_path.read_text())
                if k_entries:
                    latest = k_entries[-1]
                    kid = str(latest.get("item_id") or latest.get("id") or f"k_{len(k_entries)}")
                    sync_memory_entry(kid, "knowledge", latest)
                    print(f"✓ Supabase synced (knowledge)")
    except Exception as e:
        print(f"  Supabase sync skipped: {e}")

    print(f"\n📢 Published: {title}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True)
    parser.add_argument("--thinking", required=True)
    parser.add_argument("--knowledge", default="")
    parser.add_argument("--category", default="model_behavior")
    parser.add_argument("--phase", default="")
    parser.add_argument("--confidence", type=float, default=0.85)
    parser.add_argument("--tags", nargs="*", default=None, help="Tags for search/categorization")
    args = parser.parse_args()

    record_and_publish(
        title=args.title,
        thinking=args.thinking,
        knowledge=args.knowledge,
        category=args.category,
        phase=args.phase,
        confidence=args.confidence,
        tags=args.tags,
    )
