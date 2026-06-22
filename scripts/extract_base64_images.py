#!/usr/bin/env python3
"""Extract inline base64 data-URI images from feed.json → Supabase URLs.

2026-06-23 feed.json bloat fix (part 2). One-time Codex publish scripts embedded
charts as ``![alt](data:image/png;base64,...)`` instead of uploading to the
Supabase article-images bucket. 10 entries carried ~1.84MB of inline base64
(one entry, mile_e5f33cfa, held a single 862KB PNG). The publisher now has a
canonical-write-site gate (publisher._extract_base64_images, wired into
_append_to_feed) so this can't recur; this script repairs the existing rows.

For each affected entry it: decodes each data URI → uploads the PNG to
article-images → rewrites the markdown to the public URL (reusing the SAME
publisher helper so behavior matches publish-time), then re-syncs the entry to
Supabase so the live article page serves the URL image instead of base64.

content stays the canonical body (only the image encoding changes from inline
base64 to a URL reference); this is process-consistent cleanup, not data fixing.

Usage:
    uv run python scripts/extract_base64_images.py            # dry-run (list only)
    uv run python scripts/extract_base64_images.py --apply    # upload + rewrite + sync
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='upload + rewrite + sync (default: dry-run)')
    parser.add_argument('--feed', default='storage/reports/feed.json')
    parser.add_argument('--no-sync', action='store_true', help='skip Supabase re-sync after rewrite')
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / 'src'))
    sys.path.insert(0, str(repo_root))
    from volpred.publisher.publisher import _extract_base64_images, _DATA_URI_IMG_RE  # noqa: E402

    feed_path = Path(args.feed)
    feed = json.loads(feed_path.read_text())
    orig_bytes = len(feed_path.read_bytes())

    affected = []
    for entry in feed:
        content = entry.get('content') or ''
        if 'data:image' not in content:
            continue
        n_imgs = len(_DATA_URI_IMG_RE.findall(content))
        affected.append((entry, n_imgs, len(content)))

    print(f"feed entries with inline base64 images: {len(affected)}")
    for entry, n_imgs, clen in sorted(affected, key=lambda x: -x[2]):
        print(f"  {entry.get('id')}: {n_imgs} image(s), content {clen // 1024}KB  | {(entry.get('title') or '')[:34]}")

    if not args.apply:
        print("\nDRY-RUN. Re-run with --apply to upload + rewrite + sync.")
        return 0

    # Apply: rewrite each affected entry's content via the publisher helper
    # (decodes → uploads → swaps in the URL). Network upload happens here.
    changed_ids = []
    for entry, _n, _clen in affected:
        article_id = entry.get('id', 'unknown')
        before = entry['content']
        after = _extract_base64_images(before, article_id)
        if after != before and 'data:image' not in after:
            entry['content'] = after
            changed_ids.append(article_id)
        elif 'data:image' in after:
            print(f"  WARN {article_id}: still has data:image after extract (upload likely failed) — left unchanged")

    feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2, default=str))
    new_bytes = len(feed_path.read_bytes())
    print(
        f"\nREWROTE feed.json: {orig_bytes / 1024 / 1024:.1f}MB -> {new_bytes / 1024 / 1024:.1f}MB "
        f"({(orig_bytes - new_bytes) / 1024 / 1024:.1f}MB saved); {len(changed_ids)} entries updated"
    )

    if changed_ids and not args.no_sync:
        import scripts.supabase_sync as supabase_sync  # noqa: E402
        by_id = {e.get('id'): e for e in feed}
        ok = 0
        for aid in changed_ids:
            try:
                if supabase_sync.sync_article(by_id[aid]):
                    ok += 1
                else:
                    print(f"  WARN Supabase sync returned False for {aid}")
            except Exception as exc:
                print(f"  WARN Supabase sync raised for {aid}: {exc}")
        print(f"Supabase re-sync: {ok}/{len(changed_ids)} entries")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
