from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sys


ROOT = Path(__file__).resolve().parents[2]
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"

CLUSTER_VARIANTS: dict[str, list[str]] = {
    "vix": ["VIX", "VVIX", "VIX9D", "12/VIX", "恐慌指數", "VIX 條件槓桿"],
    "factor_etf": [
        "MTUM",
        "QUAL",
        "USMV",
        "VLUE",
        "SPLV",
        "SPHQ",
        "USHY",
        "因子 ETF",
        "低波動 ETF",
        "smart beta",
        "smart-beta",
        "美股 ETF",
    ],
    "spy": ["SPY", "QQQ", "美股", "S&P 500", "標普"],
    "garch": ["GARCH", "GJR-GARCH", "GJR", "EGARCH", "EWMA", "GARCH-MIDAS", "MF-GJR"],
    "vt": ["VT", "VT策略", "Hybrid-VT", "波動率目標", "volatility targeting", "risk parity", "Risk-Parity"],
    "taiwan": ["0050.TW", "0056.TW", "00878", "00919", "00929", "00940", "2330.TW", "台股", "台灣市場", "TAIFEX", "台指期"],
}

CLUSTER_HARD_CAPS: dict[str, int] = {
    "vix": 15,
    "spy": 10,
    "factor_etf": 6,
    "garch": 10,
    "vt": 8,
    "taiwan": 8,
}

DEFAULT_CLUSTER_CAP = 6
DOMINANT_RATIO_LIMIT = 0.25

# 2026-06-29: soft cap for timely / topic-bound types (event_article,
# trending_repost, member_qa, daily_*). They are exempt from the HARD cap
# (cluster_gate_status.blocked) because their repetition is by design — a
# trending take responds to a live event; the daily VIX bulletin is templated.
# But "exempt" was a free pass that let vix grow to 92/15 = 6.1x and spy to
# 83/10 = 8.3x in 30d (alerts.py cluster_cap_drift, boss escalation 2026-06-29).
# So even timely types now stop at `hard_cap * SOFT_CAP_MULTIPLIER`. Real events
# can still override via `details['cluster_waiver']='<reason>'` (e.g. an FOMC
# day) — same waiver mechanism the hard cap already supports.
SOFT_CAP_MULTIPLIER = 2.5


def _warn_topic_clusters(
    message: str,
    feed_path: Path,
    exc: Exception,
    *,
    item_id: object | None = None,
    value: object | None = None,
) -> None:
    print(
        "[topic_clusters] WARN "
        f"{message} path={feed_path} item_id={item_id!r} "
        f"value={value!r} error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


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
        except ValueError as exc:
            _warn_topic_clusters(
                "feed timestamp parse failed; skipping item",
                feed_path,
                exc,
                item_id=item.get("id"),
                value=ts,
            )
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
    soft_cap = int(cap * SOFT_CAP_MULTIPLIER)
    return {
        "cluster": cluster,
        "count": count,
        "cap": cap,
        "soft_cap": soft_cap,
        "soft_cap_multiplier": SOFT_CAP_MULTIPLIER,
        "total": total,
        "ratio": ratio,
        "blocked": bool(cluster and count >= cap),
        "soft_blocked": bool(cluster and count >= soft_cap),
        "dominant_ratio_breached": bool(cluster and ratio > DOMINANT_RATIO_LIMIT),
    }


def cluster_soft_cap(cluster: str | None) -> int:
    """Hard cap × SOFT_CAP_MULTIPLIER, the ceiling that even timely / topic-bound
    types must respect (FOMC / CPI / trending / daily_digest etc).

    Hard cap blocks discretionary general/research; soft cap blocks everything
    including timely — except an explicit ``details['cluster_waiver']`` set by
    the caller for genuinely critical real-world events.
    """
    return int(cluster_cap(cluster) * SOFT_CAP_MULTIPLIER)
