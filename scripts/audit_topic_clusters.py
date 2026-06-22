#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "src"))

from volpred.topic_clusters import CLUSTER_HARD_CAPS, classify_topic_cluster, load_feed_items  # noqa: E402


def _warn_audit_topic_clusters(
    message: str,
    exc: Exception,
    *,
    item_id: object | None = None,
    value: object | None = None,
) -> None:
    print(
        "[audit_topic_clusters] WARN "
        f"{message} item_id={item_id!r} value={value!r} "
        f"error={type(exc).__name__}: {exc}",
        file=sys.stderr,
    )


def main() -> int:
    feed = load_feed_items()
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    counts: dict[str, int] = defaultdict(int)
    samples: dict[str, list[dict]] = defaultdict(list)
    total = 0

    for item in feed:
        if not isinstance(item, dict):
            continue
        if item.get("status") not in {"published", "draft", "scheduled"}:
            continue
        ts = item.get("published_at") or item.get("created_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError as exc:
            _warn_audit_topic_clusters(
                "feed timestamp parse failed; skipping item",
                exc,
                item_id=item.get("id"),
                value=ts,
            )
            continue
        if dt < cutoff:
            continue
        total += 1
        cluster = classify_topic_cluster(
            item.get("title", ""),
            item.get("tags") or [],
            item.get("description") or item.get("content") or "",
        )
        if not cluster:
            continue
        counts[cluster] += 1
        if len(samples[cluster]) < 5:
            samples[cluster].append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "published_at": ts,
                }
            )

    rows = []
    for cluster, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        rows.append(
            {
                "cluster": cluster,
                "count_90d": count,
                "ratio_90d": round((count / total), 4) if total else 0.0,
                "hard_cap_30d": CLUSTER_HARD_CAPS.get(cluster),
                "sample_titles": samples[cluster],
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 90,
        "total_articles": total,
        "clusters": rows,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
