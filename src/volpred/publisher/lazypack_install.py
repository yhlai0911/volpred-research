"""Install a 懶人包圖組 (lazypack) section onto an existing feed article.

Single owner for the "upload panel PNGs → append/replace `## 懶人包圖組`
section → stamp last_updated_at/errata → single-article Supabase sync" flow,
shared by:

  - scripts/replace_lazypack_section.py      (manual / backfill CLI)
  - scripts/lazypack_async_render.py `run`   (compute_queue async worker path,
                                              2026-07-02 error_log 15:15 #4)

Extracted 2026-07-02 from replace_lazypack_section.py so the async pipeline
does not fork a second copy of the feed-mutation logic. One behaviour fix over
the standalone script: the feed read-modify-write now runs under
shared_state_lock("publisher_feed") — the old script wrote feed.json unlocked,
racing release_pool / publisher writers (same lock namespace they use).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from volpred.canonical_write import guard_canonical_write

_LAZYPACK_HEADING_RE = re.compile(r"^#+\s*.*懶人包.*$", re.MULTILINE)


def upload_panels(
    article_id: str,
    panel_dir: str | Path,
    panels: list[tuple[str, str]],
    *,
    uploader: Callable[[str], str] | None = None,
) -> list[tuple[str, str]]:
    """Upload each (png-stem, alt-text) panel PNG; return [(public_url, alt)].

    Raises FileNotFoundError / RuntimeError on any missing panel or failed
    upload — callers (compute worker job) must treat that as job failure, not
    swallow it (no-silent-fallback.md).
    """
    if uploader is None:
        from volpred.charts.article_charts import upload_chart

        uploader = upload_chart
    panel_dir = Path(panel_dir)
    urls: list[tuple[str, str]] = []
    for i, (stem, alt) in enumerate(panels, 1):
        src = panel_dir / f"{stem}.png"
        if not src.exists():
            raise FileNotFoundError(f"panel PNG missing: {src}")
        raw = src.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()[:16]
        # Content-address the upload object. Re-rendering a changed panel now
        # produces a new URL instead of relying on CDN cache invalidation for an
        # upserted fixed key; identical bytes intentionally deduplicate.
        dst = Path(f"/tmp/{article_id}_lazypack_{i}_{digest}.png")
        dst.write_bytes(raw)
        try:
            url = uploader(str(dst))
        finally:
            dst.unlink(missing_ok=True)
        if not url or not str(url).startswith("http"):
            raise RuntimeError(f"upload failed for {src}: {url!r}")
        urls.append((str(url), alt or f"懶人包 {i}"))
    return urls


def install_lazypack_section(
    article_id: str,
    urls: list[tuple[str, str]],
    *,
    storage_dir: str | Path = "storage",
    update_action: str = "lazypack_install",
    update_summary: str | None = None,
    sync: bool = True,
) -> dict:
    """Append (or replace) the article's `## 懶人包圖組` section with `urls`.

    urls: [(public_png_url, alt_text)] in display order.
    Returns {"article_id", "panels", "replaced", "status", "synced"}.
    Raises KeyError if the article id is not in feed.json.
    """
    from volpred.ops.shared_lock import shared_state_lock

    storage = Path(storage_dir)
    feed_path = storage / "reports" / "feed.json"
    new_section = (
        "## 懶人包圖組\n\n"
        + "\n\n".join(f"![{alt}]({url})" for url, alt in urls)
        + "\n"
    )

    with shared_state_lock("publisher_feed", storage_dir=str(storage)):
        feed = json.loads(feed_path.read_text(encoding="utf-8"))
        art = next(
            (x for x in feed if isinstance(x, dict) and x.get("id") == article_id),
            None,
        )
        if art is None:
            raise KeyError(f"{article_id} not found in {feed_path}")
        content = art.get("content") or ""
        m = _LAZYPACK_HEADING_RE.search(content)
        replaced = bool(m)
        if m:
            content = content[: m.start()].rstrip() + "\n\n" + new_section
        else:
            content = content.rstrip() + "\n\n" + new_section
        art["content"] = content
        # Stamp the content edit so the webpage shows "更新於 <date hh:mm>" (boss
        # 2026-07-01: 內容有改 → 網頁日期要對應改). published_at stays intact.
        now_iso = datetime.now(timezone.utc).isoformat()
        art["last_updated_at"] = now_iso
        errata = art.get("errata") if isinstance(art.get("errata"), dict) else {}
        errata["update_at"] = now_iso
        errata["update_action"] = update_action
        errata["update_summary"] = update_summary or (
            f"Installed deterministic data-bound lazypack section ({len(urls)} panels)."
        )
        hist = (
            errata.get("update_history")
            if isinstance(errata.get("update_history"), list)
            else []
        )
        hist.append(
            {
                "at": now_iso,
                "action": update_action,
                "summary": f"lazypack section installed ({len(urls)} panels)",
            }
        )
        errata["update_history"] = hist
        art["errata"] = errata
        guard_canonical_write(feed_path)
        feed_path.write_text(
            json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    synced: bool | None = None
    if sync:
        try:
            from scripts.supabase_sync import sync_article

            synced = bool(sync_article(art, storage_dir=str(storage)))
        except Exception as exc:  # log-and-continue: feed.json already updated
            from volpred.ops.diagnostics import warn

            warn(
                "lazypack_install",
                "sync_article failed after feed update",
                article_id=article_id,
                err=f"{type(exc).__name__}: {exc}",
            )
            synced = False

    return {
        "article_id": article_id,
        "panels": len(urls),
        "replaced": replaced,
        "status": str(art.get("status") or ""),
        "synced": synced,
    }
