#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.topic_clusters import DOMINANT_RATIO_LIMIT, recent_cluster_counts  # noqa: E402


def main() -> int:
    counts, total = recent_cluster_counts(days=30)
    if total == 0:
        print("PASS — no recent articles")
        return 0
    cluster, count = counts.most_common(1)[0]
    ratio = count / total
    if ratio > DOMINANT_RATIO_LIMIT:
        print(
            json.dumps(
                {
                    "status": "fail",
                    "cluster": cluster,
                    "count_30d": count,
                    "total_30d": total,
                    "ratio_30d": round(ratio, 4),
                    "limit": DOMINANT_RATIO_LIMIT,
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(
        f"PASS — dominant cluster {cluster} ratio {ratio:.4f} <= {DOMINANT_RATIO_LIMIT:.2f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
