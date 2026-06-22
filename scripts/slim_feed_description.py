#!/usr/bin/env python3
"""Slim bloated ``description`` fields in feed.json down to short excerpts.

2026-06-23 feed.json bloat fix. The publisher historically stored the full
article markdown body in BOTH ``content`` (canonical) and ``description``
(redundant fallback that never fires because content is always populated). The
duplicate body was ~5.8MB of a 23MB feed.json. publisher.py:_make_excerpt now
stores a short excerpt going forward; this script backfills existing entries.

What it does (and does NOT do):
  - Rewrites ``description`` to ``_make_excerpt(content)`` ONLY for entries whose
    description is bloated (len > THRESHOLD), i.e. clearly a full-body clone.
  - NEVER touches ``content`` (the canonical full body / research artifact).
  - NEVER touches short hand-authored descriptions (len <= THRESHOLD).
  - Deterministic: same content always yields the same excerpt.

This is legitimate cleanup of a *derived/redundant* field (like recalc_metrics),
not hand-editing historical research data. Run with --apply to write; default is
a dry-run report.

Usage:
    uv run python scripts/slim_feed_description.py            # dry-run
    uv run python scripts/slim_feed_description.py --apply    # write changes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Bloat threshold: any description longer than this is a full-body clone, not a
# proper excerpt (the publisher caps excerpts at 300 chars). 400 leaves margin.
BLOAT_THRESHOLD = 400


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='write changes (default: dry-run)')
    parser.add_argument('--feed', default='storage/reports/feed.json')
    args = parser.parse_args()

    # Import the canonical excerpt helper so backfill == publish-time behavior.
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / 'src'))
    from volpred.publisher.publisher import _make_excerpt  # noqa: E402

    feed_path = Path(args.feed)
    feed = json.loads(feed_path.read_text())
    orig_bytes = len(feed_path.read_bytes())

    bloated = []
    saved = 0
    for entry in feed:
        desc = entry.get('description') or ''
        if len(desc) <= BLOAT_THRESHOLD:
            continue
        # Prefer regenerating from canonical content; fall back to the desc body.
        body = entry.get('content') or desc
        new_desc = _make_excerpt(body)
        bloated.append((entry.get('id'), len(desc), len(new_desc)))
        saved += len(desc) - len(new_desc)
        if args.apply:
            entry['description'] = new_desc

    print(f"feed.json entries: {len(feed)}")
    print(f"bloated descriptions (> {BLOAT_THRESHOLD} chars): {len(bloated)}")
    print(f"approx chars reclaimed (description only): {saved:,} (~{saved / 1024 / 1024:.2f} MB raw text)")
    if bloated:
        print("\ntop 10 by original description length:")
        for _id, old, new in sorted(bloated, key=lambda x: -x[1])[:10]:
            print(f"  {_id}: {old:>8,} -> {new:>4} chars")

    if args.apply:
        # Match publisher's json.dump params exactly (indent=2, ensure_ascii=False,
        # default=str) so the backfill diff is minimal and format-stable.
        feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2, default=str))
        new_bytes = len(feed_path.read_bytes())
        print(
            f"\nAPPLIED. feed.json: {orig_bytes / 1024 / 1024:.1f}MB -> "
            f"{new_bytes / 1024 / 1024:.1f}MB "
            f"({(orig_bytes - new_bytes) / 1024 / 1024:.1f}MB saved)"
        )
    else:
        print("\nDRY-RUN. Re-run with --apply to write changes.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
