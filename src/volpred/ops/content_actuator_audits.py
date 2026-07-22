"""Pure content-audit decisions shared by CLIs and the hourly alert actuator.

The command-line scripts under ``scripts/`` are presentation adapters. Keeping
the decisions here lets ``ops.alerts`` consume the exact same verdicts instead
of leaving useful audit conclusions stranded in terminal output.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from volpred.publisher.arc_dedup import ARC_SIGNATURE_SCHEMA_VERSION, arc_signature
from volpred.publisher.publisher import _ACADEMIC_KEYWORDS

from .diagnostics import warn

TITLE_KEYWORD_LABELS = {
    "GARCH", "GARCH-X", "HAR-RV", "Harvey", "Diebold-Mariano", "DM test",
    "QLIKE", "MLE", "bootstrap", "cointegration", "EGARCH", "MCS", "VaR",
}
EXPERIMENT_REF_PATTERN = re.compile(r"K\d+[A-Z0-9_]*", re.IGNORECASE)


def _article_text(item: dict) -> str:
    return str(item.get("content") or item.get("description") or "")


def _parse_dt(raw: object) -> datetime | None:
    if not raw:
        return None
    try:
        from dateutil.parser import parse as dtparse

        parsed = dtparse(str(raw))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception as exc:  # noqa: BLE001 - malformed feed rows must not abort patrol
        warn("arc_overmatch_parse_dt", "timestamp parse failed", err=str(exc), raw=str(raw)[:60])
        return None


def _signature(item: dict) -> dict:
    details = item.get("details") if isinstance(item.get("details"), dict) else {}
    stored = details.get("arc_signature") if isinstance(details, dict) else None
    if isinstance(stored, dict) and stored.get("schema_version") == ARC_SIGNATURE_SCHEMA_VERSION:
        return stored
    return arc_signature(str(item.get("title") or ""), _article_text(item))


def find_overmatches(
    feed: Iterable[dict], *, days: int = 30, now: datetime | None = None
) -> list[dict]:
    """Return recent dedup skips whose candidate/blocker narrative axes differ."""
    items = [item for item in feed if isinstance(item, dict)]
    by_id = {str(item.get("id") or ""): item for item in items}
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    candidates: list[dict] = []
    for item in items:
        details = item.get("details")
        if not isinstance(details, dict):
            continue
        blocker_id = str(details.get("release_arc_dedup_of") or "")
        skipped_at = _parse_dt(details.get("release_dedup_skipped_at"))
        if not blocker_id or not skipped_at or skipped_at < cutoff:
            continue
        blocker = by_id.get(blocker_id)
        if not blocker:
            continue
        cand_sig, block_sig = _signature(item), _signature(blocker)
        cand_axis = str(cand_sig.get("narrative_axis") or "unspecified")
        block_axis = str(block_sig.get("narrative_axis") or "unspecified")
        if "unspecified" in {cand_axis, block_axis} or cand_axis == block_axis:
            continue
        cand_entities = set(cand_sig.get("entities") or [])
        block_entities = set(block_sig.get("entities") or [])
        candidates.append({
            "candidate_id": item.get("id"), "candidate_title": item.get("title"),
            "blocked_by_id": blocker.get("id"), "blocked_by_title": blocker.get("title"),
            "release_dedup_skipped_at": skipped_at.isoformat(),
            "candidate_narrative_axis": cand_axis, "blocked_by_narrative_axis": block_axis,
            "shared_entities": sorted(cand_entities & block_entities),
            "candidate_entities": sorted(cand_entities), "blocked_by_entities": sorted(block_entities),
            "candidate_mechanisms": cand_sig.get("mechanisms") or [],
            "blocked_by_mechanisms": block_sig.get("mechanisms") or [],
            "recommendation": "review_dup_waiver_or_fresh_arc_rewrite",
        })
    return candidates


def _extract_experiment_refs(item: dict) -> list[str]:
    refs: list[str] = []
    details = item.get("details") or {}
    if isinstance(details, dict):
        refs.extend(ref.upper() for ref in details.get("experiment_refs") or [] if isinstance(ref, str))
    for source in (item.get("title") or "", item.get("description") or "", item.get("content") or ""):
        refs.extend(match.upper() for match in EXPERIMENT_REF_PATTERN.findall(str(source)))
    return list(dict.fromkeys(refs))


def _keyword_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern, label in _ACADEMIC_KEYWORDS:
        if label not in hits and pattern.search(text):
            hits.append(label)
    return hits


def score_item(item: dict, *, repo_root: Path) -> dict:
    """Score whether a nominally-general item contains research-grade language."""
    title = str(item.get("title") or "")
    description = str(item.get("description") or item.get("content") or "")
    combined = " ".join([title, description, " ".join(item.get("tags") or [])])
    refs = _extract_experiment_refs(item)
    title_hits = [hit for hit in _keyword_hits(title) if hit in TITLE_KEYWORD_LABELS]
    body_hits = _keyword_hits(combined)
    body_chars, unique_hits = len(description), len(set(body_hits))
    density = (len(body_hits) / max(body_chars, 1)) * 1000
    vocab_ratio = (unique_hits / max(body_chars, 1)) * 100
    readme_exists = any((repo_root / "experiments" / ref.lower() / "README.md").exists() for ref in refs)
    score = min(len(title_hits) * 18, 36) + min(unique_hits * 8, 32)
    score += 14 if density >= 6 else 8 if density >= 3 else 0
    score += 8 if body_chars >= 2500 else 4 if body_chars >= 1600 else 0
    score += 10 if readme_exists else 0
    tier = "HIGH" if score >= 62 else "MEDIUM" if score >= 38 else "LOW"
    return {
        "id": item.get("id"), "title": title, "audience": item.get("audience"),
        "status": item.get("status"), "published_at": item.get("published_at") or item.get("created_at"),
        "score": score, "tier": tier, "title_keyword_hits": title_hits,
        "body_keyword_hits": body_hits, "body_chars": body_chars,
        "keyword_density_per_1000_chars": round(density, 2),
        "unique_keyword_ratio_per_100_chars": round(vocab_ratio, 3),
        "experiment_refs": refs, "experiment_readme_exists": readme_exists,
        "recommended_audience": "research" if tier in {"HIGH", "MEDIUM"} else "general",
    }


def build_audience_report(feed: list[dict], *, repo_root: Path, source_feed: str) -> dict:
    candidates, scanned_general = [], 0
    for item in feed:
        if item.get("audience") != "general":
            continue
        scanned_general += 1
        scored = score_item(item, repo_root=repo_root)
        if scored["tier"] == "LOW" and not scored["title_keyword_hits"] and len(scored["body_keyword_hits"]) < 2:
            continue
        candidates.append(scored)
    candidates.sort(key=lambda x: (-x["score"], x["id"] or ""))
    tiers = {tier: [x for x in candidates if x["tier"] == tier] for tier in ("HIGH", "MEDIUM", "LOW")}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "source_feed": source_feed,
        "summary": {"scanned_general_items": scanned_general, "flagged_candidates": len(candidates),
                    "high_confidence": len(tiers["HIGH"]), "medium_confidence": len(tiers["MEDIUM"]),
                    "low_confidence": len(tiers["LOW"])},
        "candidates": candidates, "tiers": tiers,
    }


def render_audience_markdown(report: dict) -> str:
    summary = report["summary"]
    lines = ["# Audience Classification Audit", "", f"- generated_at: `{report['generated_at']}`",
             f"- scanned general items: `{summary['scanned_general_items']}`",
             f"- flagged candidates: `{summary['flagged_candidates']}`",
             f"- HIGH / MEDIUM / LOW: `{summary['high_confidence']}` / `{summary['medium_confidence']}` / `{summary['low_confidence']}`",
             "", "## Action rule", "", "- `HIGH`: 主線程 review 後可 batch reclassify `general -> research`",
             "- `MEDIUM`: 保留人工複核", "- `LOW`: 預設不動", ""]
    for tier in ("HIGH", "MEDIUM", "LOW"):
        lines.extend([f"## {tier}", ""])
        if not report["tiers"][tier]:
            lines.extend(["- None", ""])
            continue
        for item in report["tiers"][tier][:80]:
            title_hits = ", ".join(item["title_keyword_hits"]) or "-"
            refs = ", ".join(item["experiment_refs"][:3]) or "-"
            lines.append(f"- `{item['id']}` score={item['score']} title_hits=[{title_hits}] refs=[{refs}] readme={item['experiment_readme_exists']} :: {item['title']}")
        lines.append("")
    return "\n".join(lines)
