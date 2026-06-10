#!/usr/bin/env python3
"""Pre-write narrative-arc duplicate check for article agents.

Usage:
    uv run python scripts/check_arc_dedup.py --title "銅博士的波動率版本" \
        --text-file /tmp/draft_or_results_summary.md
    uv run python scripts/check_arc_dedup.py --k-id k1449   # reads experiment README+results

Exit codes: 0 = no arc duplicate, 1 = duplicate found (do NOT write/publish
without a deliberate new angle + details['dup_waiver']), 2 = usage error.

Why this exists (2026-06-10 K1449/K1091 incident): title-similarity dedup is
blind to same-story-different-shell duplicates. The publisher now hard-blocks
arc duplicates at publish time, but running this BEFORE writing saves the whole
wasted article. Mandated in the hourly dispatch prompt for daily_article /
gen_article tasks.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from volpred.publisher.arc_dedup import (  # noqa: E402
    classify_conclusion,
    extract_entities,
    find_arc_duplicates,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--title", default="", help="planned article title / topic")
    ap.add_argument("--text-file", help="draft / results summary file to scan")
    ap.add_argument("--k-id", help="experiment id (reads experiments/<k>/README.md + results)")
    ap.add_argument("--days", type=int, default=90)
    args = ap.parse_args()

    text = ""
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8", errors="replace")
    if args.k_id:
        kdir = ROOT / "experiments" / args.k_id.lower()
        for name in ("README.md", f"{args.k_id.lower()}_results.json"):
            f = kdir / name
            if f.exists():
                text += "\n" + f.read_text(encoding="utf-8", errors="replace")
        if not text:
            print(f"ERROR: no readable files under {kdir}", file=sys.stderr)
            return 2
    if not (args.title or text):
        ap.print_help()
        return 2

    feed = json.loads((ROOT / "storage" / "reports" / "feed.json").read_text(encoding="utf-8"))
    full = f"{args.title}\n{text}"
    report = {
        "entities": sorted(extract_entities(full)),
        "conclusion_class": classify_conclusion(full),
    }
    dups = find_arc_duplicates(args.title, text, feed, days=args.days)
    report["arc_duplicates"] = dups
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if dups:
        print(
            f"\n🚫 ARC DUPLICATE — {len(dups)} existing article(s) tell the same "
            f"story. Do not write this piece without a genuinely new angle "
            f"(and details['dup_waiver'] at publish).",
            file=sys.stderr,
        )
        return 1
    print("\n✅ no arc duplicate in window", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
