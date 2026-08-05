#!/usr/bin/env python3
"""Inspect and release the write claims held by concurrent sessions.

Claims are taken automatically by scripts/hooks/write_claim_guard.py on every
Edit/Write; this CLI is how a human or the manager sees who is working where and
clears a claim whose session is gone.

  uv run python scripts/path_claims.py list
  uv run python scripts/path_claims.py release --scope scripts/org/
  uv run python scripts/path_claims.py release --all-expired
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "hooks"))
from write_claim_guard import CLAIM_DIR, _claim_path  # noqa: E402


def _load_all() -> list[dict]:
    claims = []
    if not CLAIM_DIR.is_dir():
        return claims
    for path in sorted(CLAIM_DIR.glob("*.json")):
        try:
            claim = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):  # silent-ok: not silent — surfaced to the user as "(unreadable)" below
            claims.append({"scope": f"(unreadable {path.name})", "expires_at": 0})
            continue
        claim["_file"] = str(path)
        claims.append(claim)
    return claims


def cmd_list(args: argparse.Namespace) -> int:
    now = time.time()
    claims = _load_all()
    live = [c for c in claims if float(c.get("expires_at", 0)) > now]
    if args.as_json:
        print(json.dumps(claims, ensure_ascii=False, indent=2, default=str))
        return 0
    if not claims:
        print("沒有任何寫入認領（沒有 session 正在編輯受管路徑）")
        return 0
    print(f"{'scope':<40}{'session':<12}{'actor':<16}剩餘")
    for c in claims:
        remaining = int(float(c.get("expires_at", 0)) - now)
        state = f"{remaining // 60}分" if remaining > 0 else "已過期"
        print(f"{str(c.get('scope'))[:38]:<40}{str(c.get('session_id'))[:10]:<12}"
              f"{str(c.get('actor'))[:14]:<16}{state}")
    print(f"\n{len(live)} 個生效中 / {len(claims)} 個檔案")
    return 0


def cmd_release(args: argparse.Namespace) -> int:
    now = time.time()
    released = 0
    if args.all_expired:
        for c in _load_all():
            if float(c.get("expires_at", 0)) <= now and c.get("_file"):
                Path(c["_file"]).unlink(missing_ok=True)
                released += 1
                print(f"released expired: {c.get('scope')}")
    elif args.scope:
        path = _claim_path(args.scope)
        if path.exists():
            path.unlink()
            released = 1
            print(f"released: {args.scope}")
        else:
            print(f"沒有 {args.scope} 的認領")
    else:
        print("需要 --scope 或 --all-expired", file=sys.stderr)
        return 2
    return 0 if released or args.all_expired else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="who is editing what right now")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("release", help="clear a claim whose session has stopped")
    p.add_argument("--scope")
    p.add_argument("--all-expired", action="store_true")
    p.set_defaults(func=cmd_release)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
