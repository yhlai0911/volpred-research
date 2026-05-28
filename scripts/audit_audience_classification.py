#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "storage" / "ops"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.publisher import _ACADEMIC_KEYWORDS  # noqa: E402

TITLE_KEYWORD_LABELS = {
    "GARCH",
    "GARCH-X",
    "HAR-RV",
    "Harvey",
    "Diebold-Mariano",
    "DM test",
    "QLIKE",
    "MLE",
    "bootstrap",
    "cointegration",
    "EGARCH",
    "MCS",
    "VaR",
}
EXPERIMENT_REF_PATTERN = re.compile(r"K\d+[A-Z0-9_]*", re.IGNORECASE)


def _extract_experiment_refs(item: dict) -> list[str]:
    refs = []
    details = item.get("details") or {}
    if isinstance(details, dict):
        for ref in details.get("experiment_refs") or []:
            if isinstance(ref, str):
                refs.append(ref.upper())
    for source in (item.get("title") or "", item.get("description") or "", item.get("content") or ""):
        refs.extend(match.upper() for match in EXPERIMENT_REF_PATTERN.findall(str(source)))
    deduped = []
    seen = set()
    for ref in refs:
        if ref not in seen:
            deduped.append(ref)
            seen.add(ref)
    return deduped


def _readme_exists(experiment_refs: list[str]) -> bool:
    for ref in experiment_refs:
        readme = ROOT / "experiments" / ref.lower() / "README.md"
        if readme.exists():
            return True
    return False


def _keyword_hits(text: str) -> list[str]:
    hits: list[str] = []
    seen = set()
    for pattern, label in _ACADEMIC_KEYWORDS:
        if label in seen:
            continue
        if pattern.search(text):
            hits.append(label)
            seen.add(label)
    return hits


def score_item(item: dict) -> dict:
    title = str(item.get("title") or "")
    description = str(item.get("description") or item.get("content") or "")
    combined = " ".join([title, description, " ".join(item.get("tags") or [])])
    experiment_refs = _extract_experiment_refs(item)

    title_hits = [hit for hit in _keyword_hits(title) if hit in TITLE_KEYWORD_LABELS]
    body_hits = _keyword_hits(combined)
    body_chars = len(description)
    unique_hits = len(set(body_hits))
    density_per_1000 = (len(body_hits) / max(body_chars, 1)) * 1000
    vocab_ratio_per_100 = (unique_hits / max(body_chars, 1)) * 100
    readme_exists = _readme_exists(experiment_refs)

    score = 0
    score += min(len(title_hits) * 18, 36)
    score += min(unique_hits * 8, 32)
    score += 14 if density_per_1000 >= 6 else 8 if density_per_1000 >= 3 else 0
    score += 8 if body_chars >= 2500 else 4 if body_chars >= 1600 else 0
    score += 10 if readme_exists else 0

    if score >= 62:
        tier = "HIGH"
    elif score >= 38:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    return {
        "id": item.get("id"),
        "title": title,
        "audience": item.get("audience"),
        "status": item.get("status"),
        "published_at": item.get("published_at") or item.get("created_at"),
        "score": score,
        "tier": tier,
        "title_keyword_hits": title_hits,
        "body_keyword_hits": body_hits,
        "body_chars": body_chars,
        "keyword_density_per_1000_chars": round(density_per_1000, 2),
        "unique_keyword_ratio_per_100_chars": round(vocab_ratio_per_100, 3),
        "experiment_refs": experiment_refs,
        "experiment_readme_exists": readme_exists,
        "recommended_audience": "research" if tier in {"HIGH", "MEDIUM"} else "general",
    }


def build_report(feed: list[dict]) -> dict:
    candidates = []
    scanned_general = 0
    for item in feed:
        if item.get("audience") != "general":
            continue
        scanned_general += 1
        scored = score_item(item)
        if scored["tier"] == "LOW" and not scored["title_keyword_hits"] and len(scored["body_keyword_hits"]) < 2:
            continue
        candidates.append(scored)

    candidates.sort(key=lambda x: (-x["score"], x["id"] or ""))
    tiers = {"HIGH": [], "MEDIUM": [], "LOW": []}
    for item in candidates:
        tiers[item["tier"]].append(item)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_feed": str(FEED_PATH.relative_to(ROOT)),
        "summary": {
            "scanned_general_items": scanned_general,
            "flagged_candidates": len(candidates),
            "high_confidence": len(tiers["HIGH"]),
            "medium_confidence": len(tiers["MEDIUM"]),
            "low_confidence": len(tiers["LOW"]),
        },
        "candidates": candidates,
        "tiers": tiers,
    }


def render_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = [
        "# Audience Classification Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- scanned general items: `{summary['scanned_general_items']}`",
        f"- flagged candidates: `{summary['flagged_candidates']}`",
        f"- HIGH / MEDIUM / LOW: `{summary['high_confidence']}` / `{summary['medium_confidence']}` / `{summary['low_confidence']}`",
        "",
        "## Action rule",
        "",
        "- `HIGH`: 主線程 review 後可 batch reclassify `general -> research`",
        "- `MEDIUM`: 保留人工複核",
        "- `LOW`: 預設不動",
        "",
    ]
    for tier in ("HIGH", "MEDIUM", "LOW"):
        lines.append(f"## {tier}")
        lines.append("")
        items = report["tiers"][tier]
        if not items:
            lines.append("- None")
            lines.append("")
            continue
        for item in items[:80]:
            title_hits = ", ".join(item["title_keyword_hits"]) or "-"
            refs = ", ".join(item["experiment_refs"][:3]) or "-"
            lines.append(
                f"- `{item['id']}` score={item['score']} title_hits=[{title_hits}] "
                f"refs=[{refs}] readme={item['experiment_readme_exists']} :: {item['title']}"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit feed audience misclassification")
    parser.add_argument("--output-prefix", default="audience_audit_latest", help="report prefix under storage/ops/")
    args = parser.parse_args()

    feed = json.loads(FEED_PATH.read_text())
    report = build_report(feed)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORT_DIR / f"{args.output_prefix}.json"
    md_path = REPORT_DIR / f"{args.output_prefix}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    md_path.write_text(render_markdown(report) + "\n")

    print(f"[audience_audit] report_json={json_path}")
    print(f"[audience_audit] report_md={md_path}")
    print(f"[audience_audit] summary={report['summary']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
