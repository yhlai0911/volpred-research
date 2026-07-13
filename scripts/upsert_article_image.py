#!/usr/bin/env python3
"""Overwrite an existing Supabase article image in-place (same public URL).

Used when a chart already embedded in a published article has to be corrected
(wrong font, wrong numbers, wrong axis). Re-uploading at the SAME object key
fixes the live article without touching feed.json or re-publishing.

Usage:
    uv run python scripts/upsert_article_image.py \
        --local storage/event_articles/<slug>/fig1.png \
        --url   https://<proj>.supabase.co/storage/v1/object/public/article-images/<key>.png

Exit 0 only when Supabase confirms the upsert.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_MARKER = "/storage/v1/object/public/"


def _load_credentials() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") or os.environ.get("SUPABASE_KEY", "")
    for env_file in (".env.local", ".env"):
        if url and key:
            break
        env_path = REPO_ROOT / env_file
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            if "=" not in line or line.lstrip().startswith("#"):
                continue
            k, v = line.strip().split("=", 1)
            if k == "SUPABASE_URL" and not url:
                url = v
            elif k in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_KEY") and not key:
                key = v
    if not url or not key:
        raise SystemExit("[FAIL] SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 未設定（env 或 .env.local）")
    return url.rstrip("/"), key


def _object_path(public_url: str) -> str:
    """Extract '<bucket>/<key>' from a Supabase public URL."""
    parsed = urlparse(public_url)
    if PUBLIC_MARKER not in parsed.path:
        raise SystemExit(f"[FAIL] 不是 Supabase public URL（缺 {PUBLIC_MARKER}）: {public_url}")
    return parsed.path.split(PUBLIC_MARKER, 1)[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", required=True, help="修正後的本地 PNG")
    ap.add_argument("--url", required=True, help="線上既有的 public URL（將被就地覆蓋）")
    ap.add_argument("--dry-run", action="store_true", help="只解析 object key，不上傳")
    args = ap.parse_args()

    local = Path(args.local)
    if not local.is_file():
        raise SystemExit(f"[FAIL] 本地檔不存在: {local}")

    object_path = _object_path(args.url)
    print(f"[INFO] {local} → {object_path} ({local.stat().st_size} bytes)")
    if args.dry_run:
        print("[DRY-RUN] 未上傳")
        return 0

    base, key = _load_credentials()
    resp = requests.post(
        f"{base}/storage/v1/object/{object_path}",
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "Content-Type": "image/png",
            "x-upsert": "true",
        },
        data=local.read_bytes(),
        timeout=60,
    )
    if resp.status_code not in (200, 201):
        print(f"[FAIL] upsert 失敗 HTTP {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
        return 1
    print(f"[OK] 已覆蓋 → {args.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
