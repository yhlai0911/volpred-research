#!/usr/bin/env python3
"""
Build publication candidate list: K experiments that have PASS/important results
but no feed article covering them yet.

Output: storage/publication_candidates.json

Logic:
1. Scan knowledge.json for all experiments (experiment_id = K_NN)
2. For each K, find feed articles covering it via:
   - tags array containing K_NN
   - title containing K_NN
   - content (description) mentioning K_NN
3. Score priority based on verdict keywords:
   - PASS / Harvey / significant / robust → +3
   - universal / cross-market / three-market → +3
   - mechanism / methodology warning → +2
   - NULL decisive / paradigm → +2
   - sample too small / inconclusive → -1
4. Output sorted candidates with coverage status.
"""
import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
KNOWLEDGE_PATH = ROOT / "storage/memory/knowledge.json"
FEED_PATH = ROOT / "storage/reports/feed.json"
OUTPUT_PATH = ROOT / "storage/publication_candidates.json"


def extract_k_id(experiment_id: str) -> str | None:
    """Normalize K1145, k1145, K1145b → K1145."""
    if not experiment_id:
        return None
    m = re.match(r"[Kk](\d+)", experiment_id)
    if not m:
        return None
    return f"K{m.group(1)}"


def score_priority(entry: dict) -> tuple[int, list[str]]:
    """Score 0-10 based on content keywords. Return (score, reasons)."""
    content = (entry.get("content", "") + " " + entry.get("title", "")).lower()
    score = 0
    reasons = []
    # Positive signals
    if any(k in content for k in ["pass", "harvey"]) and "fail" not in content[:200]:
        score += 3
        reasons.append("PASS/Harvey-significant")
    if any(k in content for k in ["universal", "cross-market", "three-market", "三市場"]):
        score += 3
        reasons.append("cross-market/universal")
    if any(k in content for k in ["mechanism", "methodology", "教訓", "warning"]):
        score += 2
        reasons.append("methodology/mechanism lesson")
    if any(k in content for k in ["decisive", "決定性", "paradigm", "推翻"]):
        score += 2
        reasons.append("paradigm/decisive null")
    if any(k in content for k in ["bootstrap", "placebo", "robust"]):
        score += 1
        reasons.append("robust inference")
    if any(k in content for k in ["5 layer", "五層", "5 robustness"]):
        score += 2
        reasons.append("5-layer robustness")
    # Negative signals
    if any(k in content for k in ["inconclusive", "data 不足", "sample too small"]):
        score -= 2
        reasons.append("inconclusive (data limit)")
    if any(k in content for k in ["mixed", "scenario stable"]):
        score -= 1
        reasons.append("mixed/non-novel")
    return max(0, min(10, score)), reasons


def k_covered_by_article(k_id: str, article: dict) -> bool:
    """Check whether article covers this K via tags/title/content/experiment_refs."""
    k_lower = k_id.lower()
    k_upper = k_id.upper()
    # 1. tags
    tags = [str(t).lower() for t in article.get("tags", [])]
    if k_lower in tags:
        return True
    # 2. details.experiment_refs (canonical structured field per feed-publisher
    # SKILL.md K-id stripping; titles get K-id stripped to experiment_refs).
    # 2026-05-11 K869 incident: mile_4ec7b75e covered K869 but build script
    # only checked tags/title/content, missed structured refs → K869 stayed
    # falsely uncovered for 6 days.
    details = article.get("details") or {}
    if isinstance(details, dict):
        refs = details.get("experiment_refs") or []
        if isinstance(refs, list) and any(str(r).upper() == k_upper for r in refs):
            return True
    # 3. title
    title = str(article.get("title", "")).lower()
    if k_lower in title:
        return True
    # 4. description + content body
    content = str(article.get("description", "") + article.get("content", "")).lower()
    # Match K1145 or k1145 but not K114 inside K1145
    pattern = rf"\b{re.escape(k_lower)}\b"
    if re.search(pattern, content):
        return True
    return False


def main():
    if not KNOWLEDGE_PATH.exists():
        print(f"ERROR: {KNOWLEDGE_PATH} not found", file=sys.stderr)
        sys.exit(1)
    if not FEED_PATH.exists():
        print(f"ERROR: {FEED_PATH} not found", file=sys.stderr)
        sys.exit(1)

    knowledge = json.loads(KNOWLEDGE_PATH.read_text())
    feed = json.loads(FEED_PATH.read_text())

    # Deduplicate knowledge by experiment_id (keep latest)
    by_k: dict[str, dict] = {}
    for entry in knowledge:
        k_id = extract_k_id(entry.get("experiment_id", ""))
        if not k_id:
            continue
        existing = by_k.get(k_id)
        if existing is None or entry.get("updated_at", "") > existing.get("updated_at", ""):
            by_k[k_id] = entry

    # For each K, check feed coverage
    candidates = []
    for k_id, entry in by_k.items():
        covering_articles = []
        for article in feed:
            if k_covered_by_article(k_id, article):
                covering_articles.append({
                    "id": article.get("id"),
                    "title": article.get("title", ""),
                    "status": article.get("status"),
                    "audience": article.get("audience"),
                })
        score, reasons = score_priority(entry)
        candidates.append({
            "k_id": k_id,
            "title": entry.get("title", ""),
            "score": score,
            "reasons": reasons,
            "verdict_preview": entry.get("content", "")[:300],
            "covered_by": covering_articles,
            "uncovered": len(covering_articles) == 0,
            # Treat audience=None/empty as 'general' (pre-2026-04-14 articles
            # had no audience metadata; platform default-tone was general).
            # 2026-05-11 K665/K630/K622 incidents: dropping audience=null from
            # this set caused refill_task_pool to mistakenly queue articles
            # for K-experiments that already had audience=null legacy coverage.
            "audiences_covered": sorted({
                (a.get("audience") or "general")
                for a in covering_articles
            }),
            "updated_at": entry.get("updated_at", ""),
            "tags": entry.get("tags", []),
        })

    # Sort: uncovered first, then by score desc, then by recency desc
    candidates.sort(
        key=lambda c: (
            not c["uncovered"],
            -c["score"],
            c.get("updated_at", ""),
        ),
        reverse=False,
    )

    # Summary
    total = len(candidates)
    uncovered = sum(1 for c in candidates if c["uncovered"])
    high_uncovered = [c for c in candidates if c["uncovered"] and c["score"] >= 5]

    # 2026-05-09 K979 incident: missing_audience 須 cluster by topic family，非僅 K-id
    # K979 was tagged missing_general because no article mentioned "K979", but K447's
    # mile_1b2ad1f8 (general SKEW article from 2026-05-05) covered the same topic family.
    # Fix: compute tag-overlap between candidate K and existing articles in target audience;
    # if ≥2 domain tags overlap, mark as topic_family_collision and exclude from missing list.
    GENERIC_TAGS = {
        "一般讀者", "研究", "general", "research", "深度研究",
        "波動率預測", "vol-prediction", "volatility", "金融研究",
    }

    def _norm_tag(t: str) -> str:
        return t.strip().lower().replace("_", "-")

    def _domain_tags(tags: list) -> set[str]:
        return {_norm_tag(t) for t in (tags or []) if t and t not in GENERIC_TAGS}

    def _topic_family_collision(cand_tags: set[str], audience: str) -> list[dict]:
        """Find feed articles in target audience sharing ≥2 domain tags with candidate K."""
        if not cand_tags:
            return []
        hits = []
        for art in feed:
            if not isinstance(art, dict):
                continue
            if (art.get("audience") or (art.get("details") or {}).get("audience")) != audience:
                continue
            art_tags = _domain_tags(art.get("tags") or [])
            overlap = cand_tags & art_tags
            if len(overlap) >= 2:
                hits.append({
                    "id": art.get("id"),
                    "title": art.get("title", "")[:80],
                    "shared_tags": sorted(overlap),
                })
        return hits

    # Annotate each candidate with topic_family_collision per audience
    for c in candidates:
        cand_tags = _domain_tags(c.get("tags") or [])
        c["topic_family_collisions"] = {
            "general": _topic_family_collision(cand_tags, "general"),
            "research": _topic_family_collision(cand_tags, "research"),
        }

    missing_general = [
        c for c in candidates
        if c["covered_by"]
        and "general" not in c["audiences_covered"]
        and c["score"] >= 4
        and not c["topic_family_collisions"]["general"]  # exclude topic-family clashes
    ]
    missing_research = [
        c for c in candidates
        if c["covered_by"]
        and "research" not in c["audiences_covered"]
        and c["score"] >= 4
        and not c["topic_family_collisions"]["research"]
    ]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_k": total,
            "uncovered": uncovered,
            "high_priority_uncovered": len(high_uncovered),
            "missing_general_audience": len(missing_general),
            "missing_research_audience": len(missing_research),
        },
        "top_10_uncovered": [
            {"k_id": c["k_id"], "score": c["score"], "title": c["title"][:120]}
            for c in candidates[:10] if c["uncovered"]
        ],
        "missing_general_top5": [
            {"k_id": c["k_id"], "score": c["score"], "title": c["title"][:120],
             "already_covered_for": c["audiences_covered"]}
            for c in missing_general[:5]
        ],
        "missing_research_top5": [
            {"k_id": c["k_id"], "score": c["score"], "title": c["title"][:120],
             "already_covered_for": c["audiences_covered"]}
            for c in missing_research[:5]
        ],
        "candidates": candidates,
    }

    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))

    # Print concise summary
    print(f"Scanned {total} K experiments.")
    print(f"  Uncovered: {uncovered}")
    print(f"  High-priority uncovered (score≥5): {len(high_uncovered)}")
    print(f"  Covered but missing general audience: {len(missing_general)}")
    print(f"  Covered but missing research audience: {len(missing_research)}")
    print()
    print("Top 5 uncovered candidates:")
    for c in [c for c in candidates if c["uncovered"]][:5]:
        print(f"  [{c['score']}] {c['k_id']}: {c['title'][:100]}")
    print()
    print(f"Full output: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
