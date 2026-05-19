"""Post-publish live verification gate.

Three-Strike structural fix (2026-05-19):
5 articles this session got `status='published'` locally + Supabase-synced, but
no code verified the public URL was actually reachable. Downstream automation
(FB push) used a wrong URL template (`/article/{id}` 404) since no one held
the canonical URL builder.

This module owns the canonical public URL and the verify-after-publish gate.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Callable
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen

# Canonical public URL pattern. /v3/reports/{id} is the live route (confirmed
# 2026-05-19). /article/{id} returns 404. /reports/{id} also resolves 200 but
# v3 is the canonical reader path used everywhere in the frontend (search the
# repo for `href={`/v3/reports/`` — 19 matches; /reports/ links are legacy
# back-compat only).
PUBLIC_BASE_URL = "https://volpred.zeabur.app"
PUBLIC_PATH_TEMPLATE = "/v3/reports/{mile_id}"


def public_url(mile_id: str) -> str:
    """Build the canonical public URL for a feed entry id."""
    return PUBLIC_BASE_URL + PUBLIC_PATH_TEMPLATE.format(mile_id=mile_id)


def _http_status(url: str, *, timeout_s: float = 10.0) -> int:
    """Return HTTP status code for url, or 0 on transport error."""
    try:
        req = Request(url, method="GET", headers={"User-Agent": "volpred-live-verify/1.0"})
        with urlopen(req, timeout=timeout_s) as resp:
            return int(getattr(resp, "status", 200) or 200)
    except HTTPError as exc:
        return int(exc.code)
    except (URLError, TimeoutError, OSError):
        return 0


def verify_article_live(
    mile_id: str,
    *,
    max_wait_s: int = 120,
    poll_interval_s: int = 10,
    _http_check: Callable[[str], int] | None = None,
    _sleep: Callable[[float], None] | None = None,
    _now: Callable[[], float] | None = None,
) -> bool:
    """Poll the public URL until it returns 200 or timeout.

    Returns True on first HTTP 200, False if timeout elapses without 200.

    The `_http_check`, `_sleep`, `_now` hooks exist for deterministic testing.
    """
    if not mile_id or not isinstance(mile_id, str):
        return False
    url = public_url(mile_id)
    http_check = _http_check or _http_status
    sleeper = _sleep or time.sleep
    clock = _now or time.monotonic

    deadline = clock() + max_wait_s
    attempt = 0
    while True:
        attempt += 1
        status = http_check(url)
        if status == 200:
            return True
        if clock() >= deadline:
            return False
        sleeper(poll_interval_s)


def stamp_verified(item: dict, *, verified: bool) -> dict:
    """Mutate a feed entry with verify outcome.

    On success: stamp `verified_live_at=ISO`, clear `live_verify_failed`.
    On failure: set `live_verify_failed=True`, do NOT stamp `verified_live_at`.
    """
    if verified:
        item["verified_live_at"] = datetime.now(timezone.utc).isoformat()
        if "live_verify_failed" in item:
            item["live_verify_failed"] = False
    else:
        item["live_verify_failed"] = True
    return item


def emit_verify_alert(mile_id: str, title: str | None, *, storage_dir: str = "storage") -> None:
    """Send a warn alert when live verify fails. Best-effort; never raises."""
    try:
        from volpred.ops.alerts import send_alert

        alert_title = f"publish_pending_live: {mile_id}"
        body = (
            "## 觸發條件\n"
            f"Article `{mile_id}` 已 flip status=published 並 sync 至 Supabase，"
            f"但 public URL {public_url(mile_id)} 在 verify window 內未回 HTTP 200。\n"
            f"標題：{title or '(unknown)'}\n"
            f"已標 `live_verify_failed=True` 於 feed.json（未 stamp verified_live_at）。\n\n"
            "## 影響\n"
            "Mission #1（內容）+ #5（流量）：讀者點連結會 404 / 顯示舊快取；"
            "下游 FB / email 推播會帶到 dead link，傷信任。\n\n"
            "## 建議行動\n"
            f"1. 手動 `curl -I {public_url(mile_id)}` 確認狀態\n"
            "2. 若仍 404：查 Zeabur build log / Supabase RLS / frontend revalidate\n"
            "3. 修好後 `uv run python scripts/backfill_verified_live.py --id "
            f"{mile_id}` 補 stamp\n"
            "4. 根因若在 publish pipeline，補 regression test 於 "
            "`tests/test_live_verify.py`"
        )
        send_alert(level="warn", title=alert_title, body=body, storage_dir=storage_dir)
    except Exception as exc:  # pragma: no cover — alert failures must not block publish
        print(f"  [live_verify] alert send failed for {mile_id}: {exc}")
