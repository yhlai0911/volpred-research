from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"

CLUSTER_VARIANTS: dict[str, list[str]] = {
    "vix": ["VIX", "VVIX", "VIX9D", "12/VIX", "恐慌指數", "VIX 條件槓桿"],
    "spy": ["SPY", "QQQ", "美股", "S&P 500", "標普"],
    "garch": ["GARCH", "GJR-GARCH", "GJR", "EGARCH", "EWMA", "GARCH-MIDAS", "MF-GJR"],
    "vt": ["VT", "VT策略", "Hybrid-VT", "波動率目標", "volatility targeting", "risk parity", "Risk-Parity"],
    "taiwan": ["0050.TW", "0056.TW", "00878", "00919", "00929", "00940", "2330.TW", "台股", "台灣市場", "TAIFEX", "台指期"],
}

CLUSTER_HARD_CAPS: dict[str, int] = {
    "vix": 15,
    "spy": 10,
    "garch": 10,
    "vt": 8,
    "taiwan": 8,
}

DEFAULT_CLUSTER_CAP = 6
DOMINANT_RATIO_LIMIT = 0.25


def _normalize(text: str) -> str:
    return (text or "").strip().lower()


def classify_topic_cluster(title: str, tags: list[str] | None = None, content: str | None = None) -> str | None:
    """Classify article into topic cluster by title + tags only.

    2026-05-27 fix: content scanning was too aggressive — daily_update.py
    boilerplate "市場快照: VIX 17.01, GARCH 11.3%" caused EVERY daily article
    to count toward vix+garch clusters → audit showed VIX=312/30d (vs 109
    when scanning only title). content arg accepted for API compatibility
    but ignored. Cluster = what the article is ABOUT (title/tags), not what
    keywords appear in body.
    """
    haystack_parts = [title or ""]
    if tags:
        haystack_parts.extend(str(t) for t in tags)
    haystack = " ".join(haystack_parts).lower()

    for cluster, variants in CLUSTER_VARIANTS.items():
        for variant in variants:
            if _normalize(variant) in haystack:
                return cluster
    return None


def cluster_cap(cluster: str | None) -> int:
    if not cluster:
        return DEFAULT_CLUSTER_CAP
    return CLUSTER_HARD_CAPS.get(cluster, DEFAULT_CLUSTER_CAP)


def load_feed_items(feed_path: Path = FEED_PATH) -> list[dict]:
    if not feed_path.exists():
        return []
    data = json.loads(feed_path.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("reports", [])


def recent_cluster_counts(
    *,
    days: int = 30,
    feed_path: Path = FEED_PATH,
    statuses: tuple[str, ...] = ("published", "draft", "scheduled"),
) -> tuple[Counter, int]:
    feed = load_feed_items(feed_path)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    counts: Counter[str] = Counter()
    total = 0
    for item in feed:
        if not isinstance(item, dict):
            continue
        if item.get("status") not in statuses:
            continue
        ts = item.get("published_at") or item.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt < cutoff:
            continue
        cluster = classify_topic_cluster(
            item.get("title", ""),
            item.get("tags") or [],
            item.get("description") or item.get("content") or "",
        )
        if cluster:
            counts[cluster] += 1
        total += 1
    return counts, total


def cluster_gate_status(cluster: str | None, *, days: int = 30, feed_path: Path = FEED_PATH) -> dict:
    counts, total = recent_cluster_counts(days=days, feed_path=feed_path)
    count = counts.get(cluster or "", 0) if cluster else 0
    cap = cluster_cap(cluster)
    ratio = (count / total) if total else 0.0
    return {
        "cluster": cluster,
        "count": count,
        "cap": cap,
        "total": total,
        "ratio": ratio,
        "blocked": bool(cluster and count >= cap),
        "dominant_ratio_breached": bool(cluster and ratio > DOMINANT_RATIO_LIMIT),
    }
