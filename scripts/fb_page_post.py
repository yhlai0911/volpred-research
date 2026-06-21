#!/usr/bin/env python3
"""Withdrawn FB Page Graph API publisher.

This file is intentionally kept as a fail-fast historical stub. The Page /
Graph API route was permanently rejected on 2026-06-03 because VolPred FB
distribution must use the owner's personal account via an interactive Chrome
session. See docs/fb_pipeline_permanent_fix.md.

Any CLI or direct function call exits before reading FB_PAGE_* credentials or
attempting a Graph API request.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GRAPH_VERSION = "v21.0"
FEED_PATH = ROOT / "storage" / "reports" / "feed.json"
SITE = "https://volpred.zeabur.app"
# fb_post_status values that mean "still needs posting"
PENDING_STATES = {"awaiting_interactive_session", "pending_manual", "pending_manual_post", "pending"}
WITHDRAWN_MESSAGE = (
    "FB Page Graph API path is permanently withdrawn. Use the personal-account "
    "Claude-in-Chrome workflow; see docs/fb_pipeline_permanent_fix.md."
)


def _raise_withdrawn() -> None:
    raise SystemExit(WITHDRAWN_MESSAGE)


def _load_env() -> None:
    """Load FB_* from .env / .env.local if not already in environment."""
    for fname in (".env", ".env.local", "frontend-v2-fix/.env.production"):
        p = ROOT / fname
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k.startswith("FB_") and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")


def _creds() -> tuple[str, str]:
    _raise_withdrawn()
    _load_env()
    page_id = os.environ.get("FB_PAGE_ID", "").strip()
    token = os.environ.get("FB_PAGE_ACCESS_TOKEN", "").strip()
    if not page_id or not token:
        raise SystemExit(
            "Missing FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN. Set them in .env (owner provides "
            "the Page id + a long-lived Page access token; this script never hardcodes them)."
        )
    return page_id, token


def _graph_post(path: str, params: dict) -> dict:
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{path}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def post_article(message: str, link: str | None, token: str, page_id: str) -> dict:
    """Create the Page post (body only), then add the link as the first comment."""
    _raise_withdrawn()
    post = _graph_post(f"{page_id}/feed", {"message": message, "access_token": token})
    post_id = post.get("id")
    comment = None
    if link and post_id:
        comment = _graph_post(
            f"{post_id}/comments",
            {"message": f"完整的數字跟圖表在這 👉 {link}", "access_token": token},
        )
    return {"post_id": post_id, "post": post, "comment": comment}


def _load_feed() -> list:
    return json.loads(FEED_PATH.read_text(encoding="utf-8"))


def _article(feed: list, mile_id: str) -> dict | None:
    return next((a for a in feed if isinstance(a, dict) and a.get("id") == mile_id), None)


def _fb_message_for(art: dict) -> str:
    """Use the article's prepared FB copy if present, else a short fallback hook."""
    det = art.get("details") or {}
    if det.get("fb_post_text"):
        return str(det["fb_post_text"]).strip()
    # fallback: title + 1-line — better to set details.fb_post_text upstream
    return str(art.get("title") or "").strip()


def _mark_success(mile_id: str, post_url: str, comment_link: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    import subprocess
    subprocess.run(
        ["uv", "run", "python", "scripts/mark_fb_post_status.py",
         "--mile-id", mile_id, "--status", "success",
         "--note", f"FB Page Graph API auto-post; {post_url}"],
        cwd=str(ROOT), check=False,
    )
    feed = _load_feed()
    for a in feed:
        if isinstance(a, dict) and a.get("id") == mile_id:
            det = a.setdefault("details", {})
            det["fb_post_url"] = post_url
            det["fb_comment_url"] = comment_link
            det["fb_post_timestamp"] = ts
            det["fb_post_channel"] = "page_graph_api"
            break
    FEED_PATH.write_text(json.dumps(feed, ensure_ascii=False, indent=2), encoding="utf-8")


def _post_one(mile_id: str, dry_run: bool) -> bool:
    _raise_withdrawn()
    feed = _load_feed()
    art = _article(feed, mile_id)
    if not art:
        print(f"  {mile_id}: not in feed — skip")
        return False
    message = _fb_message_for(art)
    link = f"{SITE}/v3/reports/{mile_id}"
    if dry_run:
        print(f"  [dry-run] {mile_id}\n    message: {message[:80]}...\n    link(comment): {link}")
        return True
    page_id, token = _creds()
    res = post_article(message, link, token, page_id)
    post_id = res.get("post_id")
    if not post_id:
        print(f"  {mile_id}: post FAILED — {res}")
        return False
    post_url = f"https://www.facebook.com/{post_id}"
    _mark_success(mile_id, post_url, link)
    print(f"  {mile_id}: posted ✓ {post_url}")
    return True


def main() -> int:
    _raise_withdrawn()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mile-id")
    ap.add_argument("--message")
    ap.add_argument("--link")
    ap.add_argument("--drain", action="store_true", help="post all FB-pending articles in feed")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.drain:
        feed = _load_feed()
        pending = [a["id"] for a in feed if isinstance(a, dict)
                   and a.get("fb_post_status") in PENDING_STATES and a.get("status") == "published"]
        print(f"[drain] {len(pending)} FB-pending: {pending}")
        ok = sum(1 for mid in pending if _post_one(mid, args.dry_run))
        print(f"[drain] posted {ok}/{len(pending)}")
        return 0

    if args.message:
        if args.dry_run:
            print(f"[dry-run] message: {args.message[:80]}\n  link(comment): {args.link}")
            return 0
        page_id, token = _creds()
        res = post_article(args.message, args.link, token, page_id)
        print(json.dumps(res, ensure_ascii=False, indent=2)[:600])
        return 0

    if args.mile_id:
        return 0 if _post_one(args.mile_id, args.dry_run) else 1

    ap.error("need --mile-id, --message, or --drain")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
