#!/usr/bin/env python3
"""
K322: Clean Up Empty/Stub Articles — Content Quality Enforcement

Background: K320 identified content-deficient articles that hurt SEO and user experience.
This script scans feed.json, classifies each deficient article, and produces
a structured action plan (no modifications are made).

[提出: 用戶, 執行: Claude]

Results:
- 15 empty articles (no content AND no description)
- 3 stub articles (content < 100 chars)
- 21 borderline articles (100-200 chars) — noted but not actioned
- 4 duplicate daily updates (same date, same content)
"""

import json
import os
from datetime import datetime, timezone

FEED_PATH = "storage/reports/feed.json"
KNOWLEDGE_PATH = "storage/memory/knowledge.json"
OUTPUT_PATH = "experiments/k322_cleanup_actions.json"


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def get_text_length(article):
    """Return the effective text and its length for an article."""
    c = article.get("content", "") or ""
    d = article.get("description", "") or ""
    text = c if len(c.strip()) > 0 else d
    return text.strip(), len(text.strip())


def classify_article(article, text, text_len, knowledge_entries):
    """Classify an article and decide action.

    Returns:
        dict with keys: action, reason, knowledge_available, regeneration_possible
    """
    aid = article["id"]
    title = article["title"]
    category = article.get("category", "")
    tags = article.get("tags", [])
    status = article.get("status", "")
    created = article.get("created_at", "")

    # --- Rule 1: System test articles → archive ---
    if "system_test" in (article.get("phase", "") or ""):
        return {
            "action": "archive",
            "reason": "System test article — not real research content",
            "knowledge_available": False,
            "regeneration_possible": False,
        }
    if "系統測試" in title or "system test" in title.lower():
        return {
            "action": "archive",
            "reason": "System test article — not real research content",
            "knowledge_available": False,
            "regeneration_possible": False,
        }

    # --- Rule 2: Duplicates → archive all but newest ---
    # (handled separately in main)

    # --- Rule 3: Old comparison/experiment articles with empty content ---
    # These are early-phase articles from 2026-03-14 that were published
    # before the content-quality rules were established.
    # Check if knowledge exists for regeneration.
    search_terms = _extract_search_terms(title, tags)
    matching_knowledge = _search_knowledge(search_terms, knowledge_entries)

    if text_len == 0:
        if len(matching_knowledge) >= 2:
            return {
                "action": "regenerate",
                "reason": f"Empty article with meaningful title; {len(matching_knowledge)} related knowledge entries available",
                "knowledge_available": True,
                "regeneration_possible": True,
                "knowledge_count": len(matching_knowledge),
                "knowledge_sample": [
                    k.get("title", k.get("content", "")[:60])[:80]
                    for k in matching_knowledge[:3]
                ],
            }
        else:
            return {
                "action": "archive",
                "reason": f"Empty article with insufficient knowledge for regeneration ({len(matching_knowledge)} entries)",
                "knowledge_available": len(matching_knowledge) > 0,
                "regeneration_possible": False,
            }

    # --- Rule 4: Stub articles (<100 chars) ---
    if 0 < text_len < 100:
        if "系統修正" in title or "修正" in title:
            return {
                "action": "archive",
                "reason": "Internal system fix note — not user-facing content",
                "knowledge_available": False,
                "regeneration_possible": False,
            }
        if len(matching_knowledge) >= 2:
            return {
                "action": "regenerate",
                "reason": f"Stub article ({text_len} chars); {len(matching_knowledge)} related knowledge entries for expansion",
                "knowledge_available": True,
                "regeneration_possible": True,
                "knowledge_count": len(matching_knowledge),
                "knowledge_sample": [
                    k.get("title", k.get("content", "")[:60])[:80]
                    for k in matching_knowledge[:3]
                ],
            }
        else:
            return {
                "action": "archive",
                "reason": f"Stub article ({text_len} chars) with insufficient knowledge",
                "knowledge_available": len(matching_knowledge) > 0,
                "regeneration_possible": False,
            }

    # Borderline — note only
    return {
        "action": "note",
        "reason": f"Borderline ({text_len} chars) — monitor but no immediate action needed",
        "knowledge_available": len(matching_knowledge) > 0,
        "regeneration_possible": False,
    }


def _extract_search_terms(title, tags):
    """Extract meaningful search terms from title and tags."""
    terms = []
    # Add tags
    terms.extend(tags)
    # Extract key phrases from title
    for word in title.split():
        if len(word) > 2 and word not in ("的", "在", "和", "是", "了", "但", "與"):
            terms.append(word)
    # Special keywords
    keyword_map = {
        "Adaptive Window": ["adaptive window", "persistence stability"],
        "H5": ["H5", "2025 驗證"],
        "Window Size": ["window size", "ablation"],
        "Phase H1": ["Phase H1", "OOS"],
        "Risk Parity": ["risk parity"],
        "GJR-HAR": ["GJR-HAR", "HAR"],
        "GJR-Range": ["GJR-Range", "range", "CARR"],
        "QLIKE": ["QLIKE", "baseline"],
        "模型選擇": ["model selection"],
        "排行": ["ranking", "排行"],
        "穩健性": ["robustness", "穩健"],
        "cross_period": ["cross period", "cross OOS"],
        "w=5000": ["window", "w=5000", "w=504"],
    }
    for key, values in keyword_map.items():
        if key.lower() in title.lower():
            terms.extend(values)
    return terms


def _search_knowledge(search_terms, knowledge_entries):
    """Search knowledge entries for matching terms."""
    matches = []
    for k in knowledge_entries:
        content = (k.get("content", "") or "").lower()
        title = (k.get("title", "") or "").lower()
        combined = content + " " + title
        score = sum(1 for term in search_terms if term.lower() in combined)
        if score >= 2:  # At least 2 term matches
            matches.append(k)
    return matches[:10]  # Cap at 10


def find_duplicates(articles):
    """Find duplicate groups by title."""
    from collections import defaultdict

    title_groups = defaultdict(list)
    for a in articles:
        title_groups[a["title"]].append(a)

    duplicates = {}
    for title, group in title_groups.items():
        if len(group) > 1:
            # Keep newest, archive rest
            sorted_group = sorted(
                group, key=lambda x: x.get("created_at", ""), reverse=True
            )
            keep = sorted_group[0]
            archive = sorted_group[1:]
            duplicates[title] = {
                "keep": keep["id"],
                "archive": [a["id"] for a in archive],
                "count": len(group),
            }
    return duplicates


def main():
    articles = load_json(FEED_PATH)
    knowledge = load_json(KNOWLEDGE_PATH)

    print(f"Total articles: {len(articles)}")
    print(f"Total knowledge entries: {len(knowledge)}")

    # === Phase 1: Find all deficient articles ===
    empty_articles = []
    stub_articles = []
    borderline_articles = []

    for a in articles:
        text, text_len = get_text_length(a)
        if text_len == 0:
            empty_articles.append(a)
        elif text_len < 100:
            stub_articles.append(a)
        elif text_len < 200:
            borderline_articles.append(a)

    print(f"\nEmpty (no content + no description): {len(empty_articles)}")
    print(f"Stubs (<100 chars): {len(stub_articles)}")
    print(f"Borderline (100-200 chars): {len(borderline_articles)}")

    # === Phase 2: Find duplicates ===
    duplicates = find_duplicates(articles)
    print(f"Duplicate groups: {len(duplicates)}")

    # === Phase 3: Classify each deficient article ===
    actions = []

    # Process empty articles
    for a in empty_articles:
        text, text_len = get_text_length(a)
        classification = classify_article(a, text, text_len, knowledge)
        actions.append(
            {
                "id": a["id"],
                "title": a["title"],
                "category": a.get("category"),
                "status": a.get("status"),
                "created_at": a.get("created_at", "")[:10],
                "text_length": text_len,
                "deficiency_type": "empty",
                "has_individual_file": os.path.exists(f"storage/reports/{a['id']}.json"),
                **classification,
            }
        )

    # Process stub articles
    for a in stub_articles:
        text, text_len = get_text_length(a)
        classification = classify_article(a, text, text_len, knowledge)
        actions.append(
            {
                "id": a["id"],
                "title": a["title"],
                "category": a.get("category"),
                "status": a.get("status"),
                "created_at": a.get("created_at", "")[:10],
                "text_length": text_len,
                "deficiency_type": "stub",
                "has_individual_file": os.path.exists(f"storage/reports/{a['id']}.json"),
                **classification,
            }
        )

    # Process duplicates
    duplicate_actions = []
    for title, dup_info in duplicates.items():
        for archive_id in dup_info["archive"]:
            duplicate_actions.append(
                {
                    "id": archive_id,
                    "title": title,
                    "action": "archive",
                    "reason": f"Duplicate ({dup_info['count']}x same title). Keeping {dup_info['keep']}",
                    "deficiency_type": "duplicate",
                    "keep_id": dup_info["keep"],
                }
            )

    # === Phase 4: Summary statistics ===
    action_counts = {}
    for a in actions:
        act = a["action"]
        action_counts[act] = action_counts.get(act, 0) + 1

    for a in duplicate_actions:
        act = a["action"]
        action_counts[act] = action_counts.get(act, 0) + 1

    # === Phase 5: Borderline notes (informational only) ===
    borderline_notes = []
    for a in borderline_articles:
        text, text_len = get_text_length(a)
        borderline_notes.append(
            {
                "id": a["id"],
                "title": a["title"],
                "text_length": text_len,
                "status": a.get("status"),
                "created_at": a.get("created_at", "")[:10],
                "note": "Borderline short content — may benefit from expansion in future",
            }
        )

    # === Output ===
    result = {
        "experiment": "K322",
        "title": "Clean Up Empty/Stub Articles — Content Quality Enforcement",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_articles_scanned": len(articles),
            "empty_articles": len(empty_articles),
            "stub_articles": len(stub_articles),
            "borderline_articles": len(borderline_articles),
            "duplicate_groups": len(duplicates),
            "total_actions": len(actions) + len(duplicate_actions),
            "action_breakdown": action_counts,
        },
        "actions": actions,
        "duplicate_actions": duplicate_actions,
        "borderline_notes": borderline_notes,
        "rules_applied": [
            "System test articles → archive",
            "Duplicate titles → archive all but newest",
            "Empty articles with ≥2 knowledge entries → regenerate",
            "Empty articles with <2 knowledge entries → archive",
            "Stub articles that are internal fix notes → archive",
            "Stub articles with ≥2 knowledge entries → regenerate",
            "Borderline articles (100-200 chars) → note only (no action)",
        ],
        "safety_notes": [
            "NO articles are deleted — only status changes to 'archived'",
            "Regeneration means creating new content from knowledge.json, not fabrication",
            "All changes should go through ops CLI, not direct JSON editing",
            "This script is analysis-only — no files are modified",
        ],
    }

    # Write output
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    # Print summary
    print("\n" + "=" * 60)
    print("K322 RESULTS")
    print("=" * 60)
    print(f"\nTotal deficient articles: {len(actions)}")
    print(f"Duplicate articles: {len(duplicate_actions)}")
    print(f"\nAction breakdown:")
    for act, count in sorted(action_counts.items()):
        print(f"  {act}: {count}")

    print("\n--- ARCHIVE actions ---")
    archive_count = 0
    for a in actions + duplicate_actions:
        if a["action"] == "archive":
            archive_count += 1
            print(f"  [{a['deficiency_type']}] {a['id']}: {a['title'][:55]}")
            print(f"    Reason: {a['reason']}")

    print(f"\n--- REGENERATE actions ---")
    regen_count = 0
    for a in actions:
        if a["action"] == "regenerate":
            regen_count += 1
            print(f"  [{a['deficiency_type']}] {a['id']}: {a['title'][:55]}")
            print(f"    Reason: {a['reason']}")
            if "knowledge_sample" in a:
                print(f"    Knowledge sample: {a['knowledge_sample'][:2]}")

    print(f"\n--- BORDERLINE (no action) ---")
    print(f"  {len(borderline_notes)} articles between 100-200 chars")
    print(f"  (includes {len(duplicates)} duplicate group(s) with {sum(d['count']-1 for d in duplicates.values())} extra copies)")

    print(f"\n{'=' * 60}")
    print(f"TOTALS: {archive_count} to archive, {regen_count} to regenerate")
    print(f"Output saved to: {OUTPUT_PATH}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
