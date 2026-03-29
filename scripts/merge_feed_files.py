"""Merge storage/feed.json into storage/reports/feed.json (single source of truth).

Runs every hour via cron to prevent articles from being stranded in the wrong file.
Idempotent: safe to run multiple times.
"""
import json
import sys
from pathlib import Path

storage = Path(__file__).resolve().parent.parent / "storage"
main_feed = storage / "reports" / "feed.json"
agent_feed = storage / "feed.json"

if not agent_feed.exists():
    sys.exit(0)

# Read both
with open(main_feed) as f:
    main = json.load(f)
main_items = main if isinstance(main, list) else main.get("items", [])

with open(agent_feed) as f:
    agent = json.load(f)
agent_items = agent.get("items", []) if isinstance(agent, dict) else agent

# Merge: add items from agent_feed not in main_feed
main_ids = {a.get("id") for a in main_items if isinstance(a, dict)}
added = 0
for item in agent_items:
    if isinstance(item, dict) and item.get("id") not in main_ids:
        main_items.append(item)
        added += 1

if added > 0:
    if isinstance(main, list):
        with open(main_feed, "w") as f:
            json.dump(main_items, f, ensure_ascii=False, indent=2)
    else:
        main["items"] = main_items
        with open(main_feed, "w") as f:
            json.dump(main, f, ensure_ascii=False, indent=2)
    print(f"Merged {added} articles from storage/feed.json → storage/reports/feed.json")
else:
    pass  # No new articles to merge
