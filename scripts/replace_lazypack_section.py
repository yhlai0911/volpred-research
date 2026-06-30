#!/usr/bin/env python3
"""Replace an article's 懶人包圖組 section with a set of generated PNGs.

Upload each PNG to Supabase article-images → swap (or append) the `## 懶人包圖組`
section in the article's feed.json content → single-article sync. Used to install
codex-exec lazypack panels onto existing articles (e.g. redoing prose-dump
backfills from the deprecated backfill_lazypack_sections.py).

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
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from volpred.charts.article_charts import upload_chart  # noqa: E402
from volpred.publisher.publisher import has_lazypack_section  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--article-id", required=True)
    ap.add_argument("--panel-dir", required=True)
    ap.add_argument("--panel", action="append", required=True,
                    help="<png-stem>:<alt-text>; repeatable, in display order")
    a = ap.parse_args()

    panel_dir = Path(a.panel_dir)
    urls: list[tuple[str, str]] = []
    for i, spec in enumerate(a.panel, 1):
        stem, _, alt = spec.partition(":")
        src = panel_dir / f"{stem}.png"
        if not src.exists():
            print(f"MISSING panel PNG: {src}", file=sys.stderr)
            return 1
        # codex-tagged target name so Supabase serves the new image (no cache clash)
        dst = Path(f"/tmp/{a.article_id}_lazypack_codex_{i}.png")
        dst.write_bytes(src.read_bytes())
        url = upload_chart(str(dst))
        if not url or not url.startswith("http"):
            print(f"upload failed for {src}: {url}", file=sys.stderr)
            return 1
        urls.append((url, alt or f"懶人包 {i}"))
        print(f"uploaded panel {i}: {url}")

    new_section = "## 懶人包圖組\n\n" + "\n\n".join(f"![{alt}]({url})" for url, alt in urls) + "\n"

    feed_path = ROOT / "storage" / "reports" / "feed.json"
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    art = next((x for x in feed if isinstance(x, dict) and x.get("id") == a.article_id), None)
    if art is None:
        print(f"{a.article_id} not found in feed", file=sys.stderr)
        return 1
    content = art.get("content") or ""
    m = re.search(r"^#+\s*.*懶人包.*$", content, re.MULTILINE)
    if m:
        content = content[:m.start()].rstrip() + "\n\n" + new_section
    else:
        content = content.rstrip() + "\n\n" + new_section
    art["content"] = content
    # Stamp the content edit so the webpage shows "更新於 <date hh:mm>" (boss
    # 2026-07-01: 內容有改 → 網頁日期要對應改). Keeps published_at intact; the
    # frontend (ArticleReader) surfaces last_updated_at when it post-dates publish.
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    art["last_updated_at"] = now_iso
    errata = art.get("errata") if isinstance(art.get("errata"), dict) else {}
    errata["update_at"] = now_iso
    errata["update_action"] = "lazypack_codex_replace"
    errata["update_summary"] = "Replaced the lazypack section with codex-exec generated, data-bound infographic panels."
    hist = errata.get("update_history") if isinstance(errata.get("update_history"), list) else []
    hist.append({"at": now_iso, "action": "lazypack_codex_replace",
                 "summary": f"codex-exec lazypack ({len(urls)} panels)"})
    errata["update_history"] = hist
    art["errata"] = errata
    feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"feed.json updated: {a.article_id} lazypack section replaced ({len(urls)} panels)")
    print("has_lazypack_section:", has_lazypack_section(content))

    try:
        from supabase_sync import sync_article  # noqa: E402
        ok = sync_article(art, storage_dir=str(ROOT / "storage"))
        print("sync_article:", ok)
    except Exception as exc:  # noqa: BLE001
        print(f"sync_article failed (feed.json still updated): {type(exc).__name__}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
