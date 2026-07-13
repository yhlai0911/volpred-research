#!/usr/bin/env python3
"""Replace an article's 懶人包圖組 section with a set of generated PNGs.

Upload each PNG to Supabase article-images → swap (or append) the `## 懶人包圖組`
section in the article's feed.json content → single-article sync. Used to install
deterministic data-bound lazypack panels onto existing articles (manual / backfill path; the
async pipeline path is scripts/lazypack_async_render.py).

2026-07-02: core logic moved to volpred.publisher.lazypack_install (shared with
the compute_queue async worker; feed write now under the publisher_feed lock).
This CLI is a thin wrapper.

Usage:
  uv run python scripts/replace_lazypack_section.py \
    --article-id mile_9839822d --panel-dir /tmp/k1575_lz \
    --panel 1_framework:懶人包：文章框架 \
    --panel 2_method:懶人包：研究方法 \
    --panel 3_results:懶人包：主要發現

Each --panel is "<png-stem>:<alt-text>" (png read from <panel-dir>/<stem>.png).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from volpred.publisher.lazypack_install import (  # noqa: E402
    install_lazypack_section,
    upload_panels,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--article-id", required=True)
    ap.add_argument("--panel-dir", required=True)
    ap.add_argument("--panel", action="append", required=True,
                    help="<png-stem>:<alt-text>; repeatable, in display order")
    a = ap.parse_args()

    panels: list[tuple[str, str]] = []
    for i, spec in enumerate(a.panel, 1):
        stem, _, alt = spec.partition(":")
        panels.append((stem, alt or f"懶人包 {i}"))

    try:
        urls = upload_panels(a.article_id, a.panel_dir, panels)
    except (FileNotFoundError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for i, (url, _alt) in enumerate(urls, 1):
        print(f"uploaded panel {i}: {url}")

    try:
        result = install_lazypack_section(
            a.article_id,
            urls,
            storage_dir=ROOT / "storage",
            update_action="lazypack_deterministic_replace",
            update_summary=(
                "Replaced the lazypack section with deterministic, data-bound "
                "infographic panels."
            ),
        )
    except KeyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"feed.json updated: {a.article_id} lazypack section "
          f"{'replaced' if result['replaced'] else 'appended'} "
          f"({result['panels']} panels); sync_article: {result['synced']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
