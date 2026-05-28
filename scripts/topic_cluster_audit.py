#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "src"))

from volpred.topic_clusters import (  # noqa: E402
    CLUSTER_HARD_CAPS,
    DOMINANT_RATIO_LIMIT,
    recent_cluster_counts,
)


OUT_JSON = ROOT / "storage" / "ops" / "topic_cluster_audit_latest.json"


def main() -> int:
    counts, total = recent_cluster_counts(days=30)
    rows = []
    for cluster, count in counts.most_common():
        cap = CLUSTER_HARD_CAPS.get(cluster)
        rows.append(
            {
                "cluster": cluster,
                "count_30d": count,
                "ratio_30d": round((count / total), 4) if total else 0.0,
                "hard_cap_30d": cap,
                "over_cap": bool(cap is not None and count >= cap),
            }
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": 30,
        "total_articles": total,
        "dominant_ratio_limit": DOMINANT_RATIO_LIMIT,
        "clusters": rows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
